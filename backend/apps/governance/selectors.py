import json
from datetime import timedelta
from typing import Any, cast

from django.conf import settings
from django.db.models import QuerySet, Sum
from django.utils import timezone
from redis import Redis

from apps.accounts.models import User
from apps.core.errors import ResourceNotFound
from apps.core.models import ObjectAsset
from apps.courses.models import Course, CourseStaffGrant
from apps.courses.selectors import active_enrollment, require_course_capability

from .models import (
    ImageAsset,
    NetworkAllowlist,
    Quota,
    QuotaReservation,
    ResourceProfile,
    RuntimeAdapter,
    SecurityPolicy,
)
from .ports import has_instance_usage_provider, instance_usage

LIMIT_FIELDS = (
    "max_concurrent_instances",
    "max_concurrent_starts",
    "max_cpu_millicores",
    "max_memory_mb",
    "max_disk_gb",
    "max_object_storage_bytes",
    "max_agent_tokens_per_day",
    "max_agent_requests_per_minute",
)

USAGE_TO_LIMIT = {
    "instance_count": "max_concurrent_instances",
    "start_count": "max_concurrent_starts",
    "cpu_millicores": "max_cpu_millicores",
    "memory_mb": "max_memory_mb",
    "disk_gb": "max_disk_gb",
    "object_storage_bytes": "max_object_storage_bytes",
    "agent_tokens": "max_agent_tokens_per_day",
    "agent_requests": "max_agent_requests_per_minute",
}


def platform_quota() -> Quota | None:
    return Quota.objects.filter(scope_type=Quota.ScopeType.PLATFORM).first()


def quota_levels(*, course: Course | None, user: User | None) -> list[Quota]:
    rows: list[Quota] = []
    platform = platform_quota()
    if platform is not None:
        rows.append(platform)
    if course is not None:
        course_quota = Quota.objects.filter(course=course).first()
        if course_quota is not None:
            rows.append(course_quota)
    if user is not None:
        user_quota = Quota.objects.filter(user=user).first()
        if user_quota is not None:
            rows.append(user_quota)
    return rows


def effective_limits(*, course: Course | None, user: User | None) -> dict[str, int | None]:
    result: dict[str, int | None] = {}
    rows = quota_levels(course=course, user=user)
    for field in LIMIT_FIELDS:
        values = [int(value) for row in rows if (value := getattr(row, field)) is not None]
        result[field] = min(values) if values else None
    return result


def reservation_usage(
    *,
    course: Course | None = None,
    user: User | None = None,
) -> dict[str, int]:
    queryset = QuotaReservation.objects.filter(status=QuotaReservation.Status.ACTIVE)
    if course is not None:
        queryset = queryset.filter(course=course)
    if user is not None:
        queryset = queryset.filter(user=user)
    aggregate = queryset.aggregate(
        instance_count=Sum("instance_count"),
        start_count=Sum("start_count"),
        cpu_millicores=Sum("cpu_millicores"),
        memory_mb=Sum("memory_mb"),
        disk_gb=Sum("disk_gb"),
        object_storage_bytes=Sum("object_storage_bytes"),
        agent_tokens=Sum("agent_tokens"),
        agent_requests=Sum("agent_requests"),
        estimated_cost_minor=Sum("estimated_cost_minor"),
    )
    return {key: int(value or 0) for key, value in aggregate.items()}


def resource_summary(*, course: Course | None, user: User | None) -> dict[str, Any]:
    limits = effective_limits(course=course, user=user)
    # Each inherited quota is consumed at its own scope. A user summary must
    # include other users' course reservations and a user's reservations in
    # other courses before reporting the intersection of remaining capacity.
    scoped_usage: list[dict[str, int]] = []
    if platform_quota() is not None:
        scoped_usage.append(reservation_usage())
    if course is not None and Quota.objects.filter(course=course).exists():
        scoped_usage.append(reservation_usage(course=course))
    if user is not None and Quota.objects.filter(user=user).exists():
        scoped_usage.append(reservation_usage(user=user))
    used = {
        usage_field: max((usage.get(usage_field, 0) for usage in scoped_usage), default=0)
        for usage_field in USAGE_TO_LIMIT
    }
    available: dict[str, int | None] = {}
    for usage_field, limit_field in USAGE_TO_LIMIT.items():
        remaining: list[int] = []
        for quota, usage in zip(quota_levels(course=course, user=user), scoped_usage, strict=False):
            limit = getattr(quota, limit_field)
            if limit is not None:
                remaining.append(max(0, int(limit) - usage.get(usage_field, 0)))
        available[usage_field] = min(remaining) if remaining else None
    return {"limits": limits, "used": used, "available": available}


