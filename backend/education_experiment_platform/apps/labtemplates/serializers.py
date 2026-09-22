from rest_framework import serializers

from apps.core.models import ObjectAsset

from .models import AutoCheckRule, Template, TemplatePrecheckRun, TemplateVersion


class TemplateWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    category = serializers.CharField(max_length=64, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)


class TemplatePatchSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160, required=False)
    category = serializers.CharField(max_length=64, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)


class TemplateVersionWriteSerializer(serializers.Serializer):
    runtime_type = serializers.ChoiceField(choices=("CONTAINER", "VM"), required=False)
    runtime_adapter_id = serializers.CharField(max_length=26, required=False)
    image_id = serializers.CharField(max_length=26, required=False)
    resource_profile_id = serializers.CharField(max_length=26, required=False)
    dependencies = serializers.ListField(child=serializers.DictField(), required=False)
    network_policy = serializers.DictField(required=False)
    workspace_capabilities = serializers.DictField(required=False)
    material_version_ids = serializers.ListField(
        child=serializers.CharField(max_length=26), required=False
    )
    report_policy = serializers.DictField(required=False)
    review_policy = serializers.DictField(required=False)
    retention_days = serializers.IntegerField(min_value=1, max_value=3650, required=False)


class AutoCheckRuleWriteSerializer(serializers.Serializer):
    position = serializers.IntegerField(min_value=1)
    checker_type = serializers.RegexField(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    input_schema = serializers.DictField()
    output_schema = serializers.DictField()
    timeout_seconds = serializers.IntegerField(min_value=1)
    resource_limit = serializers.DictField()
    network_policy = serializers.DictField()
    display_policy = serializers.DictField()
    failure_semantics = serializers.DictField()


class AutoCheckRulesWriteSerializer(serializers.Serializer):
    rules = AutoCheckRuleWriteSerializer(many=True)


class TemplateAssetCreateSerializer(serializers.Serializer):
    version_id = serializers.CharField(max_length=26)
    purpose = serializers.ChoiceField(choices=("MANUAL", "STARTER", "REPORT_TEMPLATE"))
    file_name = serializers.CharField(max_length=255)
    media_type = serializers.CharField(max_length=255)
    size_bytes = serializers.IntegerField(min_value=1)
    digest_sha256 = serializers.RegexField(r"^[0-9a-fA-F]{64}$")


class TemplateAssetDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    version_id = serializers.CharField()
    purpose = serializers.CharField()
    file_name = serializers.CharField()
    media_type = serializers.CharField()
    size_bytes = serializers.IntegerField()
    digest_sha256 = serializers.CharField()
    scan_status = serializers.ChoiceField(choices=ObjectAsset.ScanStatus.choices)
    status = serializers.ChoiceField(choices=ObjectAsset.Status.choices)
    failure_code = serializers.CharField()
    attached = serializers.BooleanField()
    row_version = serializers.IntegerField()


class TemplateAssetUploadDataSerializer(serializers.Serializer):
    asset = TemplateAssetDataSerializer()
    upload = serializers.DictField()


class TemplateAssetResponseSerializer(serializers.Serializer):
    data = TemplateAssetDataSerializer()
    meta = serializers.DictField()


class TemplateAssetUploadResponseSerializer(serializers.Serializer):
    data = TemplateAssetUploadDataSerializer()
    meta = serializers.DictField()


class TemplateDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    course_id = serializers.CharField()
    name = serializers.CharField()
    category = serializers.CharField()
    description = serializers.CharField()
    owner_id = serializers.CharField()
    status = serializers.ChoiceField(choices=Template.Status.choices)
    current_version_id = serializers.CharField(allow_null=True)
    row_version = serializers.IntegerField()


class AutoCheckRuleDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    position = serializers.IntegerField()
    checker_type = serializers.CharField()
    input_schema = serializers.DictField()
    output_schema = serializers.DictField()
    timeout_seconds = serializers.IntegerField()
    resource_limit = serializers.DictField()
    network_policy = serializers.DictField()
    display_policy = serializers.DictField()
    failure_semantics = serializers.DictField()
    rule_digest = serializers.CharField()


class AutoCheckRulesDataSerializer(serializers.Serializer):
    rules = AutoCheckRuleDataSerializer(many=True)


class AutoCheckRulesResponseSerializer(serializers.Serializer):
    data = AutoCheckRulesDataSerializer()
    meta = serializers.DictField()


class TemplateVersionDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    template_id = serializers.CharField()
    version_no = serializers.IntegerField()
    status = serializers.ChoiceField(choices=TemplateVersion.Status.choices)
    runtime_type = serializers.CharField()
    runtime_adapter_id = serializers.CharField()
    image_id = serializers.CharField()
    image_digest = serializers.CharField()
    resource_profile_id = serializers.CharField()
    dependencies = serializers.ListField(child=serializers.DictField())
    network_policy = serializers.DictField()
    workspace_capabilities = serializers.DictField()
    material_refs = serializers.ListField(child=serializers.DictField())
    manual_asset_id = serializers.CharField(allow_null=True)
    starter_asset_id = serializers.CharField(allow_null=True)
    report_template_asset_id = serializers.CharField(allow_null=True)
    report_policy = serializers.DictField()
    review_policy = serializers.DictField()
    retention_days = serializers.IntegerField()
    spec_digest = serializers.CharField(allow_null=True)
    row_version = serializers.IntegerField()
    rules = AutoCheckRuleDataSerializer(many=True)


class PrecheckRunDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    template_version_id = serializers.CharField()
    status = serializers.ChoiceField(choices=TemplatePrecheckRun.Status.choices)
    current_stage = serializers.CharField()
    stage_results = serializers.ListField(child=serializers.DictField())
    attempt_count = serializers.IntegerField()
    max_attempts = serializers.IntegerField()
    error_code = serializers.CharField()
    error_detail = serializers.DictField()
    retryable = serializers.BooleanField()
    trace_id = serializers.CharField()
    started_at = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)


