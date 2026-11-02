from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from apps.courses.models import Course

from .models import ImageAsset, NetworkAllowlist, ResourceProfile, RuntimeAdapter, SecurityPolicy


@dataclass(frozen=True)
class InstanceUsage:
    active_instances: int = 0
    cpu_millicores: int = 0
    memory_mb: int = 0


InstanceUsageProvider = Callable[[str | None], InstanceUsage]

_instance_usage_providers: list[InstanceUsageProvider] = []


def register_instance_usage_provider(provider: InstanceUsageProvider) -> None:
    if provider not in _instance_usage_providers:
        _instance_usage_providers.append(provider)


def instance_usage(course_ref: str | None = None) -> InstanceUsage:
    result = InstanceUsage()
    for provider in _instance_usage_providers:
        current = provider(course_ref)
        result = InstanceUsage(
            active_instances=result.active_instances + current.active_instances,
            cpu_millicores=result.cpu_millicores + current.cpu_millicores,
            memory_mb=result.memory_mb + current.memory_mb,
        )
    return result


def has_instance_usage_provider() -> bool:
    return bool(_instance_usage_providers)


def clear_instance_usage_providers() -> None:
    _instance_usage_providers.clear()


def template_resource_options() -> dict[str, list[dict[str, Any]]]:
    return {
        "runtime_adapters": [
            {
                "public_id": item.public_id,
                "code": item.code,
                "name": item.name,
                "runtime_type": item.runtime_type,
                "driver": item.driver,
                "health_status": item.health_status,
            }
            for item in RuntimeAdapter.objects.filter(
                status=RuntimeAdapter.Status.ENABLED
            ).order_by("code")
        ],
        "images": [
            {
                "public_id": item.public_id,
                "repository": item.repository,
                "display_tag": item.display_tag,
                "digest": item.digest,
                "risk_level": item.risk_level,
            }
            for item in ImageAsset.objects.filter(
                approval_status=ImageAsset.ApprovalStatus.APPROVED,
                scan_status=ImageAsset.ScanStatus.CLEAN,
            ).order_by("repository", "display_tag")
        ],
        "resource_profiles": [
            {
                "public_id": item.public_id,
                "code": item.code,
                "name": item.name,
                "runtime_type": item.runtime_type,
                "cpu_millicores": item.cpu_millicores,
                "memory_mb": item.memory_mb,
                "disk_gb": item.disk_gb,
                "network_mode": item.network_mode,
            }
            for item in ResourceProfile.objects.filter(
                status=ResourceProfile.Status.ACTIVE
            ).order_by("runtime_type", "code")
        ],
    }


def template_governance_snapshot(
    *,
    course: Course,
    runtime_adapter_id: str,
    image_id: str,
    resource_profile_id: str,
) -> dict[str, Any] | None:
    adapter = RuntimeAdapter.objects.filter(
        public_id=runtime_adapter_id, status=RuntimeAdapter.Status.ENABLED
    ).first()
    image = ImageAsset.objects.filter(
        public_id=image_id,
        approval_status=ImageAsset.ApprovalStatus.APPROVED,
        scan_status=ImageAsset.ScanStatus.CLEAN,
    ).first()
    profile = ResourceProfile.objects.filter(
        public_id=resource_profile_id, status=ResourceProfile.Status.ACTIVE
    ).first()
    if adapter is None or image is None or profile is None:
        return None
    policies = list(
        SecurityPolicy.objects.filter(
            policy_kind=SecurityPolicy.PolicyKind.RUNTIME_SECURITY,
            scope_key__in=("PLATFORM", f"COURSE:{course.public_id}"),
        ).order_by("scope_type")
    )
    allowlist = list(
        NetworkAllowlist.objects.filter(
            status=NetworkAllowlist.Status.ACTIVE,
            scope_key__in=("PLATFORM", f"COURSE:{course.public_id}"),
        ).values("target_type", "target_value", "protocol", "port_start", "port_end")
    )
    return {
        "adapter": adapter,
        "image": image,
        "profile": profile,
        "security_policies": policies,
        "allowlist": allowlist,
    }
