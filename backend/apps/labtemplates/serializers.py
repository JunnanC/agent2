from django.conf import settings
from rest_framework import serializers

from apps.core.models import ObjectAsset

from .errors import TemplateValidationError
from .image_services import normalize_image_reference
from .models import (
    AutoCheckRule,
    ExperimentImage,
    Template,
    TemplateChapter,
    TemplatePrecheckRun,
    TemplateTask,
    TemplateVersion,
)


class ExecutionMaterialSerializer(serializers.Serializer):
    asset_id = serializers.CharField(max_length=26)
    role = serializers.ChoiceField(choices=("STUDENT_FILES", "HIDDEN_SOURCE", "PUBLIC_DATA"))


class ExecutionSpecSerializer(serializers.Serializer):
    schema_version = serializers.ChoiceField(choices=(2,), required=False)
    language = serializers.ChoiceField(
        choices=("c", "cpp", "java", "python", "go"), allow_null=True
    )
    toolchain_version = serializers.CharField(
        max_length=32, required=False, allow_null=True, allow_blank=True
    )
    language_standard = serializers.CharField(
        max_length=16, required=False, allow_null=True, allow_blank=True
    )
    toolchain = serializers.DictField(required=False)
    materials = ExecutionMaterialSerializer(many=True, required=False)
    entrypoint = serializers.CharField(max_length=255, allow_null=True, allow_blank=True)
    timeout_seconds = serializers.IntegerField(
        min_value=1, max_value=settings.TEMPLATE_CHECK_TIMEOUT_MAX_SECONDS
    )
    memory_mb = serializers.IntegerField(min_value=1)
    cpu_millicores = serializers.IntegerField(min_value=1)
    comparator = serializers.ChoiceField(choices=("token", "numeric"))
    absolute_tolerance = serializers.FloatField(min_value=0, required=False)
    relative_tolerance = serializers.FloatField(min_value=0, required=False)
    tests_asset = serializers.CharField(max_length=26)
    network_mode = serializers.ChoiceField(choices=("DENY_ALL",))


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
    runtime_adapter_id = serializers.CharField(max_length=26, required=False, allow_null=True)
    image_id = serializers.CharField(max_length=26, required=False, allow_null=True)
    resource_profile_id = serializers.CharField(max_length=26, required=False, allow_null=True)
    dependencies = serializers.ListField(child=serializers.DictField(), required=False)
    execution_spec = ExecutionSpecSerializer(required=False)
    network_policy = serializers.DictField(required=False)
    workspace_capabilities = serializers.DictField(required=False)
    material_version_ids = serializers.ListField(
        child=serializers.CharField(max_length=26), required=False
    )
    report_policy = serializers.DictField(required=False)
    review_policy = serializers.DictField(required=False)
    retention_days = serializers.IntegerField(min_value=1, max_value=3650, required=False)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({"unknown": sorted(unknown)})
        execution_spec = self.initial_data.get("execution_spec")
        if isinstance(execution_spec, dict):
            spec_unknown = set(execution_spec) - {
                "schema_version", "language", "toolchain_version", "language_standard", "toolchain",
                "materials",
                "entrypoint", "timeout_seconds", "memory_mb", "cpu_millicores",
                "comparator", "absolute_tolerance", "relative_tolerance", "tests_asset",
                "network_mode",
            }
            if spec_unknown:
                raise serializers.ValidationError(
                    {"execution_spec": {"unknown": sorted(spec_unknown)}}
                )
        return attrs


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


class TemplateChapterWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    learning_objectives = serializers.ListField(child=serializers.CharField(), required=False)
    sort_order = serializers.IntegerField(min_value=1, required=False)
    status = serializers.ChoiceField(choices=TemplateChapter.Status.choices, required=False)
    resource_profile_id = serializers.CharField(max_length=26, required=False, allow_null=True)


class TemplateTaskWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    instructions = serializers.CharField(required=False, allow_blank=True)
    task_type = serializers.CharField(max_length=64, required=False)
    sort_order = serializers.IntegerField(min_value=1, required=False)
    status = serializers.ChoiceField(choices=TemplateTask.Status.choices, required=False)
    execution_spec = serializers.DictField(required=False)
    resource_profile_id = serializers.CharField(max_length=26, required=False, allow_null=True)
    submission_policy = serializers.DictField(required=False)
    grading_policy = serializers.DictField(required=False)
    question_spec = serializers.DictField(required=False)
    marking_spec = serializers.DictField(required=False)
    max_score = serializers.DecimalField(max_digits=7, decimal_places=2, required=False)


class ReorderWriteSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.CharField(max_length=26), allow_empty=False)


class ExecutionSpecSaveSerializer(serializers.Serializer):
    tests_json = serializers.CharField()
    schema_version = serializers.ChoiceField(choices=(2,), required=False)
    language = serializers.ChoiceField(
        choices=("c", "cpp", "java", "python", "go"), allow_null=True
    )
    toolchain_version = serializers.CharField(
        max_length=32, required=False, allow_null=True, allow_blank=True
    )
    language_standard = serializers.CharField(
        max_length=16, required=False, allow_null=True, allow_blank=True
    )
    materials = ExecutionMaterialSerializer(many=True, required=False)
    entrypoint = serializers.CharField(max_length=255, allow_null=True, allow_blank=True)
    timeout_seconds = serializers.IntegerField(
        min_value=1, max_value=settings.TEMPLATE_CHECK_TIMEOUT_MAX_SECONDS
    )
    memory_mb = serializers.IntegerField(min_value=1)
    cpu_millicores = serializers.IntegerField(min_value=1)
    comparator = serializers.ChoiceField(choices=("token", "numeric"))
    absolute_tolerance = serializers.FloatField(min_value=0, required=False)
    relative_tolerance = serializers.FloatField(min_value=0, required=False)
    network_mode = serializers.ChoiceField(choices=("DENY_ALL",))

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({"unknown": sorted(unknown)})
        return attrs


class TemplateAssetCreateSerializer(serializers.Serializer):
    version_id = serializers.CharField(max_length=26)
    purpose = serializers.ChoiceField(
        choices=(
            "MANUAL",
            "STARTER",
            "REPORT_TEMPLATE",
            "TESTS",
            "BUILD_CONTEXT",
            "HIDDEN_SOURCE",
            "PUBLIC_DATA",
        )
    )
    file_name = serializers.CharField(max_length=255)
    media_type = serializers.CharField(max_length=255)
    size_bytes = serializers.IntegerField(min_value=1)
    digest_sha256 = serializers.RegexField(r"^[0-9a-fA-F]{64}$")


class ExperimentImageCreateSerializer(serializers.Serializer):
    template_version_id = serializers.CharField(max_length=26)
    source_type = serializers.ChoiceField(choices=ExperimentImage.SourceType.choices)
    registry = serializers.CharField(max_length=255, required=False, allow_blank=True)
    repository = serializers.CharField(max_length=255)
    requested_tag = serializers.CharField(max_length=128)
    build_context_asset_id = serializers.CharField(max_length=26, required=False)
    build_args = serializers.DictField(required=False)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        try:
            registry, repository, requested_tag = normalize_image_reference(
                registry=attrs.get("registry", ""),
                repository=attrs.get("repository"),
                requested_tag=attrs.get("requested_tag"),
            )
        except TemplateValidationError as exc:
            raise serializers.ValidationError(exc.detail) from exc
        attrs.update(
            registry=registry,
            repository=repository,
            requested_tag=requested_tag,
        )
        return attrs


class ExperimentImageDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    template_version_id = serializers.CharField()
    source_type = serializers.ChoiceField(choices=ExperimentImage.SourceType.choices)
    registry = serializers.CharField()
    repository = serializers.CharField()
    requested_tag = serializers.CharField()
    resolved_digest = serializers.CharField(allow_blank=True)
    status = serializers.ChoiceField(choices=ExperimentImage.Status.choices)
    scan_status = serializers.ChoiceField(choices=ExperimentImage.ScanStatus.choices)
    image_asset_id = serializers.CharField(allow_null=True)
    build_context_asset_id = serializers.CharField(allow_null=True)
    validation_detail = serializers.DictField()
    build_args = serializers.DictField()
    logs = serializers.CharField()
    error_code = serializers.CharField()
    row_version = serializers.IntegerField()