class TemplateOptionsDataSerializer(serializers.Serializer):
    runtime_adapters = serializers.ListField(child=serializers.DictField())
    images = serializers.ListField(child=serializers.DictField())
    resource_profiles = serializers.ListField(child=serializers.DictField())
    materials = serializers.ListField(child=serializers.DictField())


class TemplateResponseSerializer(serializers.Serializer):
    data = TemplateDataSerializer()
    meta = serializers.DictField()


class TemplateListResponseSerializer(serializers.Serializer):
    data = TemplateDataSerializer(many=True)
    meta = serializers.DictField()


class TemplateVersionResponseSerializer(serializers.Serializer):
    data = TemplateVersionDataSerializer()
    meta = serializers.DictField()


class TemplateVersionListResponseSerializer(serializers.Serializer):
    data = TemplateVersionDataSerializer(many=True)
    meta = serializers.DictField()


class PrecheckRunResponseSerializer(serializers.Serializer):
    data = PrecheckRunDataSerializer()
    meta = serializers.DictField()


class PrecheckRunListResponseSerializer(serializers.Serializer):
    data = PrecheckRunDataSerializer(many=True)
    meta = serializers.DictField()


class TemplateOptionsResponseSerializer(serializers.Serializer):
    data = TemplateOptionsDataSerializer()
    meta = serializers.DictField()


class PlatformPrecheckSummaryResponseSerializer(serializers.Serializer):
    data = serializers.DictField()
    meta = serializers.DictField()


def template_data(item: Template) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "course_id": item.course.public_id,
        "name": item.name,
        "category": item.category,
        "description": item.description,
        "owner_id": item.owner.public_id,
        "status": item.status,
        "current_version_id": item.current_version.public_id if item.current_version else None,
        "row_version": item.row_version,
    }


def rule_data(item: AutoCheckRule) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "position": item.position,
        "checker_type": item.checker_type,
        "input_schema": item.input_schema,
        "output_schema": item.output_schema,
        "timeout_seconds": item.timeout_seconds,
        "resource_limit": item.resource_limit,
        "network_policy": item.network_policy,
        "display_policy": item.display_policy,
        "failure_semantics": item.failure_semantics,
        "rule_digest": item.rule_digest,
    }


def version_data(item: TemplateVersion) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "template_id": item.template.public_id,
        "version_no": item.version_no,
        "status": item.status,
        "runtime_type": item.runtime_type,
        "runtime_adapter_id": item.runtime_adapter.public_id,
        "image_id": item.image.public_id,
        "image_digest": item.image.digest,
        "resource_profile_id": item.resource_profile.public_id,
        "dependencies": item.dependencies,
        "network_policy": item.network_policy,
        "workspace_capabilities": item.workspace_capabilities,
        "material_refs": item.material_refs,
        "manual_asset_id": item.manual_asset.public_id if item.manual_asset else None,
        "starter_asset_id": item.starter_asset.public_id if item.starter_asset else None,
        "report_template_asset_id": (
            item.report_template_asset.public_id if item.report_template_asset else None
        ),
        "report_policy": item.report_policy,
        "review_policy": item.review_policy,
        "retention_days": item.retention_days,
        "spec_digest": item.spec_digest,
        "row_version": item.row_version,
        "rules": [
            rule_data(rule)
            for rule in item.auto_check_rules.filter(is_active=True).order_by("position")
        ],
    }


def precheck_data(item: TemplatePrecheckRun) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "template_version_id": item.template_version.public_id,
        "status": item.status,
        "current_stage": item.current_stage,
        "stage_results": item.stage_results,
        "attempt_count": item.attempt_count,
        "max_attempts": item.max_attempts,
        "error_code": item.error_code,
        "error_detail": item.error_detail_masked,
        "retryable": item.retryable,
        "trace_id": item.trace_id,
        "started_at": item.started_at,
        "completed_at": item.completed_at,
    }


def asset_data(item: object, version: TemplateVersion) -> dict[str, object]:
    from apps.core.models import ObjectAsset

    assert isinstance(item, ObjectAsset)
    if item.purpose == "MANUAL":
        attached_id = version.manual_asset_id
    elif item.purpose == "STARTER":
        attached_id = version.starter_asset_id
    else:
        attached_id = version.report_template_asset_id
    return {
        "public_id": item.public_id,
        "version_id": version.public_id,
        "purpose": item.purpose,
        "file_name": item.original_name,
        "media_type": item.media_type,
        "size_bytes": item.size_bytes,
        "digest_sha256": item.digest_sha256,
        "scan_status": item.scan_status,
        "status": item.status,
        "failure_code": item.failure_code,
        "attached": attached_id == item.pk,
        "row_version": item.row_version,
    }
