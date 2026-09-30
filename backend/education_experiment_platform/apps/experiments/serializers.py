from datetime import datetime
from typing import cast

from rest_framework import serializers

from .models import (
    ExperimentTask,
    PublicationAudience,
    TaskExtensionDecision,
    TaskExtensionRequest,
    TaskPublication,
    TaskStateTransition,
)


class PrerequisiteWriteSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=("CHAPTER", "PUBLICATION"))
    chapter_id = serializers.CharField(max_length=26, required=False)
    publication_id = serializers.CharField(max_length=26, required=False)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        kind = attrs["kind"]
        required = "chapter_id" if kind == "CHAPTER" else "publication_id"
        if required not in attrs:
            raise serializers.ValidationError({required: "该先修类型必须提供引用"})
        forbidden = "publication_id" if required == "chapter_id" else "chapter_id"
        if forbidden in attrs:
            raise serializers.ValidationError({forbidden: "不能同时提供另一种先修引用"})
        return attrs


class PublicationWriteSerializer(serializers.Serializer):
    template_version_id = serializers.CharField(max_length=26)
    rubric_version_id = serializers.CharField(max_length=26)
    title = serializers.CharField(max_length=180)
    description = serializers.CharField(required=False, allow_blank=True)
    audience_mode = serializers.ChoiceField(choices=TaskPublication.AudienceMode.choices)
    late_enrollment_policy = serializers.ChoiceField(
        choices=TaskPublication.LateEnrollmentPolicy.choices, required=False
    )
    assignment_deadline = serializers.DateTimeField(required=False, allow_null=True)
    window_start = serializers.DateTimeField()
    window_end = serializers.DateTimeField()
    report_required = serializers.BooleanField(required=False)
    review_mode = serializers.ChoiceField(choices=TaskPublication.ReviewMode.choices)
    prerequisites = PrerequisiteWriteSerializer(many=True, required=False)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        window_start = cast(datetime, attrs["window_start"])
        window_end = cast(datetime, attrs["window_end"])
        if window_end <= window_start:
            raise serializers.ValidationError({"window_end": "必须晚于 window_start"})
        deadline = cast(datetime | None, attrs.get("assignment_deadline"))
        if deadline is not None and deadline > window_end:
            raise serializers.ValidationError({"assignment_deadline": "不能晚于 window_end"})
        return attrs


class PublicationPatchSerializer(serializers.Serializer):
    template_version_id = serializers.CharField(max_length=26, required=False)
    rubric_version_id = serializers.CharField(max_length=26, required=False)
    title = serializers.CharField(max_length=180, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    audience_mode = serializers.ChoiceField(
        choices=TaskPublication.AudienceMode.choices, required=False
    )
    late_enrollment_policy = serializers.ChoiceField(
        choices=TaskPublication.LateEnrollmentPolicy.choices, required=False
    )
    assignment_deadline = serializers.DateTimeField(required=False, allow_null=True)
    window_start = serializers.DateTimeField(required=False)
    window_end = serializers.DateTimeField(required=False)
    report_required = serializers.BooleanField(required=False)
    review_mode = serializers.ChoiceField(
        choices=TaskPublication.ReviewMode.choices, required=False
    )
    prerequisites = PrerequisiteWriteSerializer(many=True, required=False)


class PublicationPublishSerializer(serializers.Serializer):
    selected_enrollment_ids = serializers.ListField(
        child=serializers.CharField(max_length=26), required=False, allow_empty=True
    )


class TaskExtensionWriteSerializer(serializers.Serializer):
    requested_deadline = serializers.DateTimeField()
    reason = serializers.CharField(max_length=2000)


class TaskExtensionDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=TaskExtensionDecision.Decision.choices)
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class PublicationDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    course_id = serializers.CharField()
    template_version_id = serializers.CharField()
    rubric_version_id = serializers.CharField()
    template_spec_digest = serializers.CharField(allow_null=True)
    execution_spec = serializers.DictField()
    runtime_adapter_id = serializers.CharField(allow_null=True)
    runtime_adapter_driver = serializers.CharField()
    runtime_adapter_config_ref = serializers.CharField()
    image_id = serializers.CharField(allow_null=True)
    image_digest = serializers.CharField()
    resource_profile_id = serializers.CharField(allow_null=True)
    resource_profile_snapshot = serializers.DictField()
    title = serializers.CharField()
    description = serializers.CharField()
    audience_mode = serializers.ChoiceField(choices=TaskPublication.AudienceMode.choices)
    late_enrollment_policy = serializers.ChoiceField(
        choices=TaskPublication.LateEnrollmentPolicy.choices
    )
    window_start = serializers.DateTimeField()
    window_end = serializers.DateTimeField()
    assignment_deadline = serializers.DateTimeField(allow_null=True)
    report_required = serializers.BooleanField()
    review_mode = serializers.ChoiceField(choices=TaskPublication.ReviewMode.choices)
    status = serializers.ChoiceField(choices=TaskPublication.Status.choices)
    audience_count = serializers.IntegerField()
    prerequisites = serializers.ListField(child=serializers.DictField())
    publication_error = serializers.DictField()
    row_version = serializers.IntegerField()


class TaskDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    course_id = serializers.CharField()
    publication_id = serializers.CharField()
    enrollment_id = serializers.CharField()
    student_id = serializers.CharField()
    student_name = serializers.CharField(required=False)
    title = serializers.CharField()
    template_version_id = serializers.CharField()
    template_name = serializers.CharField()
    template_spec_digest = serializers.CharField(allow_null=True)
    runtime_type = serializers.CharField()
    execution_spec = serializers.DictField()
    runtime_adapter_id = serializers.CharField(allow_null=True)
    runtime_adapter_driver = serializers.CharField()
    runtime_adapter_config_ref = serializers.CharField()
    image_id = serializers.CharField(allow_null=True)
    image_digest = serializers.CharField()
    resource_profile_id = serializers.CharField(allow_null=True)
    resource_profile_snapshot = serializers.DictField()
    report_required = serializers.BooleanField()
    status = serializers.ChoiceField(choices=ExperimentTask.Status.choices)
    terminal_target = serializers.CharField(allow_null=True)
    progress = serializers.IntegerField()
    window_start = serializers.DateTimeField()
    window_end = serializers.DateTimeField()
    effective_deadline = serializers.DateTimeField(allow_null=True)
    allowed_actions = serializers.ListField(child=serializers.CharField())
    blockers = serializers.ListField(child=serializers.DictField())
    current_failure = serializers.DictField()
    provisioning = serializers.DictField(allow_null=True, required=False)
    row_version = serializers.IntegerField()


class TransitionDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    from_status = serializers.CharField()
    to_status = serializers.CharField()
    trigger = serializers.CharField()
    reason = serializers.CharField()
    detail = serializers.DictField()
    trace_id = serializers.CharField()
    created_at = serializers.DateTimeField()


class ExtensionDataSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    task_id = serializers.CharField()
    requested_by = serializers.CharField()
    original_deadline = serializers.DateTimeField()
    requested_deadline = serializers.DateTimeField()
    reason = serializers.CharField()
    status = serializers.ChoiceField(choices=TaskExtensionRequest.Status.choices)
    effective_deadline = serializers.DateTimeField(allow_null=True)
    row_version = serializers.IntegerField()
    decisions = serializers.ListField(child=serializers.DictField())


class DashboardDataSerializer(serializers.Serializer):
    counts = serializers.DictField()
    next_tasks = TaskDataSerializer(many=True)


class GenericResponseSerializer(serializers.Serializer):
    data = serializers.DictField()
    meta = serializers.DictField()


def publication_data(item: TaskPublication) -> dict[str, object]:
    template = item.template_version
    template_spec_digest = item.template_spec_digest
    execution_spec = dict(item.execution_spec or {})
    adapter = item.runtime_adapter
    image = item.image
    profile = item.resource_profile
    if adapter is None:
        adapter = template.runtime_adapter
        image = template.image
        profile = template.resource_profile
        template_spec_digest = template.spec_digest
        execution_spec = dict(template.execution_spec or {})
    profile_snapshot = dict(item.resource_profile_snapshot or {})
    if not profile_snapshot and profile is not None:
        profile_snapshot = {
            "public_id": profile.public_id,
            "code": profile.code,
            "runtime_type": profile.runtime_type,
            "cpu_millicores": profile.cpu_millicores,
            "memory_mb": profile.memory_mb,
            "disk_gb": profile.disk_gb,
            "network_mode": profile.network_mode,
        }
    return {
        "public_id": item.public_id,
        "course_id": item.course.public_id,
        "template_version_id": item.template_version.public_id,
        "rubric_version_id": item.rubric_version.public_id,
        "template_spec_digest": template_spec_digest,
        "execution_spec": execution_spec,
        "runtime_adapter_id": adapter.public_id if adapter else None,
        "runtime_adapter_driver": item.runtime_adapter_driver
        or (adapter.driver if adapter else ""),
        "runtime_adapter_config_ref": item.runtime_adapter_config_ref
        or (adapter.config_ref if adapter else ""),
        "image_id": image.public_id if image else None,
        "image_digest": item.image_digest or (image.digest if image else ""),
        "resource_profile_id": profile.public_id if profile else None,
        "resource_profile_snapshot": profile_snapshot,
        "title": item.title,
        "description": item.description,
        "audience_mode": item.audience_mode,
        "late_enrollment_policy": item.late_enrollment_policy,
        "window_start": item.window_start,
        "window_end": item.window_end,
        "assignment_deadline": item.assignment_deadline,
        "report_required": item.report_required,
        "review_mode": item.review_mode,
        "status": item.status,
        "audience_count": _audience_count(item),
        "publication_error": item.publication_error,
        "row_version": item.row_version,
        "prerequisites": [
            {
                "kind": pre.kind,
                "chapter_id": pre.chapter.public_id if pre.chapter_id else None,
                "publication_id": pre.prerequisite_publication.public_id
                if pre.prerequisite_publication_id
                else None,
            }
            for pre in item.prerequisites.all()
        ],
    }


