import json
import urllib.error
import urllib.request
from contextlib import suppress
from datetime import timedelta
from typing import Any

from celery import shared_task
from django.conf import settings
from django.utils import timezone
from redis import Redis

from apps.core.audit import append_failure
from apps.core.models import FailureRecord
from apps.provisioning.adapters import RuntimeAdapterFailure
from apps.provisioning.ports import RuntimeSpec
from apps.provisioning.services import _runtime_adapter_for_row

from .errors import GovernanceStateConflict, GovernanceValidationError
from .metrics import RUNTIME_ADAPTER_CAPACITY, RUNTIME_ADAPTER_HEALTH
from .models import QuotaReservation, RuntimeAdapter
from .services import (
    ActorContext,
    expire_reservations,
    rebuild_quota_cache,
    record_runtime_health,
    reresolve_image_digest,
    resolve_image_digest,
)


def _nonnegative_int(value: object) -> int:
    if not isinstance(value, (str, bytes, bytearray, int, float)):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _redis_client() -> Redis:
    return Redis.from_url(settings.REDIS_URL, decode_responses=True)


@shared_task(name="apps.governance.probe_object_storage")
def probe_object_storage(*, trace_id: str = "") -> dict[str, str]:
    status = "UNAVAILABLE"
    try:
        request = urllib.request.Request(settings.MINIO_HEALTH_URL, method="GET")
        with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310
            if response.status == 200:
                status = "HEALTHY"
    except (OSError, urllib.error.URLError):
        status = "UNAVAILABLE"
    payload = {
        "status": status,
        "checked_at": timezone.now().isoformat(),
        "trace_id": trace_id,
    }
    with suppress(Exception):
        _redis_client().set(
            "governance:health:minio",
            json.dumps(payload, sort_keys=True),
            ex=settings.GOVERNANCE_CACHE_TTL_SECONDS,
        )
    return payload


@shared_task(name="apps.governance.probe_runtime_adapters")
def probe_runtime_adapters(*, trace_id: str = "") -> dict[str, str]:
    results: dict[str, str] = {}
    adapters = RuntimeAdapter.objects.filter(status=RuntimeAdapter.Status.ENABLED).order_by("code")
    for adapter_config in adapters:
        try:
            health = dict(
                _runtime_adapter_for_row(
                    driver=adapter_config.driver,
                    config_ref=adapter_config.config_ref,
                    code=adapter_config.code,
                ).health()
            )
        except RuntimeAdapterFailure:
            health = {"status": RuntimeAdapter.HealthStatus.UNAVAILABLE}
        status = str(health.get("status", RuntimeAdapter.HealthStatus.UNAVAILABLE))
        if status not in RuntimeAdapter.HealthStatus.values:
            status = RuntimeAdapter.HealthStatus.UNAVAILABLE
        values = {
            "node_count": _nonnegative_int(health.get("node_count", 0)),
            "capacity_cpu_millicores": _nonnegative_int(
                health.get("capacity_cpu_millicores", 0)
            ),
            "available_cpu_millicores": _nonnegative_int(
                health.get("available_cpu_millicores", 0)
            ),
            "capacity_memory_mb": _nonnegative_int(health.get("capacity_memory_mb", 0)),
            "available_memory_mb": _nonnegative_int(
                health.get("available_memory_mb", 0)
            ),
        }
        record_runtime_health(
            adapter_id=adapter_config.public_id,
            health_status=status,
            detail={"driver": adapter_config.driver, "checked_at": timezone.now().isoformat()},
            trace_id=trace_id,
            **values,
        )
        for possible_status in RuntimeAdapter.HealthStatus.values:
            RUNTIME_ADAPTER_HEALTH.labels(
                adapter=adapter_config.code, status=possible_status
            ).set(1 if possible_status == status else 0)
        for resource, capacity_key, available_key in (
            ("cpu_millicores", "capacity_cpu_millicores", "available_cpu_millicores"),
            ("memory_mb", "capacity_memory_mb", "available_memory_mb"),
        ):
            RUNTIME_ADAPTER_CAPACITY.labels(
                adapter=adapter_config.code, resource=resource, kind="total"
            ).set(values[capacity_key])
            RUNTIME_ADAPTER_CAPACITY.labels(
                adapter=adapter_config.code, resource=resource, kind="available"
            ).set(values[available_key])
        results[adapter_config.code] = status
    return results


