import json
import urllib.error
import urllib.request
from contextlib import suppress
from typing import Any

from celery import shared_task
from django.conf import settings
from django.utils import timezone
from redis import Redis

from apps.core.audit import append_failure
from apps.provisioning.adapters import RuntimeAdapterFailure, runtime_for_driver

from .errors import GovernanceStateConflict, GovernanceValidationError
from .metrics import RUNTIME_ADAPTER_CAPACITY, RUNTIME_ADAPTER_HEALTH
from .models import RuntimeAdapter
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


def _capped_capacity(reported: int, configured: int) -> int:
    """Keep the configured capacity as an upper bound; a probe may only lower it."""
    if configured <= 0:
        return reported
    if reported <= 0:
        return configured
    return min(reported, configured)


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
                runtime_for_driver(
                    adapter_config.driver, config_ref=adapter_config.config_ref
                ).health()
            )
        except RuntimeAdapterFailure:
            health = {"status": RuntimeAdapter.HealthStatus.UNAVAILABLE}
        status = str(health.get("status", RuntimeAdapter.HealthStatus.UNAVAILABLE))
        if status not in RuntimeAdapter.HealthStatus.values:
            status = RuntimeAdapter.HealthStatus.UNAVAILABLE
        capacity_cpu = _capped_capacity(
            _nonnegative_int(health.get("capacity_cpu_millicores", 0)),
            adapter_config.budget_cpu_millicores,
        )
        capacity_memory = _capped_capacity(
            _nonnegative_int(health.get("capacity_memory_mb", 0)),
            adapter_config.budget_memory_mb,
        )
        values = {
            "node_count": _nonnegative_int(health.get("node_count", 0)),
            "capacity_cpu_millicores": capacity_cpu,
            "available_cpu_millicores": min(
                _nonnegative_int(health.get("available_cpu_millicores", 0)), capacity_cpu,
            ),
            "capacity_memory_mb": capacity_memory,
            "available_memory_mb": min(
                _nonnegative_int(health.get("available_memory_mb", 0)), capacity_memory,
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
            RUNTIME_ADAPTER_HEALTH.labels(adapter=adapter_config.code, status=possible_status).set(
                1 if possible_status == status else 0
            )
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


def reconcile_runtime_capacity(*, trace_id: str = "") -> dict[str, int]:
    from apps.provisioning.models import RuntimeCapacityReservation
    from apps.provisioning.services import release_runtime_capacity

    released = 0
    for binding in (
        RuntimeCapacityReservation.objects.filter(status="ACTIVE")
        .exclude(
            reservation__status="ACTIVE",
        )
        .select_related("reservation")
    ):
        release_runtime_capacity(reservation_id=binding.reservation)
        released += 1
    return {"ensured": 0, "released": released, "failed": 0}


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
            raise self.retry(exc=exc, countdown=2**self.request.retries) from exc
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
            raise self.retry(exc=exc, countdown=2**self.request.retries) from exc
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