def _audience_count(item: TaskPublication) -> int:
    row = item.audience.filter(audience_kind=PublicationAudience.Kind.ALL_ACTIVE).first()
    if row is not None:
        return len(row.snapshot_enrollment_ids)
    return item.audience.count()


def task_data(
    item: ExperimentTask,
    *,
    blockers: list[dict[str, object]] | None = None,
    actions: list[str] | None = None,
) -> dict[str, object]:
    template = item.template_version
    adapter = item.runtime_adapter or template.runtime_adapter
    image = item.image or template.image
    profile = item.resource_profile or template.resource_profile
    profile_snapshot = dict(item.resource_profile_snapshot or {})
    if not profile_snapshot and profile is not None:
        profile_snapshot = {
            "public_id": profile.public_id,
            "code": profile.code,
            "runtime_type": profile.runtime_type,
            "cpu_millicores": profile.cpu_millicores,
            "memory_mb": profile.memory_mb,
            "disk_gb": profile.disk_gb,
            "network_mode": profile.network_mode,
        }
    provisioning = None
    try:
        from apps.provisioning.models import ProvisioningJob

        job = (
            item.provisioning_jobs.select_related("failure_record", "compensation_task")
            .order_by("-attempt_no", "-created_at")
            .first()
        )
        if job is not None:
            provisioning = {
                "job_id": job.public_id,
                "status": job.status,
                "current_stage": job.current_stage,
                "attempt_no": job.attempt_no,
                "retryable": job.retryable,
                "failure_code": job.failure_record.error_code if job.failure_record else "",
                "compensation_status": (
                    job.compensation_task.status if job.compensation_task else None
                ),
                "events_channel": f"task:{item.public_id}",
            }
    except (AttributeError, ProvisioningJob.DoesNotExist):
        provisioning = None
    return {
        "public_id": item.public_id,
        "course_id": item.course.public_id,
        "publication_id": item.publication.public_id,
        "enrollment_id": item.enrollment.public_id,
        "student_id": item.student.public_id,
        "student_name": item.student.display_name,
        "title": item.publication.title,
        "template_version_id": item.template_version.public_id,
        "template_name": template.template.name,
        "template_spec_digest": item.template_spec_digest or template.spec_digest,
        "runtime_type": item.runtime_type,
        "execution_spec": dict(item.execution_spec or template.execution_spec or {}),
        "runtime_adapter_id": adapter.public_id if adapter else None,
        "runtime_adapter_driver": item.runtime_adapter_driver
        or (adapter.driver if adapter else ""),
        "runtime_adapter_config_ref": item.runtime_adapter_config_ref
        or (adapter.config_ref if adapter else ""),
        "image_id": image.public_id if image else None,
        "image_digest": item.image_digest or (image.digest if image else ""),
        "resource_profile_id": profile.public_id if profile else None,
        "resource_profile_snapshot": profile_snapshot,
        "report_required": item.publication.report_required,
        "status": item.status,
        "terminal_target": item.terminal_target,
        "progress": item.progress,
        "window_start": item.publication.window_start,
        "window_end": item.publication.window_end,
        "effective_deadline": item.effective_deadline,
        "allowed_actions": actions or [],
        "blockers": blockers or [],
        "current_failure": item.current_failure,
        "provisioning": provisioning,
        "row_version": item.row_version,
    }


def transition_data(item: TaskStateTransition) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "from_status": item.from_status,
        "to_status": item.to_status,
        "trigger": item.trigger,
        "reason": item.reason,
        "detail": item.detail_masked,
        "trace_id": item.trace_id,
        "created_at": item.created_at,
    }


def extension_data(item: TaskExtensionRequest) -> dict[str, object]:
    return {
        "public_id": item.public_id,
        "task_id": item.task.public_id,
        "requested_by": item.requested_by.public_id,
        "original_deadline": item.original_deadline,
        "requested_deadline": item.requested_deadline,
        "reason": item.reason,
        "status": item.status,
        "effective_deadline": item.effective_deadline,
        "row_version": item.row_version,
        "decisions": [
            {
                "public_id": decision.public_id,
                "decision": decision.decision,
                "effective_deadline": decision.effective_deadline,
                "reason": decision.reason,
                "trace_id": decision.trace_id,
                "created_at": decision.created_at,
            }
            for decision in item.decisions.all().order_by("created_at", "id")
        ],
    }
