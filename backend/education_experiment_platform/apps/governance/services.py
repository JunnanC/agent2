import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from redis import Redis

from apps.accounts.models import User
from apps.core.audit import append_audit, hash_client_ip
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound, RowVersionConflict
from apps.core.outbox import append_outbox_event, enqueue_relay_after_commit
from apps.courses.models import Course

from . import events
from .errors import (
    BudgetExceeded,
    GovernanceStateConflict,
    GovernanceValidationError,
    ImageNotApproved,
    QuotaExceeded,
    QuotaNotConfigured,
    ScalingCooldownActive,
)
from .metrics import QUOTA_OPERATIONS
from .models import (
    ImageAsset,
    NetworkAllowlist,
    Quota,
    QuotaReservation,
    ResourceProfile,
    RuntimeAdapter,
    SecurityPolicy,
)
from .selectors import LIMIT_FIELDS, USAGE_TO_LIMIT, reservation_usage

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)

QUOTA_VALUE_FIELDS = frozenset(LIMIT_FIELDS)
RESERVATION_VALUE_FIELDS = frozenset(USAGE_TO_LIMIT)


def validate_resource_profile(profile_data: dict[str, Any]) -> dict[str, int]:
    """Normalize legacy resource fields and validate request/limit semantics."""
    cpu = int(profile_data.get("cpu_millicores") or 0)
    memory = int(profile_data.get("memory_mb") or 0)
    cpu_request = int(
        profile_data["cpu_request_millicores"]
        if profile_data.get("cpu_request_millicores") is not None
        else cpu
    )
    cpu_limit = int(
        profile_data["cpu_limit_millicores"]
        if profile_data.get("cpu_limit_millicores") is not None
        else cpu
    )
    memory_request = int(
        profile_data["memory_request_mb"]
        if profile_data.get("memory_request_mb") is not None
        else memory
    )
    memory_limit = int(
        profile_data["memory_limit_mb"]
        if profile_data.get("memory_limit_mb") is not None
        else memory
    )
    disk = int(profile_data.get("disk_gb") or 0)
    if min(cpu, memory, disk, cpu_request, cpu_limit, memory_request, memory_limit) <= 0:
        raise GovernanceValidationError(detail={"resource": "positive_values_required"})
    if cpu_request > cpu_limit or memory_request > memory_limit:
        raise GovernanceValidationError(detail={"resource": "request_exceeds_limit"})
    return {
        "cpu_millicores": cpu,
        "memory_mb": memory,
        "cpu_request_millicores": cpu_request,
        "cpu_limit_millicores": cpu_limit,
        "memory_request_mb": memory_request,
        "memory_limit_mb": memory_limit,
        "disk_gb": disk,
    }


def effective_resource_profile(task: Any) -> dict[str, Any]:
    """Return the frozen task profile, with legacy snapshots normalized."""
    profile = getattr(task, "resource_profile", None) or task.template_version.resource_profile
    snapshot = dict(getattr(task, "resource_profile_snapshot", None) or {})

    def value(name: str, fallback: Any) -> Any:
        return snapshot[name] if snapshot.get(name) is not None else fallback

    cpu = value("cpu_millicores", profile.cpu_millicores)
    memory = value("memory_mb", profile.memory_mb)
    return {
        "public_id": value("public_id", profile.public_id),
        "code": value("code", profile.code),
        "runtime_type": value("runtime_type", profile.runtime_type),
        "cpu_millicores": cpu,
        "memory_mb": memory,
        "cpu_request_millicores": value(
            "cpu_request_millicores", getattr(profile, "cpu_request_millicores", None) or cpu
        ),
        "cpu_limit_millicores": value(
            "cpu_limit_millicores", getattr(profile, "cpu_limit_millicores", None) or cpu
        ),
        "memory_request_mb": value(
            "memory_request_mb", getattr(profile, "memory_request_mb", None) or memory
        ),
        "memory_limit_mb": value(
            "memory_limit_mb", getattr(profile, "memory_limit_mb", None) or memory
        ),
        "disk_gb": value("disk_gb", profile.disk_gb),
        "network_mode": value("network_mode", profile.network_mode),
    }


@dataclass(frozen=True)
class ActorContext:
    actor_ref: str
    portal: str
    trace_id: str
    client_ip: str = ""
    user_agent: str = ""


def _audit(
    context: ActorContext,
    *,
    action: str,
    target_type: str,
    target_ref: str,
    course_ref: str = "",
    before: Any = None,
    after: Any = None,
) -> None:
    append_audit(
        actor_ref=context.actor_ref,
        actor_portal=context.portal,
        actor_context={},
        action=action,
        target_type=target_type,
        target_ref=target_ref,
        course_ref=course_ref,
        before=before,
        after=after,
        result="SUCCEEDED",
        client_ip_hash=hash_client_ip(context.client_ip, salt=settings.AUDIT_IP_HASH_SALT),
        user_agent_summary=context.user_agent,
        trace_id=context.trace_id,
    )


def _event(
    context: ActorContext,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_ref: str,
    payload: dict[str, Any],
) -> None:
    append_outbox_event(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_ref=aggregate_ref,
        payload=payload,
        trace_id=context.trace_id,
    )
    enqueue_relay_after_commit(trace_id=context.trace_id)


def _ensure_expected(actual: int, expected: int) -> None:
    if actual != expected:
        raise RowVersionConflict(
            detail={"expected_row_version": expected, "actual_row_version": actual}
        )


def _reason(value: str) -> str:
    clean = value.strip()
    if not clean:
        raise GovernanceValidationError(detail={"reason": "required"})
    return clean