class ExperimentImageResponseSerializer(serializers.Serializer):
    data = ExperimentImageDataSerializer()
    meta = serializers.DictField()


class ExperimentImagePrepareSerializer(serializers.Serializer):
    build_args = serializers.DictField(required=False)


class ExperimentImageListResponseSerializer(serializers.Serializer):
    data = ExperimentImageDataSerializer(many=True)
    meta = serializers.DictField()


class ExperimentImageEventSerializer(serializers.Serializer):
    event_type = serializers.CharField()
    payload = serializers.DictField()
    trace_id = serializers.CharField()
    created_at = serializers.DateTimeField()


class ExperimentImageEventsResponseSerializer(serializers.Serializer):
    data = ExperimentImageEventSerializer(many=True)
    meta = serializers.DictField()


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


class TemplateAssetListResponseSerializer(serializers.Serializer):
    data = TemplateAssetDataSerializer(many=True)
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


class TemplateTaskDataSerializer(serializers.Serializer):
    question_spec = serializers.DictField()
    marking_spec = serializers.DictField()
    max_score = serializers.DecimalField(max_digits=7, decimal_places=2)
    public_id = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    instructions = serializers.CharField()
    task_type = serializers.CharField()
    sort_order = serializers.IntegerField()
    status = serializers.CharField()
    execution_spec = serializers.DictField()
    resource_profile_id = serializers.CharField(allow_null=True)
    effective_resource_profile_id = serializers.CharField(allow_null=True)
    submission_policy = serializers.DictField()
    grading_policy = serializers.DictField()
    row_version = serializers.IntegerField()


class TemplateChapterDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    learning_objectives = serializers.ListField()
    sort_order = serializers.IntegerField()
    status = serializers.CharField()
    resource_profile_id = serializers.CharField(allow_null=True)
    effective_resource_profile_id = serializers.CharField(allow_null=True)
    row_version = serializers.IntegerField()
    tasks = TemplateTaskDataSerializer(many=True)


class TemplateChapterResponseSerializer(serializers.Serializer):
    data = TemplateChapterDataSerializer()
    meta = serializers.DictField()


class TemplateChapterListResponseSerializer(serializers.Serializer):
    data = TemplateChapterDataSerializer(many=True)
    meta = serializers.DictField()


class TemplateTaskResponseSerializer(serializers.Serializer):
    data = TemplateTaskDataSerializer()
    meta = serializers.DictField()


class TemplateTaskListResponseSerializer(serializers.Serializer):
    data = TemplateTaskDataSerializer(many=True)
    meta = serializers.DictField()


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
    runtime_adapter_id = serializers.CharField(allow_null=True)
    image_id = serializers.CharField(allow_null=True)
    image_digest = serializers.CharField()
    resource_profile_id = serializers.CharField(allow_null=True)
    dependencies = serializers.ListField(child=serializers.DictField())
    execution_spec = serializers.DictField()
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
    chapters = TemplateChapterDataSerializer(many=True)


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
    toolchains = serializers.ListField(child=serializers.DictField())


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


def task_data(item: TemplateTask, version: TemplateVersion) -> dict[str, object]:
    profile = item.resource_profile or item.chapter.resource_profile or version.resource_profile
    return {
        "public_id": item.public_id,
        "title": item.title,
        "description": item.description,
        "instructions": item.instructions,
        "task_type": item.task_type,
        "question_spec": item.question_spec,
        "marking_spec": item.marking_spec,
        "max_score": str(item.max_score),
        "sort_order": item.sort_order,
        "status": item.status,
        "execution_spec": item.execution_spec,
        "resource_profile_id": item.resource_profile.public_id if item.resource_profile else None,
        "effective_resource_profile_id": profile.public_id if profile else None,
        "submission_policy": item.submission_policy,
        "grading_policy": item.grading_policy,
        "row_version": item.row_version,
    }


def chapter_data(item: TemplateChapter, version: TemplateVersion) -> dict[str, object]:
    profile = item.resource_profile or version.resource_profile
    return {
        "public_id": item.public_id,
        "title": item.title,
        "description": item.description,
        "learning_objectives": item.learning_objectives,
        "sort_order": item.sort_order,
        "status": item.status,
        "resource_profile_id": item.resource_profile.public_id if item.resource_profile else None,
        "effective_resource_profile_id": profile.public_id if profile else None,
        "row_version": item.row_version,
        "tasks": [
            task_data(task, version)
            for task in item.tasks.filter(active=True).order_by("sort_order")
        ],
    }


