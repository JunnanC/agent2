from typing import Any

from rest_framework import serializers

from .models import (
    ImageAsset,
    NetworkAllowlist,
    Quota,
    ResourceProfile,
    RuntimeAdapter,
    SecurityPolicy,
)


class GovernanceReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class RuntimeAdapterCreateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=64)
    name = serializers.CharField(max_length=120)
    runtime_type = serializers.ChoiceField(choices=RuntimeAdapter.RuntimeType.choices)
    driver = serializers.ChoiceField(choices=RuntimeAdapter.Driver.choices)
    config_ref = serializers.CharField(max_length=128, required=False, allow_blank=True)
    reason = serializers.CharField(max_length=500)


class RuntimeAdapterUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    config_ref = serializers.CharField(max_length=128, required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=RuntimeAdapter.Status.choices, required=False)
    budget_cpu_millicores = serializers.IntegerField(min_value=0, required=False)
    budget_memory_mb = serializers.IntegerField(min_value=0, required=False)
    reason = serializers.CharField(max_length=500)


class ImageCreateSerializer(serializers.Serializer):
    registry = serializers.CharField(max_length=255)
    repository = serializers.CharField(max_length=255)
    display_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    display_tag = serializers.CharField(max_length=128, required=False, allow_blank=True)
    digest = serializers.CharField(max_length=71, required=False, allow_blank=True)
    risk_level = serializers.ChoiceField(choices=ImageAsset.RiskLevel.choices)
    reason = serializers.CharField(max_length=500)


class ImageRenameSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=120)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ImageResolveSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ImageReResolveSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ImageScanSerializer(serializers.Serializer):
    scan_status = serializers.ChoiceField(choices=ImageAsset.ScanStatus.choices)
    scan_report_ref = serializers.CharField(max_length=128, required=False, allow_blank=True)
    risk_level = serializers.ChoiceField(choices=ImageAsset.RiskLevel.choices)
    reason = serializers.CharField(max_length=500)


class ImageDecisionSerializer(serializers.Serializer):
    decision = serializers.CharField(max_length=16)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ResourceProfileCreateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=64)
    name = serializers.CharField(max_length=120)
    runtime_type = serializers.ChoiceField(choices=RuntimeAdapter.RuntimeType.choices)
    cpu_millicores = serializers.IntegerField(min_value=1)
    memory_mb = serializers.IntegerField(min_value=1)
    cpu_request_millicores = serializers.IntegerField(min_value=1, required=False)
    cpu_limit_millicores = serializers.IntegerField(min_value=1, required=False)
    memory_request_mb = serializers.IntegerField(min_value=1, required=False)
    memory_limit_mb = serializers.IntegerField(min_value=1, required=False)
    disk_gb = serializers.IntegerField(min_value=1)
    network_mode = serializers.ChoiceField(choices=ResourceProfile.NetworkMode.choices)
    cost_minor_per_hour = serializers.IntegerField(min_value=0, default=0)
    currency_code = serializers.CharField(min_length=3, max_length=3, default="CNY")
    reason = serializers.CharField(max_length=500)


class ResourceProfileUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    runtime_type = serializers.ChoiceField(
        choices=RuntimeAdapter.RuntimeType.choices, required=False
    )
    cpu_millicores = serializers.IntegerField(min_value=1, required=False)
    memory_mb = serializers.IntegerField(min_value=1, required=False)
    cpu_request_millicores = serializers.IntegerField(min_value=1, required=False)
    cpu_limit_millicores = serializers.IntegerField(min_value=1, required=False)
    memory_request_mb = serializers.IntegerField(min_value=1, required=False)
    memory_limit_mb = serializers.IntegerField(min_value=1, required=False)
    disk_gb = serializers.IntegerField(min_value=1, required=False)
    network_mode = serializers.ChoiceField(
        choices=ResourceProfile.NetworkMode.choices, required=False
    )
    cost_minor_per_hour = serializers.IntegerField(min_value=0, required=False)
    currency_code = serializers.CharField(min_length=3, max_length=3, required=False)
    reason = serializers.CharField(max_length=500)