def _capacity_spec(reservation: QuotaReservation) -> tuple[RuntimeAdapter, RuntimeSpec] | None:
    from apps.labtemplates.models import TemplateVersion

    if reservation.course_id is None or reservation.resource_profile_id is None:
        return None
    version = (
        TemplateVersion.objects.select_related(
            "runtime_adapter", "image", "resource_profile", "template"
        )
        .filter(
            template__course_id=reservation.course_id,
            resource_profile_id=reservation.resource_profile_id,
            status=TemplateVersion.Status.PUBLISHED,
            runtime_adapter__status=RuntimeAdapter.Status.ENABLED,
            task_publications__status="PUBLISHED",
        )
        .order_by("-published_at", "-id")
        .first()
    )
    if version is None:
        return None
    ttl = 60
    if reservation.expires_at is not None:
        ttl = max(60, int((reservation.expires_at - timezone.now()).total_seconds()))
    policy = dict(version.network_policy or {})
    policy.setdefault("mode", version.resource_profile.network_mode)
    return version.runtime_adapter, RuntimeSpec(
        task_id=f"capacity-{reservation.public_id}",
        course_id=reservation.course.public_id,
        student_id="",
        runtime_type=version.runtime_type,
        image_registry=version.image.registry,
        image_repository=version.image.repository,
        image_digest=version.image.digest,
        resource_profile_id=version.resource_profile.public_id,
        cpu_millicores=version.resource_profile.cpu_millicores,
        memory_mb=version.resource_profile.memory_mb,
        disk_gb=version.resource_profile.disk_gb,
        network_policy=policy,
        workspace_capabilities=version.workspace_capabilities,
        ttl_seconds=ttl,
        workspace_port=int(settings.RUNTIME_WORKSPACE_PORT),
        healthcheck_path=str(settings.RUNTIME_HEALTHCHECK_PATH),
        trace_id=reservation.trace_id,
    )


def reconcile_runtime_capacity(*, trace_id: str = "") -> dict[str, int]:
    ensured = 0
    released = 0
    failed = 0
    active = QuotaReservation.objects.select_related("course", "resource_profile").filter(
        status=QuotaReservation.Status.ACTIVE,
        reservation_type__in=(
            QuotaReservation.ReservationType.PREWARM,
            QuotaReservation.ReservationType.SCALING,
        ),
    )
    for reservation in active.iterator():
        try:
            resolved = _capacity_spec(reservation)
            if resolved is None:
                raise RuntimeAdapterFailure(
                    "RUNTIME_CAPACITY_TEMPLATE_UNAVAILABLE", retryable=False
                )
            adapter_config, spec = resolved
            _runtime_adapter_for_row(
                driver=adapter_config.driver,
                config_ref=adapter_config.config_ref,
                code=adapter_config.code,
            ).coordinate_capacity(
                spec,
                idempotency_key=f"capacity:{reservation.reservation_key}",
                replicas=reservation.instance_count,
            )
            ensured += 1
        except Exception as exc:  # noqa: BLE001 - capacity failures cannot stop other intents
            failed += 1
            code = getattr(exc, "code", "RUNTIME_CAPACITY_FAILED")
            if not FailureRecord.objects.filter(
                subject_type="QUOTA_RESERVATION",
                subject_ref=reservation.public_id,
                error_code=code,
            ).exists():
                append_failure(
                    failure_type="RUNTIME_CAPACITY",
                    subject_type="QUOTA_RESERVATION",
                    subject_ref=reservation.public_id,
                    error_code=code,
                    message=code,
                    detail={"reservation_type": reservation.reservation_type},
                    retryable=bool(getattr(exc, "retryable", True)),
                    trace_id=trace_id,
                )
    recent = QuotaReservation.objects.filter(
        status__in=(QuotaReservation.Status.EXPIRED, QuotaReservation.Status.RELEASED),
        reservation_type__in=(
            QuotaReservation.ReservationType.PREWARM,
            QuotaReservation.ReservationType.SCALING,
        ),
        released_at__gte=timezone.now() - timedelta(hours=1),
    )
    adapters = list(RuntimeAdapter.objects.filter(status=RuntimeAdapter.Status.ENABLED))
    for reservation in recent.iterator():
        for adapter_config in adapters:
            try:
                _runtime_adapter_for_row(
                    driver=adapter_config.driver,
                    config_ref=adapter_config.config_ref,
                    code=adapter_config.code,
                ).release_capacity(
                    idempotency_key=f"capacity:{reservation.reservation_key}"
                )
            except RuntimeAdapterFailure:
                failed += 1
        released += 1
    return {"ensured": ensured, "released": released, "failed": failed}