def _validate_runtime_adapter_definition(
    *, runtime_type: str, driver: str, config_ref: str
) -> str:
    """Validate immutable driver facts before they reach the runtime worker."""
    if (
        runtime_type not in RuntimeAdapter.RuntimeType.values
        or driver not in RuntimeAdapter.Driver.values
    ):
        raise GovernanceValidationError(detail={"runtime_type": runtime_type, "driver": driver})
    clean_ref = config_ref.strip()
    if driver == RuntimeAdapter.Driver.DOCKER_LOCAL:
        if runtime_type != RuntimeAdapter.RuntimeType.CONTAINER:
            raise GovernanceValidationError(
                detail={"driver": driver, "runtime_type": runtime_type}
            )
        if not clean_ref:
            raise GovernanceValidationError(detail={"config_ref": "required_for_docker_local"})
    return clean_ref


def _scope(
    *, scope_type: str, course_id: str | None = None, user_id: str | None = None
) -> tuple[str, Course | None, User | None]:
    if scope_type == Quota.ScopeType.PLATFORM:
        if course_id or user_id:
            raise GovernanceValidationError(detail={"scope": "platform_has_no_target"})
        return "PLATFORM", None, None
    if scope_type == Quota.ScopeType.COURSE:
        if not course_id or user_id:
            raise GovernanceValidationError(detail={"scope": "course_target_required"})
        try:
            course = Course.objects.get(public_id=course_id)
        except Course.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        return f"COURSE:{course.public_id}", course, None
    if scope_type == Quota.ScopeType.USER:
        if not user_id or course_id:
            raise GovernanceValidationError(detail={"scope": "user_target_required"})
        try:
            user = User.objects.get(public_id=user_id)
        except User.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        return f"USER:{user.public_id}", None, user
    raise GovernanceValidationError(detail={"scope_type": scope_type})


def _policy_scope(*, scope_type: str, course_id: str | None) -> tuple[str, Course | None]:
    if scope_type == SecurityPolicy.ScopeType.PLATFORM and not course_id:
        return "PLATFORM", None
    if scope_type == SecurityPolicy.ScopeType.COURSE and course_id:
        try:
            course = Course.objects.get(public_id=course_id)
        except Course.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        return f"COURSE:{course.public_id}", course
    raise GovernanceValidationError(detail={"scope": "invalid_policy_scope"})


@transaction.atomic
def create_runtime_adapter(
    *,
    actor: User,
    code: str,
    name: str,
    runtime_type: str,
    driver: str,
    config_ref: str,
    reason: str,
    context: ActorContext,
) -> RuntimeAdapter:
    clean_config_ref = _validate_runtime_adapter_definition(
        runtime_type=runtime_type, driver=driver, config_ref=config_ref
    )
    try:
        adapter = RuntimeAdapter.objects.create(
            code=code.strip().upper(),
            name=name.strip(),
            runtime_type=runtime_type,
            driver=driver,
            config_ref=clean_config_ref,
            change_reason=_reason(reason),
        )
    except IntegrityError as exc:
        raise GovernanceStateConflict(detail={"code": code}) from exc
    _audit(
        context,
        action="governance.runtime_adapter.create",
        target_type="runtime_adapter",
        target_ref=adapter.public_id,
        after={"code": adapter.code, "driver": adapter.driver, "status": adapter.status},
    )
    _event(
        context,
        event_type=events.RUNTIME_ADAPTER_CHANGED,
        aggregate_type="runtime_adapter",
        aggregate_ref=adapter.public_id,
        payload={"adapter_id": adapter.public_id, "status": adapter.status},
    )
    return adapter