class QuotaWriteSerializer(serializers.Serializer):
    scope_type = serializers.CharField(max_length=16, required=False)
    course_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    user_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    max_concurrent_instances = serializers.IntegerField(
        min_value=1, required=False, allow_null=True
    )
    max_concurrent_starts = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    max_cpu_millicores = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    max_memory_mb = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    max_disk_gb = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    max_object_storage_bytes = serializers.IntegerField(
        min_value=1, required=False, allow_null=True
    )
    max_agent_tokens_per_day = serializers.IntegerField(
        min_value=1, required=False, allow_null=True
    )
    max_agent_requests_per_minute = serializers.IntegerField(
        min_value=1, required=False, allow_null=True
    )
    reason = serializers.CharField(max_length=500)


class PolicyPutSerializer(serializers.Serializer):
    scope_type = serializers.CharField(max_length=16)
    course_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    risk_level = serializers.ChoiceField(choices=SecurityPolicy.RiskLevel.choices)
    rules = serializers.JSONField()
    reason = serializers.CharField(max_length=500)


class AllowlistCreateSerializer(serializers.Serializer):
    scope_type = serializers.CharField(max_length=16)
    course_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    target_type = serializers.ChoiceField(choices=NetworkAllowlist.TargetType.choices)
    target_value = serializers.CharField(max_length=255)
    protocol = serializers.ChoiceField(choices=NetworkAllowlist.Protocol.choices)
    port_start = serializers.IntegerField(min_value=1, max_value=65535)
    port_end = serializers.IntegerField(min_value=1, max_value=65535)
    risk_level = serializers.ChoiceField(choices=SecurityPolicy.RiskLevel.choices)
    reason = serializers.CharField(max_length=500)


class GovernanceTraceMetaSerializer(serializers.Serializer):
    trace_id = serializers.CharField()


class GovernancePageMetaSerializer(GovernanceTraceMetaSerializer):
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total = serializers.IntegerField()


class RuntimeAdapterDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    code = serializers.CharField()
    name = serializers.CharField()
    runtime_type = serializers.CharField()
    driver = serializers.CharField()
    status = serializers.CharField()
    config_ref = serializers.CharField()
    health_status = serializers.CharField()
    node_count = serializers.IntegerField()
    capacity_cpu_millicores = serializers.IntegerField()
    available_cpu_millicores = serializers.IntegerField()
    capacity_memory_mb = serializers.IntegerField()
    available_memory_mb = serializers.IntegerField()
    budget_cpu_millicores = serializers.IntegerField()
    budget_memory_mb = serializers.IntegerField()
    last_health_at = serializers.DateTimeField(allow_null=True)
    row_version = serializers.IntegerField()


class ImageDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    registry = serializers.CharField()
    repository = serializers.CharField()
    display_name = serializers.CharField()
    display_tag = serializers.CharField()
    digest = serializers.CharField()
    scan_status = serializers.CharField()
    approval_status = serializers.CharField()
    risk_level = serializers.CharField()
    scan_report_ref = serializers.CharField()
    scanned_at = serializers.DateTimeField(allow_null=True)
    approved_at = serializers.DateTimeField(allow_null=True)
    row_version = serializers.IntegerField()


class ResourceProfileDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    code = serializers.CharField()
    name = serializers.CharField()
    runtime_type = serializers.CharField()
    status = serializers.CharField()
    cpu_millicores = serializers.IntegerField()
    memory_mb = serializers.IntegerField()
    cpu_request_millicores = serializers.IntegerField()
    cpu_limit_millicores = serializers.IntegerField()
    memory_request_mb = serializers.IntegerField()
    memory_limit_mb = serializers.IntegerField()
    disk_gb = serializers.IntegerField()
    network_mode = serializers.CharField()
    cost_minor_per_hour = serializers.IntegerField()
    currency_code = serializers.CharField()
    row_version = serializers.IntegerField()


class QuotaDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    scope_type = serializers.CharField()
    scope_key = serializers.CharField()
    course_id = serializers.CharField(allow_null=True)
    user_id = serializers.CharField(allow_null=True)
    max_concurrent_instances = serializers.IntegerField(allow_null=True)
    max_concurrent_starts = serializers.IntegerField(allow_null=True)
    max_cpu_millicores = serializers.IntegerField(allow_null=True)
    max_memory_mb = serializers.IntegerField(allow_null=True)
    max_disk_gb = serializers.IntegerField(allow_null=True)
    max_object_storage_bytes = serializers.IntegerField(allow_null=True)
    max_agent_tokens_per_day = serializers.IntegerField(allow_null=True)
    max_agent_requests_per_minute = serializers.IntegerField(allow_null=True)
    row_version = serializers.IntegerField()


class PolicyDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    policy_kind = serializers.CharField()
    scope_type = serializers.CharField()
    scope_key = serializers.CharField()
    course_id = serializers.CharField(allow_null=True)
    risk_level = serializers.CharField()
    rules = serializers.JSONField()
    row_version = serializers.IntegerField()


class AllowlistDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    scope_type = serializers.CharField()
    scope_key = serializers.CharField()
    course_id = serializers.CharField(allow_null=True)
    target_type = serializers.CharField()
    target_value = serializers.CharField()
    protocol = serializers.CharField()
    port_start = serializers.IntegerField()
    port_end = serializers.IntegerField()
    risk_level = serializers.CharField()
    status = serializers.CharField()
    row_version = serializers.IntegerField()


class ResourceSummaryDataSerializer(serializers.Serializer):
    course_id = serializers.CharField(required=False)
    course_code = serializers.CharField(required=False)
    limits = serializers.DictField(child=serializers.IntegerField(allow_null=True))
    used = serializers.DictField(child=serializers.IntegerField())
    available = serializers.DictField(child=serializers.IntegerField(allow_null=True))
    scaling_policy = serializers.JSONField(required=False, allow_null=True)
    prewarm_active = serializers.IntegerField(required=False)


class UsageDataSerializer(serializers.Serializer):
    reservation = serializers.DictField(child=serializers.IntegerField())
    object_storage_bytes = serializers.IntegerField()
    instances = serializers.JSONField()
    prewarm_active = serializers.IntegerField()


class AlertDataSerializer(serializers.Serializer):
    severity = serializers.CharField()
    code = serializers.CharField()
    resource_type = serializers.CharField()
    resource_ref = serializers.CharField()
    message = serializers.CharField()


class RuntimeAdapterResponseSerializer(serializers.Serializer):
    data = RuntimeAdapterDataSerializer()
    meta = GovernanceTraceMetaSerializer()


class RuntimeAdapterListResponseSerializer(serializers.Serializer):
    data = RuntimeAdapterDataSerializer(many=True)
    meta = GovernancePageMetaSerializer()


class ImageResponseSerializer(serializers.Serializer):
    data = ImageDataSerializer()
    meta = GovernanceTraceMetaSerializer()


class ImageListResponseSerializer(serializers.Serializer):
    data = ImageDataSerializer(many=True)
    meta = GovernancePageMetaSerializer()


class ResourceProfileResponseSerializer(serializers.Serializer):
    data = ResourceProfileDataSerializer()
    meta = GovernanceTraceMetaSerializer()


class ResourceProfileListResponseSerializer(serializers.Serializer):
    data = ResourceProfileDataSerializer(many=True)
    meta = GovernancePageMetaSerializer()


class QuotaResponseSerializer(serializers.Serializer):
    data = QuotaDataSerializer()
    meta = GovernanceTraceMetaSerializer()


class QuotaListResponseSerializer(serializers.Serializer):
    data = QuotaDataSerializer(many=True)
    meta = GovernancePageMetaSerializer()


class PolicyResponseSerializer(serializers.Serializer):
    data = PolicyDataSerializer()
    meta = GovernanceTraceMetaSerializer()


class PolicyListResponseSerializer(serializers.Serializer):
    data = PolicyDataSerializer(many=True)
    meta = GovernancePageMetaSerializer()


class AllowlistResponseSerializer(serializers.Serializer):
    data = AllowlistDataSerializer()
    meta = GovernanceTraceMetaSerializer()