@shared_task(name="apps.governance.run_maintenance")
def run_maintenance(*, trace_id: str) -> dict[str, int | str]:
    expired = expire_reservations(trace_id=trace_id)
    cached = 0
    try:
        cached = rebuild_quota_cache()
    except Exception:
        cached = 0
    storage = probe_object_storage.run(trace_id=trace_id)
    runtimes = probe_runtime_adapters.run(trace_id=trace_id)
    capacity = reconcile_runtime_capacity(trace_id=trace_id)
    return {
        "expired": expired,
        "cached": cached,
        "storage": storage["status"],
        "runtime_adapters": len(runtimes),
        "capacity_ensured": capacity["ensured"],
        "capacity_released": capacity["released"],
        "capacity_failed": capacity["failed"],
    }


def _describe_resolve_failure(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict) and detail:
        parts = [f"{key}={value}" for key, value in detail.items()]
        return "; ".join(parts) or str(exc)
    return str(exc)


@shared_task(
    name="apps.governance.resolve_image_digest",
    bind=True,
    max_retries=2,
    queue="q_provision",
    acks_late=True,
)
def resolve_image_digest_task(self: Any, image_id: str, trace_id: str = "") -> str:
    try:
        resolved = resolve_image_digest(
            image_id=image_id,
            reason="",
            allow_resolved=True,
            context=ActorContext("PLATFORM_WORKER", "PLATFORM", trace_id),
        )
    except (GovernanceValidationError, GovernanceStateConflict) as exc:
        # 确定性失败（无可用运行时 / 内容重复 / 源站不可达等）重试不会成功，直接记录并抛出
        append_failure(
            failure_type="IMAGE_RESOLVE",
            subject_type="IMAGE_ASSET",
            subject_ref=image_id,
            error_code="IMAGE_RESOLVE_FAILED",
            message=_describe_resolve_failure(exc),
            detail={"image_id": image_id},
            retryable=False,
            trace_id=trace_id,
        )
        raise
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=2 ** self.request.retries) from exc
        append_failure(
            failure_type="IMAGE_RESOLVE",
            subject_type="IMAGE_ASSET",
            subject_ref=image_id,
            error_code="IMAGE_RESOLVE_FAILED",
            message=str(exc),
            detail={"image_id": image_id},
            retryable=False,
            trace_id=trace_id,
        )
        raise
    return resolved.public_id


@shared_task(
    name="apps.governance.reresolve_image_digest",
    bind=True,
    max_retries=2,
    queue="q_provision",
    acks_late=True,
)
def reresolve_image_digest_task(self: Any, image_id: str, trace_id: str = "") -> str:
    try:
        resolved = reresolve_image_digest(
            image_id=image_id,
            context=ActorContext("PLATFORM_WORKER", "PLATFORM", trace_id),
        )
    except (GovernanceValidationError, GovernanceStateConflict) as exc:
        # 确定性失败(运行时不可达 / 重解析出的摘要与目录内其它资产重复)重试无意义
        append_failure(
            failure_type="IMAGE_RERESOLVE",
            subject_type="IMAGE_ASSET",
            subject_ref=image_id,
            error_code="IMAGE_RERESOLVE_FAILED",
            message=_describe_resolve_failure(exc),
            detail={"image_id": image_id},
            retryable=False,
            trace_id=trace_id,
        )
        raise
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=2 ** self.request.retries) from exc
        append_failure(
            failure_type="IMAGE_RERESOLVE",
            subject_type="IMAGE_ASSET",
            subject_ref=image_id,
            error_code="IMAGE_RERESOLVE_FAILED",
            message=str(exc),
            detail={"image_id": image_id},
            retryable=False,
            trace_id=trace_id,
        )
        raise
    return resolved.public_id
