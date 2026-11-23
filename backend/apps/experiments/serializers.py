from datetime import datetime
from typing import Any, cast

from rest_framework import serializers

from .models import (
    ExperimentTask,
    PublicationAudience,
    PublicationChapter,
    PublicationPrerequisite,
    PublicationTask,
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
    course_chapter_id = serializers.CharField(max_length=26, required=False, allow_null=True)
    template_version_id = serializers.CharField(max_length=26)
    rubric_version_id = serializers.CharField(max_length=26, required=False, allow_null=True)
    score_release_at = serializers.DateTimeField(required=False, allow_null=True)
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
        release = cast(datetime | None, attrs.get("score_release_at"))
        if release is not None and release < window_end:
            raise serializers.ValidationError({"score_release_at": "不能早于截止时间"})
        return attrs


class PublicationPatchSerializer(serializers.Serializer):
    course_chapter_id = serializers.CharField(max_length=26, required=False, allow_null=True)
    score_release_at = serializers.DateTimeField(required=False, allow_null=True)
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


class RetakePublicationWriteSerializer(serializers.Serializer):
    selected_enrollment_ids = serializers.ListField(
        child=serializers.CharField(max_length=26), allow_empty=False
    )
    window_start = serializers.DateTimeField()
    window_end = serializers.DateTimeField()

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        if cast(datetime, attrs["window_end"]) <= cast(datetime, attrs["window_start"]):
            raise serializers.ValidationError({"window_end": "必须晚于 window_start"})
        return attrs


class PublicationTaskSnapshotSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    source_task_id = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    instructions = serializers.CharField()
    task_type = serializers.CharField()
    sort_order = serializers.IntegerField()
    image_digest = serializers.CharField()
    resource_profile_snapshot = serializers.DictField()
    execution_snapshot = serializers.DictField()
    submission_policy = serializers.DictField()
    grading_policy = serializers.DictField()


class PublicationChapterSnapshotSerializer(serializers.Serializer):
    public_id = serializers.CharField()
    source_chapter_id = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    learning_objectives = serializers.ListField()
    sort_order = serializers.IntegerField()
    snapshot = serializers.DictField()
    tasks = PublicationTaskSnapshotSerializer(many=True)


class TaskExtensionWriteSerializer(serializers.Serializer):
    requested_deadline = serializers.DateTimeField()
    reason = serializers.CharField(max_length=2000)


class TaskExtensionDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=TaskExtensionDecision.Decision.choices)
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class PublicationDataSerializer(serializers.Serializer):
    course_chapter_id = serializers.CharField(allow_null=True, required=False)
    score_release_at = serializers.DateTimeField(allow_null=True)
    public_id = serializers.CharField()
    course_id = serializers.CharField()
    retake_of_publication_id = serializers.CharField(allow_null=True)
    template_version_id = serializers.CharField()
    rubric_version_id = serializers.CharField(allow_null=True)
    template_spec_digest = serializers.CharField(allow_null=True)
    template_digest = serializers.CharField(allow_null=True)
    publication_digest = serializers.CharField(allow_null=True)
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
    report_template = serializers.DictField(allow_null=True)
    review_mode = serializers.ChoiceField(choices=TaskPublication.ReviewMode.choices)
    status = serializers.ChoiceField(choices=TaskPublication.Status.choices)
    audience_count = serializers.IntegerField()
    prerequisites = serializers.ListField(child=serializers.DictField())
    publication_error = serializers.DictField()
    row_version = serializers.IntegerField()
    chapters = PublicationChapterSnapshotSerializer(many=True)


class TaskDataSerializer(serializers.Serializer):
    course_chapter_id = serializers.CharField(allow_null=True, required=False)
    assessment_available = serializers.BooleanField()
    workspace_available = serializers.BooleanField(required=False)
    public_id = serializers.CharField()
    course_id = serializers.CharField()
    publication_id = serializers.CharField()
    enrollment_id = serializers.CharField()
    student_id = serializers.CharField()
    student_name = serializers.CharField(required=False)
    score = serializers.CharField(allow_null=True, required=False)
    parts = serializers.ListField(child=serializers.DictField(), required=False)
    retake_of_task_id = serializers.CharField(allow_null=True, required=False)
    has_retake = serializers.BooleanField(required=False)
    retake_task_id = serializers.CharField(allow_null=True, required=False)
    title = serializers.CharField()
    template_version_id = serializers.CharField()
    template_name = serializers.CharField()
    template_spec_digest = serializers.CharField(allow_null=True)
    runtime_type = serializers.CharField()
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


class WeeklyStudyDataSerializer(serializers.Serializer):
    minutes_by_day = serializers.ListField(child=serializers.IntegerField(min_value=0))
    total_minutes = serializers.IntegerField()
    last_week_minutes = serializers.IntegerField()
    has_records = serializers.BooleanField()


class DashboardDataSerializer(serializers.Serializer):
    counts = serializers.DictField()
    weekly_study = WeeklyStudyDataSerializer()
    next_tasks = TaskDataSerializer(many=True)


class GenericResponseSerializer(serializers.Serializer):
    data = serializers.DictField()
    meta = serializers.DictField()


