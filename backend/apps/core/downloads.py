import hashlib
import secrets
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User

from .audit import append_audit, hash_client_ip
from .concurrency import compare_and_swap
from .errors import DownloadGrantInvalid, DownloadScopeDenied, ResourceNotFound
from .models import FileDownloadGrant, ObjectAsset
from .outbox import append_outbox_event, enqueue_relay_after_commit

DownloadAuthorizer = Callable[[ObjectAsset, User, str], str]
DownloadGrantObserver = Callable[[FileDownloadGrant, User, str, str], None]
_authorizers: dict[str, DownloadAuthorizer] = {}
_grant_observers: list[DownloadGrantObserver] = []


def register_download_authorizer(owner_type: str, handler: DownloadAuthorizer) -> None:
    if owner_type in _authorizers:
        raise ValueError(f"Download authorizer already registered: {owner_type}")
    _authorizers[owner_type] = handler


def register_download_grant_observer(handler: DownloadGrantObserver) -> None:
    if handler not in _grant_observers:
        _grant_observers.append(handler)


def _course_scope(asset: ObjectAsset, actor: User, portal: str) -> str:
    handler = _authorizers.get(asset.owner_type)
    if handler is None:
        raise ResourceNotFound()
    try:
        return handler(asset, actor, portal)
    except (DownloadScopeDenied, ResourceNotFound):
        raise
    except Exception as exc:
        raise ResourceNotFound() from exc


def _audit(
    *,
    actor: User,
    portal: str,
    action: str,
    target_ref: str,
    course_ref: str,
    trace_id: str,
    after: Any = None,
    client_ip: str = "",
    user_agent: str = "",
) -> None:
    append_audit(
        actor_ref=actor.public_id,
        actor_portal=portal,
        actor_context={},
        action=action,
        target_type="file_download_grant",
        target_ref=target_ref,
        course_ref=course_ref,
        after=after,
        result="SUCCEEDED",
        client_ip_hash=hash_client_ip(client_ip, salt=settings.AUDIT_IP_HASH_SALT),
        user_agent_summary=user_agent,
        trace_id=trace_id,
    )


def _emit(*, grant: FileDownloadGrant, event_type: str, trace_id: str) -> None:
    append_outbox_event(
        event_type=event_type,
        aggregate_type="file_download_grant",
        aggregate_ref=grant.public_id,
        payload={
            "grant_id": grant.public_id,
            "asset_id": grant.asset.public_id,
            "course_id": grant.course_ref,
            "portal": grant.portal,
        },
        trace_id=trace_id,
    )
    enqueue_relay_after_commit(trace_id=trace_id)


@transaction.atomic
def create_download_grant(
    *,
    asset_id: str,
    actor: User,
    portal: str,
    trace_id: str,
    token: str | None = None,
    client_ip: str = "",
    user_agent: str = "",
    ttl_seconds: int | None = None,
    max_downloads: int = 1,
) -> tuple[FileDownloadGrant, str]:
    try:
        asset = ObjectAsset.objects.get(public_id=asset_id, status=ObjectAsset.Status.ACTIVE)
    except ObjectAsset.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    course_ref = _course_scope(asset, actor, portal)
    if asset.scan_status != ObjectAsset.ScanStatus.CLEAN:
        raise DownloadGrantInvalid(detail={"asset_status": asset.scan_status})
    token = token or secrets.token_urlsafe(32)
    configured_ttl = (
        ttl_seconds
        if ttl_seconds is not None
        else int(getattr(settings, "FILE_DOWNLOAD_GRANT_TTL_SECONDS", 300))
    )
    ttl = max(1, min(int(configured_ttl), 900))
    expires_at = timezone.now() + timedelta(seconds=ttl)
    if asset.retention_until is not None:
        if asset.retention_until <= timezone.now():
            raise DownloadGrantInvalid(detail={"asset_status": "RETENTION_EXPIRED"})
        expires_at = min(expires_at, asset.retention_until)
    grant = FileDownloadGrant.objects.create(
        asset=asset,
        requested_by=actor,
        portal=portal,
        course_ref=course_ref,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=expires_at,
        max_downloads=max(1, min(int(max_downloads), 100)),
    )
    _audit(
        actor=actor,
        portal=portal,
        action="file.download_grant.create",
        target_ref=grant.public_id,
        course_ref=course_ref,
        trace_id=trace_id,
        after={"asset_id": asset.public_id, "expires_at": grant.expires_at.isoformat()},
        client_ip=client_ip,
        user_agent=user_agent,
    )
    _emit(grant=grant, event_type="file.download_grant.created", trace_id=trace_id)
    for observer in _grant_observers:
        observer(grant, actor, portal, trace_id)
    return grant, token