def teacher_governance_summary(*, actor: User, course_id: str) -> dict[str, Any]:
    try:
        course = Course.objects.get(public_id=course_id)
    except Course.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    require_course_capability(
        course=course,
        actor=actor,
        capability=CourseStaffGrant.Capability.VIEW_PROGRESS,
    )
    summary = resource_summary(course=course, user=None)
    scaling = SecurityPolicy.objects.filter(
        policy_kind=SecurityPolicy.PolicyKind.RESOURCE_SCALING,
        course=course,
    ).first()
    summary.update({
        "course_id": course.public_id,
        "course_code": course.code,
        "scaling_policy": scaling.rules if scaling else None,
        "prewarm_active": QuotaReservation.objects.filter(
            course=course,
            reservation_type=QuotaReservation.ReservationType.PREWARM,
            status=QuotaReservation.Status.ACTIVE,
        ).count(),
    })
    return summary


def student_resource_summary(*, actor: User, course_id: str) -> dict[str, Any]:
    try:
        course = Course.objects.get(public_id=course_id)
    except Course.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if active_enrollment(course=course, student=actor) is None:
        raise ResourceNotFound()
    summary = resource_summary(course=course, user=actor)
    summary.update({"course_id": course.public_id, "course_code": course.code})
    return summary


def platform_usage_summary() -> dict[str, Any]:
    reservation = reservation_usage()
    storage = int(
        ObjectAsset.objects.filter(status=ObjectAsset.Status.ACTIVE).aggregate(
            total=Sum("size_bytes")
        )["total"]
        or 0
    )
    runtime = instance_usage()
    return {
        "reservation": reservation,
        "object_storage_bytes": storage,
        "instances": {
            "available": has_instance_usage_provider(),
            "active_instances": runtime.active_instances,
            "cpu_millicores": runtime.cpu_millicores,
            "memory_mb": runtime.memory_mb,
        },
        "prewarm_active": QuotaReservation.objects.filter(
            reservation_type=QuotaReservation.ReservationType.PREWARM,
            status=QuotaReservation.Status.ACTIVE,
        ).count(),
    }


def platform_alert_summaries(*, client: Redis | None = None) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    stale_before = timezone.now() - timedelta(seconds=settings.GOVERNANCE_HEALTH_STALE_SECONDS)
    for adapter in RuntimeAdapter.objects.filter(status=RuntimeAdapter.Status.ENABLED):
        if adapter.last_health_at is None or adapter.last_health_at < stale_before:
            alerts.append({
                "severity": "P3",
                "code": "RUNTIME_HEALTH_STALE",
                "resource_type": "runtime_adapter",
                "resource_ref": adapter.public_id,
                "message": "运行时健康数据已过期",
            })
        elif adapter.health_status in {
            RuntimeAdapter.HealthStatus.DEGRADED,
            RuntimeAdapter.HealthStatus.UNAVAILABLE,
        }:
            alerts.append({
                "severity": "P3" if adapter.health_status == "DEGRADED" else "P1",
                "code": f"RUNTIME_{adapter.health_status}",
                "resource_type": "runtime_adapter",
                "resource_ref": adapter.public_id,
                "message": "运行时容量或健康状态异常",
            })
    platform = platform_quota()
    if platform is not None:
        usage = reservation_usage()
        for usage_field, limit_field in USAGE_TO_LIMIT.items():
            limit = getattr(platform, limit_field)
            if limit and usage[usage_field] / int(limit) >= 0.85:
                alerts.append({
                    "severity": "P2",
                    "code": "QUOTA_PRESSURE",
                    "resource_type": "quota",
                    "resource_ref": platform.public_id,
                    "message": f"{limit_field} 使用率达到 85%",
                })
    redis_client = client or Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        raw = redis_client.get("governance:health:minio")
        storage_health = json.loads(cast(str, raw)) if raw else None
    except Exception:
        storage_health = None
    if storage_health is None or storage_health.get("status") != "HEALTHY":
        alerts.append({
            "severity": "P3",
            "code": "OBJECT_STORAGE_HEALTH_UNKNOWN",
            "resource_type": "object_storage",
            "resource_ref": "minio",
            "message": "对象存储健康状态未知或降级",
        })
    return alerts


def runtime_adapters() -> QuerySet[RuntimeAdapter]:
    return RuntimeAdapter.objects.order_by("code")


def images() -> QuerySet[ImageAsset]:
    return ImageAsset.objects.order_by("repository", "display_tag", "id")


def resource_profiles() -> QuerySet[ResourceProfile]:
    return ResourceProfile.objects.order_by("runtime_type", "code")


def quotas() -> QuerySet[Quota]:
    return Quota.objects.select_related("course", "user").order_by("scope_type", "scope_key")


def policies(kind: str) -> QuerySet[SecurityPolicy]:
    return (
        SecurityPolicy.objects.select_related("course")
        .filter(policy_kind=kind)
        .order_by("scope_type", "scope_key")
    )


def allowlist_entries() -> QuerySet[NetworkAllowlist]:
    return NetworkAllowlist.objects.select_related("course").order_by("scope_key", "target_value")
