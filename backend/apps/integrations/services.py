import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from datetime import timedelta
from typing import Any

from django.core import signing
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.audit import append_audit
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, RowVersionConflict
from apps.courses.services import ActorContext

from .crypto import digest, generate_secret, hash_secret, seal, sign_webhook, unseal
from .metrics import WEBHOOK_ATTEMPTS_TOTAL, WEBHOOK_DELIVERIES_TOTAL
from .models import (
    APIClient,
    APIClientGrant,
    OIDCIdentity,
    OIDCProvider,
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookEndpoint,
)

logger = logging.getLogger(__name__)
TOKEN_TTL_SECONDS = 900


def create_access_token(*, client: APIClient, scopes: list[str]) -> str:
    return signing.dumps(
        {"client_id": client.client_id, "scopes": scopes, "issued_at": int(time.time())},
        salt="integration-access-token",
    )


def verify_access_token(token: str) -> dict[str, Any]:
    return signing.loads(token, salt="integration-access-token", max_age=TOKEN_TTL_SECONDS)


def authenticate_client(*, client_id: str, secret: str) -> tuple[APIClient, str]:
    client = APIClient.objects.filter(client_id=client_id, status=APIClient.Status.ACTIVE).first()
    if client is None:
        raise ResourceNotFound()
    valid = hash_secret(secret) == client.secret_hash
    if (
        not valid
        and client.previous_secret_hash
        and client.previous_secret_expires_at
        and client.previous_secret_expires_at > timezone.now()
    ):
        valid = hash_secret(secret) == client.previous_secret_hash
    if not valid:
        raise ResourceNotFound()
    scopes = list(client.allowed_scopes)
    scopes.extend(
        APIClientGrant.objects.filter(client=client, status="ACTIVE").values_list(
            "scope", flat=True
        )
    )
    return client, create_access_token(client=client, scopes=sorted(set(scopes)))


def create_api_client(
    *,
    actor: User,
    name: str,
    scopes: list[str],
    context: ActorContext,
    rate_limit_per_minute: int = 60,
) -> tuple[APIClient, str]:
    secret = generate_secret("edu_")
    item = APIClient.objects.create(
        client_id=generate_secret("client_")[:48],
        name=name,
        secret_hash=hash_secret(secret),
        allowed_scopes=scopes,
        rate_limit_per_minute=rate_limit_per_minute,
        created_by=actor,
    )
    append_audit(
        actor_ref=actor.public_id,
        actor_portal=context.portal,
        actor_context={},
        action="integrations.api_client.create",
        target_type="api_client",
        target_ref=item.public_id,
        after={"scopes": scopes},
        result="SUCCEEDED",
        trace_id=context.trace_id,
    )
    return item, secret


@transaction.atomic
def rotate_api_client_secret(
    *, item: APIClient, actor: User, expected_version: int, context: ActorContext
) -> tuple[APIClient, str]:
    secret = generate_secret("edu_")
    updated = compare_and_swap(
        APIClient,
        pk=item.pk,
        expected_version=expected_version,
        changes={
            "previous_secret_hash": item.secret_hash,
            "previous_secret_expires_at": timezone.now() + timedelta(minutes=15),
            "secret_hash": hash_secret(secret),
        },
    )
    append_audit(
        actor_ref=actor.public_id,
        actor_portal=context.portal,
        actor_context={},
        action="integrations.api_client.rotate_secret",
        target_type="api_client",
        target_ref=item.public_id,
        result="SUCCEEDED",
        trace_id=context.trace_id,
    )
    return updated, secret


def create_oidc_provider(
    *, actor: User, data: dict[str, Any], context: ActorContext
) -> tuple[OIDCProvider, str]:
    values = dict(data)
    secret = str(values.pop("client_secret"))
    values["issuer_hash"] = digest(str(values["issuer"]))
    values["client_secret_ciphertext"] = seal(secret)
    item = OIDCProvider.objects.create(**values)
    append_audit(
        actor_ref=actor.public_id,
        actor_portal=context.portal,
        actor_context={},
        action="integrations.oidc_provider.create",
        target_type="oidc_provider",
        target_ref=item.public_id,
        result="SUCCEEDED",
        trace_id=context.trace_id,
    )
    return item, secret


@transaction.atomic
def rotate_oidc_secret(
    *, item: OIDCProvider, actor: User, expected_version: int, context: ActorContext
) -> tuple[OIDCProvider, str]:
    secret = generate_secret("oidc_")
    updated = compare_and_swap(
        OIDCProvider,
        pk=item.pk,
        expected_version=expected_version,
        changes={
            "previous_client_secret_ciphertext": item.client_secret_ciphertext,
            "previous_secret_expires_at": timezone.now() + timedelta(minutes=15),
            "client_secret_ciphertext": seal(secret),
        },
    )
    append_audit(
        actor_ref=actor.public_id,
        actor_portal=context.portal,
        actor_context={},
        action="integrations.oidc_provider.rotate_secret",
        target_type="oidc_provider",
        target_ref=item.public_id,
        result="SUCCEEDED",
        trace_id=context.trace_id,
    )
    return updated, secret