def get_download_target(
    *, token: str, actor: User, portal: str
) -> tuple[FileDownloadGrant, ObjectAsset]:
    digest = hashlib.sha256(token.encode()).hexdigest()
    try:
        grant = FileDownloadGrant.objects.select_related("asset", "requested_by").get(
            token_hash=digest
        )
    except FileDownloadGrant.DoesNotExist as exc:
        raise DownloadGrantInvalid() from exc
    _validate_download_grant(grant=grant, actor=actor, portal=portal)
    if _course_scope(grant.asset, actor, portal) != grant.course_ref:
        raise DownloadGrantInvalid()
    if grant.asset.status != ObjectAsset.Status.ACTIVE:
        raise DownloadGrantInvalid()
    if grant.asset.scan_status != ObjectAsset.ScanStatus.CLEAN:
        raise DownloadGrantInvalid(detail={"asset_status": grant.asset.scan_status})
    return grant, grant.asset


def _validate_download_grant(*, grant: FileDownloadGrant, actor: User, portal: str) -> None:
    if (
        grant.requested_by_id != actor.pk
        or grant.portal != portal
        or grant.revoked_at is not None
        or grant.expires_at <= timezone.now()
        or grant.download_count >= grant.max_downloads
    ):
        raise DownloadGrantInvalid()


@transaction.atomic
def consume_download_grant(
    *,
    grant_id: int,
    actor: User,
    portal: str,
    trace_id: str,
    client_ip: str = "",
    user_agent: str = "",
) -> FileDownloadGrant:
    try:
        grant = (
            FileDownloadGrant.objects.select_for_update()
            .select_related("asset", "requested_by")
            .get(pk=grant_id)
        )
    except FileDownloadGrant.DoesNotExist as exc:
        raise DownloadGrantInvalid() from exc
    _validate_download_grant(grant=grant, actor=actor, portal=portal)
    if _course_scope(grant.asset, actor, portal) != grant.course_ref:
        raise DownloadGrantInvalid()
    if (
        grant.asset.scan_status != ObjectAsset.ScanStatus.CLEAN
        or grant.asset.status != ObjectAsset.Status.ACTIVE
    ):
        raise DownloadGrantInvalid()
    updated = compare_and_swap(
        FileDownloadGrant,
        pk=grant.pk,
        expected_version=grant.row_version,
        changes={"download_count": grant.download_count + 1},
    )
    _audit(
        actor=actor,
        portal=portal,
        action="file.download_grant.consume",
        target_ref=grant.public_id,
        course_ref=grant.course_ref,
        trace_id=trace_id,
        after={"download_count": updated.download_count},
        client_ip=client_ip,
        user_agent=user_agent,
    )
    return updated  # type: ignore[return-value]


@transaction.atomic
def revoke_download_grant(
    *,
    grant_id: str,
    actor: User,
    portal: str,
    expected_version: int,
    trace_id: str,
    client_ip: str = "",
    user_agent: str = "",
) -> FileDownloadGrant:
    try:
        grant = FileDownloadGrant.objects.select_for_update().get(
            public_id=grant_id, requested_by=actor, portal=portal
        )
    except FileDownloadGrant.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if grant.revoked_at is not None:
        return grant
    changed = compare_and_swap(
        FileDownloadGrant,
        pk=grant.pk,
        expected_version=expected_version,
        changes={"revoked_at": timezone.now()},
    )
    _audit(
        actor=actor,
        portal=portal,
        action="file.download_grant.revoke",
        target_ref=grant.public_id,
        course_ref=grant.course_ref,
        trace_id=trace_id,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    _emit(grant=changed, event_type="file.download_grant.revoked", trace_id=trace_id)
    return changed  # type: ignore[return-value]