def version_data(item: TemplateVersion) -> dict[str, object]:
    def task_value(task: TemplateTask) -> dict[str, object]:
        profile = task.resource_profile or task.chapter.resource_profile or item.resource_profile
        return {
            "public_id": task.public_id,
            "title": task.title,
            "description": task.description,
            "instructions": task.instructions,
            "task_type": task.task_type,
            "question_spec": task.question_spec,
            "marking_spec": task.marking_spec,
            "max_score": str(task.max_score),
            "sort_order": task.sort_order,
            "status": task.status,
            "execution_spec": task.execution_spec,
            "resource_profile_id": task.resource_profile.public_id
            if task.resource_profile
            else None,
            "effective_resource_profile_id": profile.public_id if profile else None,
            "submission_policy": task.submission_policy,
            "grading_policy": task.grading_policy,
            "row_version": task.row_version,
        }

    def chapter_value(chapter: TemplateChapter) -> dict[str, object]:
        profile = chapter.resource_profile or item.resource_profile
        return {
            "public_id": chapter.public_id,
            "title": chapter.title,
            "description": chapter.description,
            "learning_objectives": chapter.learning_objectives,
            "sort_order": chapter.sort_order,
            "status": chapter.status,
            "resource_profile_id": chapter.resource_profile.public_id
            if chapter.resource_profile
            else None,
            "effective_resource_profile_id": profile.public_id if profile else None,
            "row_version": chapter.row_version,
            "tasks": [
                task_value(task)
                for task in chapter.tasks.filter(active=True).order_by("sort_order")
            ],
        }

    return {
        "public_id": item.public_id,
        "template_id": item.template.public_id,
        "version_no": item.version_no,
        "status": item.status,
        "runtime_type": item.runtime_type,
        "runtime_adapter_id": item.runtime_adapter.public_id if item.runtime_adapter else None,
        "image_id": item.image.public_id if item.image else None,
        "image_digest": item.image.digest if item.image else "",
        "resource_profile_id": item.resource_profile.public_id if item.resource_profile else None,
        "dependencies": item.dependencies,
        "execution_spec": item.execution_spec,
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
        "chapters": [
            chapter_data(chapter, item)
            for chapter in item.chapters.all().prefetch_related("tasks").order_by("sort_order")
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
        attached = attached_id == item.pk
    elif item.purpose == "STARTER":
        attached_id = version.starter_asset_id
        attached = attached_id == item.pk
    elif item.purpose == "REPORT_TEMPLATE":
        attached_id = version.report_template_asset_id
        attached = attached_id == item.pk
    elif item.purpose in {"HIDDEN_SOURCE", "PUBLIC_DATA"}:
        spec = version.execution_spec if isinstance(version.execution_spec, dict) else {}
        role = "HIDDEN_SOURCE" if item.purpose == "HIDDEN_SOURCE" else "PUBLIC_DATA"
        materials = spec.get("materials", [])
        attached = any(
            row.get("asset_id") == item.public_id and row.get("role") == role
            for row in (materials if isinstance(materials, list) else [])
            if isinstance(row, dict)
        )
    else:
        spec = version.execution_spec if isinstance(version.execution_spec, dict) else {}
        attached = spec.get("tests_asset") == item.public_id
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
        "attached": attached,
        "row_version": item.row_version,
    }


def experiment_image_data(item: ExperimentImage) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "template_version_id": item.template_version.public_id,
        "source_type": item.source_type,
        "registry": item.registry,
        "repository": item.repository,
        "requested_tag": item.requested_tag,
        "resolved_digest": item.resolved_digest,
        "status": item.status,
        "scan_status": item.scan_status,
        "image_asset_id": item.image_asset.public_id if item.image_asset else None,
        "build_context_asset_id": item.build_context_asset.public_id
        if item.build_context_asset
        else None,
        "validation_detail": item.validation_detail,
        "build_args": item.build_args_masked,
        "logs": item.logs_masked,
        "error_code": item.error_code,
        "row_version": item.row_version,
    }