class AllowlistListResponseSerializer(serializers.Serializer):
    data = AllowlistDataSerializer(many=True)
    meta = GovernancePageMetaSerializer()


class ResourceSummaryResponseSerializer(serializers.Serializer):
    data = ResourceSummaryDataSerializer()
    meta = GovernanceTraceMetaSerializer()


class UsageResponseSerializer(serializers.Serializer):
    data = UsageDataSerializer()
    meta = GovernanceTraceMetaSerializer()


class AlertListResponseSerializer(serializers.Serializer):
    data = AlertDataSerializer(many=True)
    meta = GovernancePageMetaSerializer()


def runtime_adapter_data(item: RuntimeAdapter) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "code": item.code,
        "name": item.name,
        "runtime_type": item.runtime_type,
        "driver": item.driver,
        "status": item.status,
        "config_ref": item.config_ref,
        "health_status": item.health_status,
        "node_count": item.node_count,
        "capacity_cpu_millicores": item.capacity_cpu_millicores,
        "available_cpu_millicores": item.available_cpu_millicores,
        "capacity_memory_mb": item.capacity_memory_mb,
        "available_memory_mb": item.available_memory_mb,
        "budget_cpu_millicores": item.budget_cpu_millicores,
        "budget_memory_mb": item.budget_memory_mb,
        "last_health_at": item.last_health_at,
        "row_version": item.row_version,
    }


def image_data(item: ImageAsset) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "registry": item.registry,
        "repository": item.repository,
        "display_name": item.display_name,
        "display_tag": item.display_tag,
        "digest": item.digest,
        "scan_status": item.scan_status,
        "approval_status": item.approval_status,
        "risk_level": item.risk_level,
        "scan_report_ref": item.scan_report_ref,
        "scanned_at": item.scanned_at,
        "approved_at": item.approved_at,
        "row_version": item.row_version,
    }


def resource_profile_data(item: ResourceProfile) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "code": item.code,
        "name": item.name,
        "runtime_type": item.runtime_type,
        "status": item.status,
        "cpu_millicores": item.cpu_millicores,
        "memory_mb": item.memory_mb,
        "cpu_request_millicores": item.cpu_request_millicores,
        "cpu_limit_millicores": item.cpu_limit_millicores,
        "memory_request_mb": item.memory_request_mb,
        "memory_limit_mb": item.memory_limit_mb,
        "disk_gb": item.disk_gb,
        "network_mode": item.network_mode,
        "cost_minor_per_hour": item.cost_minor_per_hour,
        "currency_code": item.currency_code,
        "row_version": item.row_version,
    }


def quota_data(item: Quota) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "scope_type": item.scope_type,
        "scope_key": item.scope_key,
        "course_id": item.course.public_id if item.course else None,
        "user_id": item.user.public_id if item.user else None,
        "max_concurrent_instances": item.max_concurrent_instances,
        "max_concurrent_starts": item.max_concurrent_starts,
        "max_cpu_millicores": item.max_cpu_millicores,
        "max_memory_mb": item.max_memory_mb,
        "max_disk_gb": item.max_disk_gb,
        "max_object_storage_bytes": item.max_object_storage_bytes,
        "max_agent_tokens_per_day": item.max_agent_tokens_per_day,
        "max_agent_requests_per_minute": item.max_agent_requests_per_minute,
        "row_version": item.row_version,
    }


def policy_data(item: SecurityPolicy) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "policy_kind": item.policy_kind,
        "scope_type": item.scope_type,
        "scope_key": item.scope_key,
        "course_id": item.course.public_id if item.course else None,
        "risk_level": item.risk_level,
        "rules": item.rules,
        "row_version": item.row_version,
    }


def allowlist_data(item: NetworkAllowlist) -> dict[str, Any]:
    return {
        "public_id": item.public_id,
        "scope_type": item.scope_type,
        "scope_key": item.scope_key,
        "course_id": item.course.public_id if item.course else None,
        "target_type": item.target_type,
        "target_value": item.target_value,
        "protocol": item.protocol,
        "port_start": item.port_start,
        "port_end": item.port_end,
        "risk_level": item.risk_level,
        "status": item.status,
        "row_version": item.row_version,
    }