def publication_data(item: TaskPublication) -> dict[str, Any]:
    template_spec_digest = item.template_spec_digest
    adapter = item.runtime_adapter
    image = item.image
    profile = item.resource_profile
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
    allowed_actions: list[str] = []
    if item.status == TaskPublication.Status.DRAFT:
        allowed_actions = ["publish"]
    elif item.status == TaskPublication.Status.PUBLISHING:
        allowed_actions = ["withdraw"]
    elif item.status == TaskPublication.Status.PUBLISHED:
        allowed_actions = ["withdraw", "close"]
    elif item.status == TaskPublication.Status.PUBLISH_FAILED:
        allowed_actions = ["withdraw"]
    return {
        "public_id": item.public_id,
        "course_id": item.course.public_id,
        "course_chapter_id": item.course_chapter.public_id if item.course_chapter else None,
        "retake_of_publication_id": (item.retake_of.public_id if item.retake_of_id else None),
        "template_version_id": item.template_version.public_id if item.template_version_id else "",
        "direct_assessment": item.direct_assessment,
        "grades_published_at": item.grades_published_at,
        "environment_id": item.environment.public_id if item.environment_id else None,
        "rubric_version_id": item.rubric_version.public_id if item.rubric_version else None,
        "template_spec_digest": template_spec_digest,
        "template_digest": item.template_digest,
        "publication_digest": item.publication_digest,
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
        "score_release_at": item.score_release_at,
        "assignment_deadline": item.assignment_deadline,
        "report_required": item.report_required,
        "report_template": ({
            "asset_id": item.report_template_asset.public_id,
            "file_name": item.report_template_asset.original_name,
        } if item.report_template_asset_id else None),
        "review_mode": item.review_mode,
        "status": item.status,
        "audience_count": _audience_count(item),
        "publication_error": item.publication_error,
        "row_version": item.row_version,
        "allowed_actions": allowed_actions,
        "prerequisites": [
            {
                "kind": pre.kind,
                "chapter_id": pre.chapter.public_id if pre.chapter_id else None,
                "publication_id": pre.prerequisite_publication.public_id
                if pre.prerequisite_publication_id
                else None,
            }
            for pre in _publication_prerequisites(item)
        ],
        "chapters": publication_chapter_data(item),
    }


def publication_chapter_data(item: TaskPublication) -> list[dict[str, object]]:
    chapters = _publication_chapters(item)
    return [
        {
            "public_id": chapter.public_id,
            "source_chapter_id": chapter.source_chapter_id,
            "title": chapter.title,
            "description": chapter.description,
            "learning_objectives": chapter.learning_objectives,
            "sort_order": chapter.sort_order,
            "snapshot": chapter.snapshot,
            "tasks": [
                {
                    "public_id": task.public_id,
                    "source_task_id": task.source_task_id,
                    "title": task.title,
                    "description": task.description,
                    "instructions": task.instructions,
                    "task_type": task.task_type,
                    "sort_order": task.sort_order,
                    "image_digest": task.image_digest,
                    "resource_profile_snapshot": task.resource_profile_snapshot,
                    "execution_snapshot": task.execution_snapshot,
                    "submission_policy": task.submission_policy,
                    "grading_policy": task.grading_policy,
                }
                for task in _publication_tasks(chapter)
            ],
        }
        for chapter in chapters
    ]


def _audience_count(item: TaskPublication) -> int:
    audience = _publication_audience(item)
    all_active = next(
        (row for row in audience if row.audience_kind == PublicationAudience.Kind.ALL_ACTIVE),
        None,
    )
    if all_active is not None:
        return len(all_active.snapshot_enrollment_ids)
    return len(audience)


def _publication_prerequisites(item: TaskPublication) -> list[PublicationPrerequisite]:
    values: list[PublicationPrerequisite] | None = getattr(item, "_response_prerequisites", None)
    if values is None:
        values = list(
            item.prerequisites.select_related("chapter", "prerequisite_publication").all()
        )
    return list(values)


def _publication_audience(item: TaskPublication) -> list[PublicationAudience]:
    values = getattr(item, "_response_audience", None)
    if values is None:
        values = list(item.audience.all())
    return list(values)


def _publication_chapters(item: TaskPublication) -> list[PublicationChapter]:
    values: list[PublicationChapter] | None = getattr(item, "_response_chapters", None)
    if values is None:
        values = list(item.chapter_snapshots.all())
    return sorted(values, key=lambda chapter: (chapter.sort_order, chapter.id))


def _publication_tasks(chapter: PublicationChapter) -> list[PublicationTask]:
    values: list[PublicationTask] | None = getattr(chapter, "_response_tasks", None)
    if values is None:
        values = list(chapter.task_snapshots.all())
    return sorted(values, key=lambda task: (task.sort_order, task.id))


def task_data(
    item: ExperimentTask,
    *,
    blockers: list[dict[str, object]] | None = None,
    actions: list[str] | None = None,
) -> dict[str, object]:
    from .assessment_parts import can_start_session

    template = item.template_version
    adapter = item.runtime_adapter
    image = item.image
    profile = item.resource_profile
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
        "workspace_available": can_start_session(item),
        "assessment_available": PublicationTask.objects.filter(
            publication_chapter__publication_id=item.publication_id,
            task_type__in=("SINGLE_CHOICE", "MULTIPLE_CHOICE", "PROGRAMMING"),
        ).exists() or (item.publication.direct_assessment and item.publication.report_required),
        "public_id": item.public_id,
        "course_id": item.course.public_id,
        "course_chapter_id": item.publication.course_chapter.public_id
        if item.publication.course_chapter
        else None,
        "publication_id": item.publication.public_id,
        "enrollment_id": item.enrollment.public_id,
        "student_id": item.student.public_id,
        "student_name": item.student.display_name,
        "title": item.publication.title,
        "template_version_id": template.public_id if template else "",
        "template_name": template.template.name if template else "",
        "template_spec_digest": item.template_spec_digest
        or (template.spec_digest if template else ""),
        "runtime_type": item.runtime_type,
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