def bind_oidc_identity(
    *, provider: OIDCProvider, account: User, subject: str, context: ActorContext
) -> OIDCIdentity:
    issuer_hash = digest(provider.issuer)
    subject_hash = digest(subject)
    try:
        with transaction.atomic():
            existing = (
                OIDCIdentity.objects.select_for_update()
                .filter(issuer_hash=issuer_hash, subject_hash=subject_hash)
                .first()
            )
            if existing and existing.account_id != account.id:
                raise RowVersionConflict(detail={"reason": "OIDC_SUBJECT_ALREADY_BOUND"})
            item, _ = OIDCIdentity.objects.select_for_update().get_or_create(
                provider=provider,
                account=account,
                defaults={
                    "issuer_hash": issuer_hash,
                    "subject_hash": subject_hash,
                    "subject_hint": subject[-8:],
                    "last_authenticated_at": timezone.now(),
                },
            )
    except IntegrityError as exc:
        # A concurrent bind can win either unique constraint between the read
        # and insert. Re-read it and return the same domain conflict instead
        # of leaking a database error or silently merging identities.
        existing = OIDCIdentity.objects.filter(
            issuer_hash=issuer_hash, subject_hash=subject_hash
        ).first()
        if existing is None or existing.account_id != account.id:
            raise RowVersionConflict(detail={"reason": "OIDC_SUBJECT_ALREADY_BOUND"}) from exc
        item = existing
    if item.status != OIDCIdentity.Status.ACTIVE:
        item = compare_and_swap(
            OIDCIdentity,
            pk=item.pk,
            expected_version=item.row_version,
            changes={"status": OIDCIdentity.Status.ACTIVE, "last_authenticated_at": timezone.now()},
        )
    append_audit(
        actor_ref=account.public_id,
        actor_portal=context.portal,
        actor_context={},
        action="integrations.oidc_identity.bind",
        target_type="oidc_identity",
        target_ref=item.public_id,
        result="SUCCEEDED",
        trace_id=context.trace_id,
    )
    return item


@transaction.atomic
def unlink_oidc_identity(
    *, item: OIDCIdentity, actor: User, expected_version: int, context: ActorContext
) -> OIDCIdentity:
    updated = compare_and_swap(
        OIDCIdentity,
        pk=item.pk,
        expected_version=expected_version,
        changes={"status": OIDCIdentity.Status.UNLINKED},
    )
    append_audit(
        actor_ref=actor.public_id,
        actor_portal=context.portal,
        actor_context={},
        action="integrations.oidc_identity.unlink",
        target_type="oidc_identity",
        target_ref=item.public_id,
        before={"status": item.status},
        after={"status": updated.status},
        result="SUCCEEDED",
        trace_id=context.trace_id,
    )
    return updated


def create_webhook_delivery(
    *, endpoint: WebhookEndpoint, event_id: str, event_type: str, payload: dict[str, Any]
) -> WebhookDelivery:
    if endpoint.status != WebhookEndpoint.Status.ACTIVE:
        raise ValueError("webhook endpoint is disabled")
    if endpoint.event_allowlist and event_type not in endpoint.event_allowlist:
        raise ValueError("event type is not allowed for webhook endpoint")
    body = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    try:
        with transaction.atomic():
            return WebhookDelivery.objects.create(
                endpoint=endpoint,
                event_id=event_id,
                event_type=event_type,
                body_digest=hashlib.sha256(body.encode()).hexdigest(),
                payload=payload,
            )
    except IntegrityError:
        return WebhookDelivery.objects.get(endpoint=endpoint, event_id=event_id)


@transaction.atomic
def deliver_webhook(
    *, delivery: WebhookDelivery, trace_id: str = "", timeout_seconds: int = 5
) -> WebhookDelivery:
    delivery = (
        WebhookDelivery.objects.select_for_update()
        .select_related("endpoint")
        .get(pk=delivery.pk)
    )
    if delivery.status not in (WebhookDelivery.Status.PENDING, WebhookDelivery.Status.RETRY):
        return delivery
    endpoint = delivery.endpoint
    body = json.dumps(
        delivery.payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()
    started = timezone.now()
    attempt_no = delivery.attempt_count + 1
    timestamp = int(time.time())
    signature = sign_webhook(
        secret=unseal(endpoint.secret_ciphertext),
        delivery_id=delivery.public_id,
        timestamp=timestamp,
        body=body,
    )
    request = urllib.request.Request(
        unseal(endpoint.endpoint_url_ciphertext),
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Delivery": delivery.public_id,
            "X-Webhook-Timestamp": str(timestamp),
            "X-Webhook-Signature": f"v1={signature}",
        },
    )
    status_code = None
    result = "FAILED"
    summary = ""
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(response.status)
            result = "DELIVERED" if 200 <= status_code < 300 else "RETRY"
            summary = f"HTTP {status_code}"
    except (urllib.error.URLError, TimeoutError) as exc:
        summary = type(exc).__name__
    WebhookDeliveryAttempt.objects.create(
        delivery=delivery,
        attempt_no=attempt_no,
        request_digest=hashlib.sha256(body).hexdigest(),
        response_status=status_code,
        response_summary_masked=summary,
        result=result,
        started_at=started,
        finished_at=timezone.now(),
    )
    WEBHOOK_ATTEMPTS_TOTAL.labels(result=result).inc()
    status = (
        WebhookDelivery.Status.DELIVERED
        if result == "DELIVERED"
        else (
            WebhookDelivery.Status.DEAD
            if attempt_no >= delivery.max_attempts
            else WebhookDelivery.Status.RETRY
        )
    )
    changes = {
        "attempt_count": attempt_no,
        "last_status_code": status_code,
        "last_response_masked": summary,
        "status": status,
        "delivered_at": timezone.now() if status == WebhookDelivery.Status.DELIVERED else None,
        "next_retry_at": None
        if status in (WebhookDelivery.Status.DELIVERED, WebhookDelivery.Status.DEAD)
        else timezone.now() + timedelta(seconds=min(2 ** max(attempt_no - 1, 0), 900)),
    }
    updated = compare_and_swap(
        WebhookDelivery, pk=delivery.pk, expected_version=delivery.row_version, changes=changes
    )
    WEBHOOK_DELIVERIES_TOTAL.labels(result=updated.status).inc()
    return updated