@transaction.atomic
def update_runtime_adapter(
    *,
    adapter_id: str,
    actor: User,
    expected_version: int,
    changes: dict[str, Any],
    reason: str,
    context: ActorContext,
) -> RuntimeAdapter:
    try:
        adapter = RuntimeAdapter.objects.select_for_update().get(public_id=adapter_id)
    except RuntimeAdapter.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    clean = {key: changes[key] for key in ("name", "config_ref", "status") if key in changes}
    if "status" in clean and clean["status"] not in RuntimeAdapter.Status.values:
        raise GovernanceValidationError(detail={"status": clean["status"]})
    if "config_ref" in clean:
        clean["config_ref"] = _validate_runtime_adapter_definition(
            runtime_type=adapter.runtime_type,
            driver=adapter.driver,
            config_ref=str(clean["config_ref"]),
        )
    clean["change_reason"] = _reason(reason)
    changed = compare_and_swap(
        RuntimeAdapter,
        pk=adapter.pk,
        expected_version=expected_version,
        changes=clean,
    )
    _audit(
        context,
        action="governance.runtime_adapter.update",
        target_type="runtime_adapter",
        target_ref=adapter.public_id,
        before={key: getattr(adapter, key) for key in clean},
        after={key: getattr(changed, key) for key in clean},
    )
    _event(
        context,
        event_type=events.RUNTIME_ADAPTER_CHANGED,
        aggregate_type="runtime_adapter",
        aggregate_ref=adapter.public_id,
        payload={"adapter_id": adapter.public_id, "status": changed.status},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def record_runtime_health(
    *,
    adapter_id: str,
    health_status: str,
    node_count: int,
    capacity_cpu_millicores: int,
    available_cpu_millicores: int,
    capacity_memory_mb: int,
    available_memory_mb: int,
    detail: dict[str, Any],
    trace_id: str,
) -> RuntimeAdapter:
    try:
        adapter = RuntimeAdapter.objects.select_for_update().get(public_id=adapter_id)
    except RuntimeAdapter.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if health_status not in RuntimeAdapter.HealthStatus.values:
        raise GovernanceValidationError(detail={"health_status": health_status})
    if (
        available_cpu_millicores > capacity_cpu_millicores
        or available_memory_mb > capacity_memory_mb
    ):
        raise GovernanceValidationError(detail={"capacity": "available_exceeds_total"})
    previous = adapter.health_status
    changed = compare_and_swap(
        RuntimeAdapter,
        pk=adapter.pk,
        expected_version=adapter.row_version,
        changes={
            "health_status": health_status,
            "node_count": node_count,
            "capacity_cpu_millicores": capacity_cpu_millicores,
            "available_cpu_millicores": available_cpu_millicores,
            "capacity_memory_mb": capacity_memory_mb,
            "available_memory_mb": available_memory_mb,
            "last_health_at": timezone.now(),
            "health_detail": detail,
        },
    )
    if previous != health_status:
        append_outbox_event(
            event_type=events.RUNTIME_HEALTH_CHANGED,
            aggregate_type="runtime_adapter",
            aggregate_ref=adapter.public_id,
            payload={"adapter_id": adapter.public_id, "health_status": health_status},
            trace_id=trace_id,
        )
        enqueue_relay_after_commit(trace_id=trace_id)
    return changed  # type: ignore[return-value]


@transaction.atomic
def create_image(
    *,
    actor: User,
    registry: str,
    repository: str,
    display_tag: str,
    digest: str,
    risk_level: str,
    reason: str,
    context: ActorContext,
) -> ImageAsset:
    if not DIGEST_RE.fullmatch(digest):
        raise GovernanceValidationError(detail={"digest": "sha256_required"})
    if risk_level not in ImageAsset.RiskLevel.values:
        raise GovernanceValidationError(detail={"risk_level": risk_level})
    try:
        image = ImageAsset.objects.create(
            registry=registry.strip().lower(),
            repository=repository.strip(),
            display_tag=display_tag.strip(),
            digest=digest,
            risk_level=risk_level,
            change_reason=_reason(reason),
        )
    except IntegrityError as exc:
        raise GovernanceStateConflict(detail={"digest": digest}) from exc
    _audit(
        context,
        action="governance.image.create",
        target_type="image_asset",
        target_ref=image.public_id,
        after={"digest": image.digest, "approval_status": image.approval_status},
    )
    _event(
        context,
        event_type=events.IMAGE_CHANGED,
        aggregate_type="image_asset",
        aggregate_ref=image.public_id,
        payload={"image_id": image.public_id, "digest": image.digest},
    )
    return image


@transaction.atomic
def update_image_scan(
    *,
    image_id: str,
    expected_version: int,
    scan_status: str,
    scan_report_ref: str,
    risk_level: str,
    reason: str,
    actor: User,
    context: ActorContext,
) -> ImageAsset:
    try:
        image = ImageAsset.objects.select_for_update().get(public_id=image_id)
    except ImageAsset.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if image.approval_status == ImageAsset.ApprovalStatus.APPROVED:
        raise GovernanceStateConflict(detail={"approval_status": image.approval_status})
    if (
        scan_status not in ImageAsset.ScanStatus.values
        or risk_level not in ImageAsset.RiskLevel.values
    ):
        raise GovernanceValidationError(
            detail={"scan_status": scan_status, "risk_level": risk_level}
        )
    changed = compare_and_swap(
        ImageAsset,
        pk=image.pk,
        expected_version=expected_version,
        changes={
            "scan_status": scan_status,
            "scan_report_ref": scan_report_ref.strip(),
            "risk_level": risk_level,
            "scanned_at": timezone.now(),
            "change_reason": _reason(reason),
        },
    )
    _audit(
        context,
        action="governance.image.scan",
        target_type="image_asset",
        target_ref=image.public_id,
        before={"scan_status": image.scan_status},
        after={"scan_status": changed.scan_status, "risk_level": changed.risk_level},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def decide_image(
    *,
    image_id: str,
    actor: User,
    expected_version: int,
    decision: str,
    reason: str,
    context: ActorContext,
) -> ImageAsset:
    try:
        image = ImageAsset.objects.select_for_update().get(public_id=image_id)
    except ImageAsset.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if decision not in {
        ImageAsset.ApprovalStatus.APPROVED,
        ImageAsset.ApprovalStatus.REJECTED,
        ImageAsset.ApprovalStatus.RETIRED,
    }:
        raise GovernanceValidationError(detail={"decision": decision})
    if (
        decision == ImageAsset.ApprovalStatus.APPROVED
        and image.scan_status != ImageAsset.ScanStatus.CLEAN
    ):
        raise ImageNotApproved(detail={"scan_status": image.scan_status})
    changed = compare_and_swap(
        ImageAsset,
        pk=image.pk,
        expected_version=expected_version,
        changes={
            "approval_status": decision,
            "approved_by": actor,
            "approved_at": timezone.now(),
            "change_reason": _reason(reason),
        },
    )
    _audit(
        context,
        action="governance.image.decide",
        target_type="image_asset",
        target_ref=image.public_id,
        before={"approval_status": image.approval_status},
        after={"approval_status": changed.approval_status},
    )
    _event(
        context,
        event_type=events.IMAGE_CHANGED,
        aggregate_type="image_asset",
        aggregate_ref=image.public_id,
        payload={"image_id": image.public_id, "approval_status": changed.approval_status},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def create_resource_profile(
    *,
    actor: User,
    code: str,
    name: str,
    runtime_type: str,
    cpu_millicores: int,
    memory_mb: int,
    cpu_request_millicores: int | None = None,
    cpu_limit_millicores: int | None = None,
    memory_request_mb: int | None = None,
    memory_limit_mb: int | None = None,
    disk_gb: int,
    network_mode: str,
    cost_minor_per_hour: int,
    currency_code: str,
    reason: str,
    context: ActorContext,
) -> ResourceProfile:
    profile_data = validate_resource_profile(
        {
            "cpu_millicores": cpu_millicores,
            "memory_mb": memory_mb,
            "cpu_request_millicores": cpu_request_millicores,
            "cpu_limit_millicores": cpu_limit_millicores,
            "memory_request_mb": memory_request_mb,
            "memory_limit_mb": memory_limit_mb,
            "disk_gb": disk_gb,
        }
    )
    if (
        runtime_type not in RuntimeAdapter.RuntimeType.values
        or network_mode not in ResourceProfile.NetworkMode.values
    ):
        raise GovernanceValidationError(
            detail={"runtime_type": runtime_type, "network_mode": network_mode}
        )
    try:
        profile = ResourceProfile.objects.create(
            code=code.strip().upper(),
            name=name.strip(),
            runtime_type=runtime_type,
            cpu_millicores=profile_data["cpu_millicores"],
            memory_mb=profile_data["memory_mb"],
            cpu_request_millicores=profile_data["cpu_request_millicores"],
            cpu_limit_millicores=profile_data["cpu_limit_millicores"],
            memory_request_mb=profile_data["memory_request_mb"],
            memory_limit_mb=profile_data["memory_limit_mb"],
            disk_gb=profile_data["disk_gb"],
            network_mode=network_mode,
            cost_minor_per_hour=cost_minor_per_hour,
            currency_code=currency_code.strip().upper(),
            change_reason=_reason(reason),
        )
    except IntegrityError as exc:
        raise GovernanceStateConflict(detail={"code": code}) from exc
    _audit(
        context,
        action="governance.resource_profile.create",
        target_type="resource_profile",
        target_ref=profile.public_id,
        after={"code": profile.code, "status": profile.status},
    )
    return profile


@transaction.atomic
def update_resource_profile(
    *,
    profile_id: str,
    actor: User,
    expected_version: int,
    changes: dict[str, Any],
    reason: str,
    context: ActorContext,
) -> ResourceProfile:
    try:
        profile = ResourceProfile.objects.select_for_update().get(public_id=profile_id)
    except ResourceProfile.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if profile.status != ResourceProfile.Status.DRAFT:
        raise GovernanceStateConflict(detail={"status": profile.status})
    allowed = {
        "name",
        "runtime_type",
        "cpu_millicores",
        "memory_mb",
        "cpu_request_millicores",
        "cpu_limit_millicores",
        "memory_request_mb",
        "memory_limit_mb",
        "disk_gb",
        "network_mode",
        "cost_minor_per_hour",
        "currency_code",
    }
    clean = {key: value for key, value in changes.items() if key in allowed}
    merged = {field: getattr(profile, field) for field in allowed}
    merged.update(clean)
    clean.update(
        {
            field: validate_resource_profile(merged)[field]
            for field in (
                "cpu_millicores",
                "memory_mb",
                "cpu_request_millicores",
                "cpu_limit_millicores",
                "memory_request_mb",
                "memory_limit_mb",
                "disk_gb",
            )
        }
    )
    clean["change_reason"] = _reason(reason)
    changed = compare_and_swap(
        ResourceProfile,
        pk=profile.pk,
        expected_version=expected_version,
        changes=clean,
    )
    _audit(
        context,
        action="governance.resource_profile.update",
        target_type="resource_profile",
        target_ref=profile.public_id,
        before={key: getattr(profile, key) for key in clean},
        after={key: getattr(changed, key) for key in clean},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def transition_resource_profile(
    *,
    profile_id: str,
    actor: User,
    expected_version: int,
    target_status: str,
    reason: str,
    context: ActorContext,
) -> ResourceProfile:
    try:
        profile = ResourceProfile.objects.select_for_update().get(public_id=profile_id)
    except ResourceProfile.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    allowed = {
        ResourceProfile.Status.DRAFT: {ResourceProfile.Status.ACTIVE},
        ResourceProfile.Status.ACTIVE: {ResourceProfile.Status.RETIRED},
    }
    if target_status not in allowed.get(profile.status, set()):
        raise GovernanceStateConflict(detail={"status": profile.status, "target": target_status})
    now = timezone.now()
    changes: dict[str, Any] = {"status": target_status, "change_reason": _reason(reason)}
    if target_status == ResourceProfile.Status.ACTIVE:
        changes["activated_at"] = now
    else:
        changes["retired_at"] = now
    changed = compare_and_swap(
        ResourceProfile,
        pk=profile.pk,
        expected_version=expected_version,
        changes=changes,
    )
    _audit(
        context,
        action="governance.resource_profile.transition",
        target_type="resource_profile",
        target_ref=profile.public_id,
        before={"status": profile.status},
        after={"status": changed.status},
    )
    _event(
        context,
        event_type=events.RESOURCE_PROFILE_CHANGED,
        aggregate_type="resource_profile",
        aggregate_ref=profile.public_id,
        payload={"profile_id": profile.public_id, "status": changed.status},
    )
    return changed  # type: ignore[return-value]


def _quota_values(values: dict[str, Any]) -> dict[str, int | None]:
    clean: dict[str, int | None] = {}
    for field in QUOTA_VALUE_FIELDS:
        value = values.get(field)
        if value is not None and int(value) <= 0:
            raise GovernanceValidationError(detail={field: "positive_or_null_required"})
        clean[field] = None if value is None else int(value)
    if all(value is None for value in clean.values()):
        raise GovernanceValidationError(detail={"quota": "at_least_one_limit_required"})
    return clean


@transaction.atomic
def create_quota(
    *,
    actor: User,
    scope_type: str,
    course_id: str | None,
    user_id: str | None,
    values: dict[str, Any],
    reason: str,
    context: ActorContext,
) -> Quota:
    scope_key, course, user = _scope(
        scope_type=scope_type,
        course_id=course_id,
        user_id=user_id,
    )
    try:
        quota = Quota.objects.create(
            scope_type=scope_type,
            scope_key=scope_key,
            course=course,
            user=user,
            updated_by=actor,
            change_reason=_reason(reason),
            **_quota_values(values),
        )
    except IntegrityError as exc:
        raise GovernanceStateConflict(detail={"scope_key": scope_key}) from exc
    _audit(
        context,
        action="governance.quota.create",
        target_type="quota",
        target_ref=quota.public_id,
        course_ref=course.public_id if course else "",
        after={"scope_key": scope_key, **_quota_values(values)},
    )
    _event(
        context,
        event_type=events.QUOTA_CHANGED,
        aggregate_type="quota",
        aggregate_ref=quota.public_id,
        payload={"quota_id": quota.public_id, "scope_key": scope_key},
    )
    return quota


@transaction.atomic
def update_quota(
    *,
    quota_id: str,
    actor: User,
    expected_version: int,
    values: dict[str, Any],
    reason: str,
    context: ActorContext,
) -> Quota:
    try:
        quota = Quota.objects.select_for_update().get(public_id=quota_id)
    except Quota.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    clean: dict[str, Any] = _quota_values(values)
    clean.update({"updated_by": actor, "change_reason": _reason(reason)})
    changed = compare_and_swap(
        Quota,
        pk=quota.pk,
        expected_version=expected_version,
        changes=clean,
    )
    _audit(
        context,
        action="governance.quota.update",
        target_type="quota",
        target_ref=quota.public_id,
        course_ref=quota.course.public_id if quota.course else "",
        before={key: getattr(quota, key) for key in QUOTA_VALUE_FIELDS},
        after={key: getattr(changed, key) for key in QUOTA_VALUE_FIELDS},
    )
    _event(
        context,
        event_type=events.QUOTA_CHANGED,
        aggregate_type="quota",
        aggregate_ref=quota.public_id,
        payload={"quota_id": quota.public_id, "scope_key": quota.scope_key},
    )
    return changed  # type: ignore[return-value]


def _reservation_values(values: dict[str, Any]) -> dict[str, int]:
    clean = {field: int(values.get(field, 0)) for field in RESERVATION_VALUE_FIELDS}
    if any(value < 0 for value in clean.values()) or clean["instance_count"] <= 0:
        raise GovernanceValidationError(detail={"reservation": "invalid_resource_values"})
    return clean


def _locked_quota_levels(*, course: Course | None, user: User | None) -> tuple[Quota, list[Quota]]:
    platform = Quota.objects.select_for_update().filter(scope_type=Quota.ScopeType.PLATFORM).first()
    if platform is None:
        raise QuotaNotConfigured()
    rows = [platform]
    if course is not None:
        current = Quota.objects.select_for_update().filter(course=course).first()
        if current is not None:
            rows.append(current)
    if user is not None:
        current = Quota.objects.select_for_update().filter(user=user).first()
        if current is not None:
            rows.append(current)
    return platform, rows


def _check_quota_level(
    *, quota: Quota, requested: dict[str, int], course: Course | None, user: User | None
) -> None:
    usage_course = course if quota.scope_type == Quota.ScopeType.COURSE else None
    usage_user = user if quota.scope_type == Quota.ScopeType.USER else None
    used = reservation_usage(course=usage_course, user=usage_user)
    for resource_field, limit_field in USAGE_TO_LIMIT.items():
        limit = getattr(quota, limit_field)
        request_value = requested[resource_field]
        if request_value and limit is None and quota.scope_type == Quota.ScopeType.PLATFORM:
            raise QuotaNotConfigured(detail={"dimension": limit_field})
        if limit is not None and used[resource_field] + request_value > int(limit):
            raise QuotaExceeded(
                detail={
                    "scope_key": quota.scope_key,
                    "dimension": limit_field,
                    "limit": int(limit),
                    "used": used[resource_field],
                    "requested": request_value,
                }
            )


@transaction.atomic
def reserve_quota(
    *,
    reservation_key: str,
    reservation_type: str,
    subject_type: str,
    subject_ref: str,
    course_id: str | None,
    user_id: str | None,
    resource_profile_id: str | None,
    values: dict[str, Any],
    expires_at: datetime | None,
    context: ActorContext,
) -> QuotaReservation:
    existing = (
        QuotaReservation.objects.select_for_update().filter(reservation_key=reservation_key).first()
    )
    requested = _reservation_values(values)
    if existing is not None:
        expected = {
            "reservation_type": reservation_type,
            "subject_type": subject_type,
            "subject_ref": subject_ref,
            **requested,
        }
        actual = {key: getattr(existing, key) for key in expected}
        if actual != expected:
            raise GovernanceStateConflict(detail={"reservation_key": reservation_key})
        return existing
    if reservation_type not in QuotaReservation.ReservationType.values:
        raise GovernanceValidationError(detail={"reservation_type": reservation_type})
    course = None
    user = None
    if course_id:
        try:
            course = Course.objects.select_for_update().get(public_id=course_id)
        except Course.DoesNotExist as exc:
            raise ResourceNotFound() from exc
    if user_id:
        try:
            user = User.objects.get(public_id=user_id)
        except User.DoesNotExist as exc:
            raise ResourceNotFound() from exc
    profile = None
    if resource_profile_id:
        try:
            profile = ResourceProfile.objects.get(
                public_id=resource_profile_id,
                status=ResourceProfile.Status.ACTIVE,
            )
        except ResourceProfile.DoesNotExist as exc:
            raise ResourceNotFound() from exc
    _, quota_rows = _locked_quota_levels(course=course, user=user)
    for quota in quota_rows:
        _check_quota_level(quota=quota, requested=requested, course=course, user=user)
    reserved_at = timezone.now()
    if expires_at is not None and expires_at <= reserved_at:
        raise GovernanceValidationError(detail={"expires_at": "must_be_future"})
    estimated_cost = 0
    currency = "CNY"
    if profile is not None:
        currency = profile.currency_code
        duration_hours = 1
        if expires_at is not None:
            seconds = max(1, int((expires_at - reserved_at).total_seconds()))
            duration_hours = (seconds + 3599) // 3600
        estimated_cost = profile.cost_minor_per_hour * duration_hours * requested["instance_count"]
    try:
        reservation = QuotaReservation.objects.create(
            reservation_key=reservation_key,
            reservation_type=reservation_type,
            subject_type=subject_type,
            subject_ref=subject_ref,
            course=course,
            user=user,
            resource_profile=profile,
            reserved_at=reserved_at,
            expires_at=expires_at,
            estimated_cost_minor=estimated_cost,
            currency_code=currency,
            trace_id=context.trace_id,
            **requested,
        )
    except IntegrityError as exc:
        raise GovernanceStateConflict(
            detail={"subject_type": subject_type, "subject_ref": subject_ref}
        ) from exc
    QUOTA_OPERATIONS.labels(operation="reserve", result="success").inc()
    _audit(
        context,
        action="governance.quota.reserve",
        target_type="quota_reservation",
        target_ref=reservation.public_id,
        course_ref=course.public_id if course else "",
        after={"reservation_type": reservation_type, "resources": requested},
    )
    _event(
        context,
        event_type=events.QUOTA_RESERVED,
        aggregate_type="quota_reservation",
        aggregate_ref=reservation.public_id,
        payload={
            "reservation_id": reservation.public_id,
            "reservation_type": reservation_type,
            "course_id": course.public_id if course else None,
            "user_id": user.public_id if user else None,
        },
    )
    return reservation


@transaction.atomic
def release_reservation(
    *, reservation_id: str, reason: str, context: ActorContext
) -> QuotaReservation:
    try:
        reservation = QuotaReservation.objects.select_for_update().get(public_id=reservation_id)
    except QuotaReservation.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if reservation.status != QuotaReservation.Status.ACTIVE:
        return reservation
    changed = compare_and_swap(
        QuotaReservation,
        pk=reservation.pk,
        expected_version=reservation.row_version,
        changes={
            "status": QuotaReservation.Status.RELEASED,
            "released_at": timezone.now(),
            "release_reason": _reason(reason),
        },
    )
    QUOTA_OPERATIONS.labels(operation="release", result="success").inc()
    _audit(
        context,
        action="governance.quota.release",
        target_type="quota_reservation",
        target_ref=reservation.public_id,
        course_ref=reservation.course.public_id if reservation.course else "",
        before={"status": reservation.status},
        after={"status": changed.status},
    )
    _event(
        context,
        event_type=events.QUOTA_RELEASED,
        aggregate_type="quota_reservation",
        aggregate_ref=reservation.public_id,
        payload={"reservation_id": reservation.public_id, "status": changed.status},
    )
    return changed  # type: ignore[return-value]


def _validate_security_rules(rules: dict[str, Any]) -> dict[str, Any]:
    required = {"default_egress", "allow_privileged", "require_workspace_gateway"}
    if not required.issubset(rules):
        raise GovernanceValidationError(detail={"rules": "security_shape_invalid"})
    if rules["default_egress"] not in {"DENY_ALL", "ALLOWLIST"}:
        raise GovernanceValidationError(detail={"default_egress": rules["default_egress"]})
    if rules["allow_privileged"] is not False or rules["require_workspace_gateway"] is not True:
        raise GovernanceValidationError(detail={"rules": "isolation_cannot_be_disabled"})
    return {
        "default_egress": rules["default_egress"],
        "allow_privileged": False,
        "require_workspace_gateway": True,
    }


def _validate_scaling_rules(rules: dict[str, Any]) -> dict[str, Any]:
    required = {
        "prewarm_enabled",
        "prewarm_lead_minutes",
        "min_replicas",
        "max_replicas",
        "cooldown_seconds",
        "idle_reclaim_seconds",
        "budget_minor",
        "currency_code",
        "max_course_concurrency",
    }
    if not required.issubset(rules):
        raise GovernanceValidationError(detail={"rules": "scaling_shape_invalid"})
    numeric = {key: int(rules[key]) for key in required - {"prewarm_enabled", "currency_code"}}
    if any(value < 0 for value in numeric.values()):
        raise GovernanceValidationError(detail={"rules": "non_negative_values_required"})
    if numeric["min_replicas"] > numeric["max_replicas"]:
        raise GovernanceValidationError(detail={"replicas": "min_exceeds_max"})
    if numeric["max_course_concurrency"] < numeric["max_replicas"]:
        raise GovernanceValidationError(detail={"max_course_concurrency": "below_max_replicas"})
    currency = str(rules["currency_code"]).upper()
    if len(currency) != 3:
        raise GovernanceValidationError(detail={"currency_code": "iso_4217_required"})
    return {"prewarm_enabled": bool(rules["prewarm_enabled"]), **numeric, "currency_code": currency}


def validate_policy_rules(*, policy_kind: str, rules: dict[str, Any]) -> dict[str, Any]:
    if policy_kind == SecurityPolicy.PolicyKind.RUNTIME_SECURITY:
        return _validate_security_rules(rules)
    if policy_kind == SecurityPolicy.PolicyKind.RESOURCE_SCALING:
        return _validate_scaling_rules(rules)
    raise GovernanceValidationError(detail={"policy_kind": policy_kind})


@transaction.atomic
def put_policy(
    *,
    actor: User,
    policy_kind: str,
    scope_type: str,
    course_id: str | None,
    risk_level: str,
    rules: dict[str, Any],
    reason: str,
    expected_version: int | None,
    context: ActorContext,
) -> SecurityPolicy:
    if risk_level not in SecurityPolicy.RiskLevel.values:
        raise GovernanceValidationError(detail={"risk_level": risk_level})
    scope_key, course = _policy_scope(scope_type=scope_type, course_id=course_id)
    clean_rules = validate_policy_rules(policy_kind=policy_kind, rules=rules)
    current = (
        SecurityPolicy.objects.select_for_update()
        .filter(
            policy_kind=policy_kind,
            scope_key=scope_key,
        )
        .first()
    )
    if current is None:
        if expected_version is not None:
            raise RowVersionConflict(detail={"actual_row_version": None})
        policy = SecurityPolicy.objects.create(
            policy_kind=policy_kind,
            scope_type=scope_type,
            scope_key=scope_key,
            course=course,
            risk_level=risk_level,
            rules=clean_rules,
            updated_by=actor,
            change_reason=_reason(reason),
        )
        before = None
    else:
        if expected_version is None:
            raise GovernanceValidationError(detail={"if_match": "required_for_existing_policy"})
        policy = compare_and_swap(
            SecurityPolicy,
            pk=current.pk,
            expected_version=expected_version,
            changes={
                "risk_level": risk_level,
                "rules": clean_rules,
                "updated_by": actor,
                "change_reason": _reason(reason),
            },
        )
        before = {"risk_level": current.risk_level, "rules": current.rules}
    _audit(
        context,
        action="governance.policy.put",
        target_type="security_policy",
        target_ref=policy.public_id,
        course_ref=course.public_id if course else "",
        before=before,
        after={"policy_kind": policy_kind, "risk_level": risk_level, "rules": clean_rules},
    )
    _event(
        context,
        event_type=events.SECURITY_POLICY_CHANGED,
        aggregate_type="security_policy",
        aggregate_ref=policy.public_id,
        payload={"policy_id": policy.public_id, "policy_kind": policy_kind},
    )
    return policy  # type: ignore[return-value]


def _validate_network_target(target_type: str, target_value: str) -> str:
    normalized = target_value.strip().lower()
    try:
        if target_type == NetworkAllowlist.TargetType.CIDR:
            return str(ipaddress.ip_network(normalized, strict=True))
    except ValueError as exc:
        raise GovernanceValidationError(detail={"target_value": "invalid_cidr"}) from exc
    if target_type == NetworkAllowlist.TargetType.HOST and HOST_RE.fullmatch(normalized):
        return normalized
    raise GovernanceValidationError(detail={"target_value": "invalid_host"})


@transaction.atomic
def create_allowlist_entry(
    *,
    actor: User,
    scope_type: str,
    course_id: str | None,
    target_type: str,
    target_value: str,
    protocol: str,
    port_start: int,
    port_end: int,
    risk_level: str,
    reason: str,
    context: ActorContext,
) -> NetworkAllowlist:
    scope_key, course = _policy_scope(scope_type=scope_type, course_id=course_id)
    if (
        protocol not in NetworkAllowlist.Protocol.values
        or risk_level not in SecurityPolicy.RiskLevel.values
    ):
        raise GovernanceValidationError(detail={"protocol": protocol, "risk_level": risk_level})
    if not 1 <= port_start <= port_end <= 65535:
        raise GovernanceValidationError(detail={"ports": "invalid_range"})
    target = _validate_network_target(target_type, target_value)
    try:
        entry = NetworkAllowlist.objects.create(
            scope_type=scope_type,
            scope_key=scope_key,
            course=course,
            target_type=target_type,
            target_value=target,
            protocol=protocol,
            port_start=port_start,
            port_end=port_end,
            risk_level=risk_level,
            approved_by=actor,
            approved_at=timezone.now(),
            change_reason=_reason(reason),
        )
    except IntegrityError as exc:
        raise GovernanceStateConflict(detail={"target_value": target}) from exc
    _audit(
        context,
        action="governance.network_allowlist.create",
        target_type="network_allowlist",
        target_ref=entry.public_id,
        course_ref=course.public_id if course else "",
        after={"target_type": target_type, "target_value": target, "status": entry.status},
    )
    _event(
        context,
        event_type=events.NETWORK_ALLOWLIST_CHANGED,
        aggregate_type="network_allowlist",
        aggregate_ref=entry.public_id,
        payload={"entry_id": entry.public_id, "status": entry.status},
    )
    return entry


@transaction.atomic
def revoke_allowlist_entry(
    *,
    entry_id: str,
    actor: User,
    expected_version: int,
    reason: str,
    context: ActorContext,
) -> NetworkAllowlist:
    try:
        entry = NetworkAllowlist.objects.select_for_update().get(public_id=entry_id)
    except NetworkAllowlist.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if entry.status == NetworkAllowlist.Status.REVOKED:
        _ensure_expected(entry.row_version, expected_version)
        return entry
    changed = compare_and_swap(
        NetworkAllowlist,
        pk=entry.pk,
        expected_version=expected_version,
        changes={"status": NetworkAllowlist.Status.REVOKED, "change_reason": _reason(reason)},
    )
    _audit(
        context,
        action="governance.network_allowlist.revoke",
        target_type="network_allowlist",
        target_ref=entry.public_id,
        course_ref=entry.course.public_id if entry.course else "",
        before={"status": entry.status},
        after={"status": changed.status},
    )
    return changed  # type: ignore[return-value]


@transaction.atomic
def request_prewarm(
    *,
    course_id: str,
    resource_profile_id: str,
    replicas: int,
    intent_key: str,
    expires_at: datetime,
    context: ActorContext,
) -> QuotaReservation:
    try:
        course = Course.objects.get(public_id=course_id)
        policy = SecurityPolicy.objects.get(
            policy_kind=SecurityPolicy.PolicyKind.RESOURCE_SCALING,
            course=course,
        )
    except (Course.DoesNotExist, SecurityPolicy.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    rules = _validate_scaling_rules(policy.rules)
    if not rules["prewarm_enabled"] or replicas > int(rules["max_replicas"]):
        raise GovernanceStateConflict(detail={"prewarm": "disabled_or_above_max"})
    active_cost = reservation_usage(course=course)["estimated_cost_minor"]
    profile = ResourceProfile.objects.filter(
        public_id=resource_profile_id,
        status=ResourceProfile.Status.ACTIVE,
    ).first()
    if profile is None:
        raise ResourceNotFound()
    hours = max(1, int((expires_at - timezone.now()).total_seconds() + 3599) // 3600)
    requested_cost = profile.cost_minor_per_hour * replicas * hours
    if active_cost + requested_cost > int(rules["budget_minor"]):
        raise BudgetExceeded(
            detail={"budget_minor": rules["budget_minor"], "requested_minor": requested_cost}
        )
    reservation = reserve_quota(
        reservation_key=intent_key,
        reservation_type=QuotaReservation.ReservationType.PREWARM,
        subject_type="COURSE_PREWARM",
        subject_ref=f"{course.public_id}:{resource_profile_id}",
        course_id=course.public_id,
        user_id=None,
        resource_profile_id=resource_profile_id,
        values={
            "instance_count": replicas,
            "start_count": replicas,
            "cpu_millicores": profile.cpu_millicores * replicas,
            "memory_mb": profile.memory_mb * replicas,
            "disk_gb": profile.disk_gb * replicas,
        },
        expires_at=expires_at,
        context=context,
    )
    _event(
        context,
        event_type=events.PREWARM_REQUESTED,
        aggregate_type="course",
        aggregate_ref=course.public_id,
        payload={"course_id": course.public_id, "reservation_id": reservation.public_id},
    )
    return reservation


@transaction.atomic
def request_scaling_intent(
    *,
    course_id: str,
    resource_profile_id: str,
    replicas: int,
    intent_key: str,
    context: ActorContext,
) -> QuotaReservation:
    try:
        course = Course.objects.get(public_id=course_id)
        policy = SecurityPolicy.objects.get(
            policy_kind=SecurityPolicy.PolicyKind.RESOURCE_SCALING,
            course=course,
        )
    except (Course.DoesNotExist, SecurityPolicy.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    rules = _validate_scaling_rules(policy.rules)
    if not int(rules["min_replicas"]) <= replicas <= int(rules["max_replicas"]):
        raise GovernanceValidationError(detail={"replicas": replicas})
    latest = (
        QuotaReservation.objects.filter(
            course=course,
            reservation_type=QuotaReservation.ReservationType.SCALING,
        )
        .order_by("-reserved_at")
        .first()
    )
    if (
        latest is not None
        and latest.reserved_at + timedelta(seconds=int(rules["cooldown_seconds"])) > timezone.now()
    ):
        if latest.reservation_key == intent_key:
            return latest
        raise ScalingCooldownActive(detail={"last_intent_at": latest.reserved_at})
    profile = ResourceProfile.objects.filter(
        public_id=resource_profile_id,
        status=ResourceProfile.Status.ACTIVE,
    ).first()
    if profile is None:
        raise ResourceNotFound()
    reservation = reserve_quota(
        reservation_key=intent_key,
        reservation_type=QuotaReservation.ReservationType.SCALING,
        subject_type="COURSE_SCALING",
        subject_ref=f"{course.public_id}:{intent_key}",
        course_id=course.public_id,
        user_id=None,
        resource_profile_id=resource_profile_id,
        values={
            "instance_count": replicas,
            "start_count": replicas,
            "cpu_millicores": profile.cpu_millicores * replicas,
            "memory_mb": profile.memory_mb * replicas,
            "disk_gb": profile.disk_gb * replicas,
        },
        expires_at=timezone.now() + timedelta(seconds=int(rules["idle_reclaim_seconds"])),
        context=context,
    )
    _event(
        context,
        event_type=events.SCALING_REQUESTED,
        aggregate_type="course",
        aggregate_ref=course.public_id,
        payload={"course_id": course.public_id, "reservation_id": reservation.public_id},
    )
    return reservation


def _redis_client() -> Redis:
    return Redis.from_url(settings.REDIS_URL, decode_responses=True)


def rebuild_quota_cache(*, client: Redis | None = None) -> int:
    redis_client = client or _redis_client()
    count = 0
    for quota in Quota.objects.all():
        course = quota.course if quota.scope_type == Quota.ScopeType.COURSE else None
        user = quota.user if quota.scope_type == Quota.ScopeType.USER else None
        redis_client.set(
            f"governance:quota:{quota.scope_key}",
            json.dumps(reservation_usage(course=course, user=user), sort_keys=True),
            ex=settings.GOVERNANCE_CACHE_TTL_SECONDS,
        )
        count += 1
    return count


@transaction.atomic
def expire_reservations(*, trace_id: str) -> int:
    now = timezone.now()
    reservations = list(
        QuotaReservation.objects.select_for_update().filter(
            status=QuotaReservation.Status.ACTIVE,
            expires_at__lte=now,
        )
    )
    for reservation in reservations:
        compare_and_swap(
            QuotaReservation,
            pk=reservation.pk,
            expected_version=reservation.row_version,
            changes={
                "status": QuotaReservation.Status.EXPIRED,
                "released_at": now,
                "release_reason": "reservation expired",
            },
        )
        append_outbox_event(
            event_type=events.QUOTA_RELEASED,
            aggregate_type="quota_reservation",
            aggregate_ref=reservation.public_id,
            payload={"reservation_id": reservation.public_id, "status": "EXPIRED"},
            trace_id=trace_id,
        )
    if reservations:
        enqueue_relay_after_commit(trace_id=trace_id)
    return len(reservations)
