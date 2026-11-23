import hashlib
import json
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone

from apps.accounts.models import User
from apps.core.audit import append_audit, hash_client_ip
from apps.core.concurrency import compare_and_swap
from apps.core.errors import ResourceNotFound
from apps.core.models import CompensationTask
from apps.core.outbox import append_outbox_event, enqueue_relay_after_commit
from apps.courses.content_services import prerequisite_status
from apps.courses.models import Chapter, CourseStaffGrant, Enrollment
from apps.courses.ports import Blocker
from apps.courses.selectors import require_course_capability
from apps.governance.models import ResourceProfile
from apps.labtemplates.models import ExperimentImage, TemplateVersion
from apps.reviews.models import RubricVersion

from . import events
from .errors import (
    PublicationStateConflict,
    PublicationValidationError,
    TaskExtensionConflict,
    TaskStateConflict,
)
from .grades import task_grades
from .metrics import (
    PUBLICATION_ASSIGNMENT_DURATION,
    PUBLICATION_DECISIONS_TOTAL,
    TASK_ASSIGNMENTS_TOTAL,
    TASK_TRANSITIONS_TOTAL,
)
from .models import (
    ExperimentRetakeLink,
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
from .ports import request_task_terminal

TASK_TRANSITIONS: dict[str, set[str]] = {
    "ASSIGNED": {"IN_PROGRESS", "CANCELLED", "EXPIRED", "ARCHIVING"},
    "IN_PROGRESS": {"REPORT_DRAFT", "UNDER_REVIEW", "FAILED", "ARCHIVING"},
    "REPORT_DRAFT": {"IN_PROGRESS", "UNDER_REVIEW", "FAILED", "ARCHIVING"},
    "UNDER_REVIEW": {"APPROVED", "REPORT_DRAFT", "FAILED", "ARCHIVING"},
    "APPROVED": {"REPORT_DRAFT", "ARCHIVING"},
    "ARCHIVING": {"COMPLETED", "CANCELLED", "EXPIRED", "FAILED"},
    "FAILED": set(),
    "COMPLETED": set(),
    "CANCELLED": set(),
    "EXPIRED": set(),
}


def _trace(context: Any) -> str:
    return str(getattr(context, "trace_id", ""))


def _actor_ref(actor: User | None, context: Any) -> str:
    return actor.public_id if actor is not None else str(getattr(context, "actor_ref", "worker"))


def _audit(
    *,
    context: Any,
    actor: User | None,
    action: str,
    target_type: str,
    target_ref: str,
    course_ref: str,
    before: Any = None,
    after: Any = None,
    result: str = "SUCCEEDED",
    error_code: str = "",
) -> None:
    append_audit(
        actor_ref=_actor_ref(actor, context),
        actor_portal=str(getattr(context, "portal", "")),
        actor_context={},
        action=action,
        target_type=target_type,
        target_ref=target_ref,
        course_ref=course_ref,
        before=before,
        after=after,
        result=result,
        error_code=error_code,
        client_ip_hash=hash_client_ip(
            str(getattr(context, "client_ip", "")), salt=settings.AUDIT_IP_HASH_SALT
        ),
        user_agent_summary=str(getattr(context, "user_agent", "")),
        trace_id=_trace(context),
    )


def _emit(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_ref: str,
    payload: dict[str, Any],
    context: Any,
) -> None:
    append_outbox_event(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_ref=aggregate_ref,
        payload=payload,
        trace_id=_trace(context),
    )
    enqueue_relay_after_commit(trace_id=_trace(context))


def _digest(values: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(values)).encode()).hexdigest()


def _json_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _resource_snapshot(
    profile: ResourceProfile | None, *, runtime_type: str, source_id: str
) -> dict[str, Any]:
    if profile is None:
        raise PublicationValidationError(detail={"resource_profile_id": {source_id: "required"}})
    request_limit_valid = (
        profile.cpu_request_millicores > 0
        and profile.cpu_request_millicores <= profile.cpu_limit_millicores
        and profile.memory_request_mb > 0
        and profile.memory_request_mb <= profile.memory_limit_mb
    )
    if profile.status != ResourceProfile.Status.ACTIVE or profile.runtime_type != runtime_type:
        raise PublicationValidationError(
            detail={"resource_profile_id": {source_id: "active_runtime_profile_required"}}
        )
    if not request_limit_valid:
        raise PublicationValidationError(
            detail={"resource_profile_id": {source_id: "invalid_request_limit"}}
        )
    return {
        "public_id": profile.public_id,
        "code": profile.code,
        "runtime_type": profile.runtime_type,
        "cpu_millicores": profile.cpu_millicores,
        "memory_mb": profile.memory_mb,
        "cpu_request_millicores": profile.cpu_request_millicores,
        "cpu_limit_millicores": profile.cpu_limit_millicores,
        "memory_request_mb": profile.memory_request_mb,
        "memory_limit_mb": profile.memory_limit_mb,
        "disk_gb": profile.disk_gb,
        "network_mode": profile.network_mode,
        "cost_minor_per_hour": profile.cost_minor_per_hour,
        "currency_code": profile.currency_code,
    }


def _ready_image_snapshot(template: TemplateVersion) -> dict[str, Any]:
    image = (
        ExperimentImage.objects
        .filter(
            template_version=template,
            status=ExperimentImage.Status.READY,
        )
        .select_related("image_asset")
        .order_by("-created_at", "-id")
        .first()
    )
    if image is None or image.image_asset is None:
        raise PublicationValidationError(detail={"image": "READY_REQUIRED"})
    asset = image.image_asset
    digest = image.resolved_digest or asset.digest
    if not _IMAGE_DIGEST.fullmatch(digest) or not asset.is_ready:
        raise PublicationValidationError(detail={"image": "READY_DIGEST_REQUIRED"})
    return {
        "experiment_image": image,
        "image": asset,
        "registry": image.registry or asset.registry,
        "repository": image.repository or asset.repository,
        "digest": digest,
    }


def _content_snapshot(template: TemplateVersion) -> dict[str, Any]:
    from apps.labtemplates.questions import assessment_snapshot
    from apps.labtemplates.services import _digest

    assessment = assessment_snapshot(template, include_case_metadata=True)
    if assessment is not None:
        case_metadata = {
            question["id"]: question.pop("case_metadata", {})
            for question in assessment["questions"]
        }
        if _digest(assessment) != template.spec_digest:
            raise PublicationValidationError(detail={"template": "precheck_digest_mismatch"})
        has_programming = any(q["task_type"] == "PROGRAMMING" for q in assessment["questions"])
        image = (
            _ready_image_snapshot(template)
            if has_programming
            else {
                "image": None,
                "registry": "",
                "repository": "",
                "digest": "",
            }
        )
        profile = (
            _resource_snapshot(
                template.resource_profile,
                runtime_type=template.runtime_type,
                source_id=template.public_id,
            )
            if has_programming
            else {}
        )
        return {
            "chapters": [
                {
                    "source_chapter_id": chapter["id"],
                    "title": chapter["title"],
                    "description": chapter["description"],
                    "learning_objectives": chapter["learning_objectives"],
                    "sort_order": chapter["sort_order"],
                    "resource_profile_snapshot": {},
                    "tasks": [
                        {
                            "source_task_id": question["id"],
                            "title": question["title"],
                            "description": question["description"],
                            "instructions": question["instructions"],
                            "task_type": question["task_type"],
                            "sort_order": question["sort_order"],
                            "image_digest": (
                                image["digest"] if question["task_type"] == "PROGRAMMING" else ""
                            ),
                            "resource_profile_snapshot": profile,
                            "execution_snapshot": {
                                "tests_digest": question.get("tests_digest", ""),
                                **case_metadata[question["id"]],
                            },
                            "submission_policy": {},
                            "grading_policy": {},
                            "question_spec": question["question_spec"],
                            "marking_spec": question["marking_spec"],
                            "max_score": question["max_score"],
                        }
                        for question in assessment["questions"]
                        if question["chapter_id"] == chapter["id"]
                    ],
                }
                for chapter in assessment["chapters"]
            ],
            "template_digest": _json_digest(assessment),
            "template_spec_digest": template.spec_digest,
            "runtime_adapter": template.runtime_adapter if has_programming else None,
            "runtime_adapter_driver": template.runtime_adapter.driver if has_programming else "",
            "runtime_adapter_config_ref": (
                template.runtime_adapter.config_ref if has_programming else ""
            ),
            "resource_profile": profile,
            "image": image,
        }
    raise PublicationValidationError(detail={"questions": "assessment_questions_required"})


@transaction.atomic
def precheck_template_version(
    *,
    template_version: TemplateVersion | None = None,
    template_version_id: str | None = None,
) -> dict[str, Any]:
    lookup = {"public_id": template_version_id} if template_version_id else {}
    if template_version is not None:
        lookup = {"pk": template_version.pk}
    if not lookup:
        raise PublicationValidationError(detail={"template_version_id": "required"})
    try:
        locked_template = (
            TemplateVersion.objects
            .select_for_update()
            .select_related("template", "runtime_adapter", "resource_profile")
            .get(**lookup)
        )
    except TemplateVersion.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if (
        locked_template.status != TemplateVersion.Status.PUBLISHED
        or not locked_template.spec_digest
    ):
        raise PublicationValidationError(detail={"template_version_status": locked_template.status})
    return _content_snapshot(locked_template)


def publish_template_version(*, template_version: TemplateVersion) -> dict[str, Any]:
    return precheck_template_version(template_version=template_version)


def _runtime_snapshot(
    template: TemplateVersion, content: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Capture mutable runtime inputs when a publication is frozen."""

    if template.runtime_adapter_id is None or (
        content is not None and content["runtime_adapter"] is None
    ):
        return {
            "template_spec_digest": template.spec_digest,
            "runtime_adapter": None,
            "runtime_adapter_driver": "",
            "runtime_adapter_config_ref": "",
            "image": None,
            "image_registry": "",
            "image_repository": "",
            "image_digest": "",
            "resource_profile": None,
            "resource_profile_snapshot": {},
        }

    adapter = template.runtime_adapter
    image = content["image"]["image"] if content is not None else template.image
    profile = template.resource_profile
    image_registry = content["image"]["registry"] if content is not None else image.registry
    image_repository = content["image"]["repository"] if content is not None else image.repository
    image_digest = content["image"]["digest"] if content is not None else image.digest
    return {
        "template_spec_digest": (
            content["template_spec_digest"] if content is not None else template.spec_digest
        ),
        "runtime_adapter": adapter,
        "runtime_adapter_driver": (
            content["runtime_adapter_driver"] if content is not None else adapter.driver
        ),
        "runtime_adapter_config_ref": (
            content["runtime_adapter_config_ref"] if content is not None else adapter.config_ref
        ),
        "image": image,
        "image_registry": image_registry,
        "image_repository": image_repository,
        "image_digest": image_digest,
        "resource_profile": profile,
        "resource_profile_snapshot": (
            dict(content["resource_profile"])
            if content is not None
            else {
                "public_id": profile.public_id,
                "code": profile.code,
                "runtime_type": profile.runtime_type,
                "cpu_millicores": profile.cpu_millicores,
                "memory_mb": profile.memory_mb,
                "cpu_request_millicores": profile.cpu_request_millicores or profile.cpu_millicores,
                "cpu_limit_millicores": profile.cpu_limit_millicores or profile.cpu_millicores,
                "memory_request_mb": profile.memory_request_mb or profile.memory_mb,
                "memory_limit_mb": profile.memory_limit_mb or profile.memory_mb,
                "disk_gb": profile.disk_gb,
                "network_mode": profile.network_mode,
            }
        ),
    }


def _course_prerequisite_blockers(*, course: Any, student: User) -> list[dict[str, Any]]:
    return [
        {
            "type": "COURSE_PREREQUISITE",
            "course_id": item.get("prerequisite_course_id", ""),
            "status": item.get("status", "NOT_EVALUABLE"),
            "reason": item.get("reason", "COMPLETION_FACT_UNAVAILABLE"),
        }
        for item in prerequisite_status(course=course, student=student)
        if item.get("status") != "SATISFIED"
    ]


def prerequisite_blockers_for_publication(
    *, publication: TaskPublication, student: User
) -> list[dict[str, Any]]:
    blockers = _course_prerequisite_blockers(course=publication.course, student=student)
    for prerequisite in publication.prerequisites.select_related(
        "chapter", "prerequisite_publication"
    ):
        if prerequisite.kind == PublicationPrerequisite.Kind.CHAPTER:
            blockers.append({
                "type": "CHAPTER_PREREQUISITE",
                "chapter_id": prerequisite.chapter.public_id if prerequisite.chapter else "",
                "status": "NOT_EVALUABLE",
                "reason": "CHAPTER_COMPLETION_FACT_UNAVAILABLE",
            })
            continue
        required = prerequisite.prerequisite_publication
        if required is None:
            continue
        if not ExperimentTask.objects.filter(
            publication=required,
            student=student,
            status=ExperimentTask.Status.COMPLETED,
        ).exists():
            blockers.append({
                "type": "PUBLICATION_PREREQUISITE",
                "publication_id": required.public_id,
                "status": "NOT_COMPLETED",
                "reason": "PREREQUISITE_TASK_NOT_COMPLETED",
            })
    return blockers


def _validate_prerequisite_spec(
    *, publication: TaskPublication, spec: dict[str, Any], actor: User, context: Any
) -> PublicationPrerequisite:
    kind = str(spec.get("kind", ""))
    if kind == PublicationPrerequisite.Kind.CHAPTER:
        try:
            chapter = Chapter.objects.get(
                public_id=str(spec["chapter_id"]), course=publication.course
            )
        except Chapter.DoesNotExist as exc:
            raise PublicationValidationError(detail={"chapter_id": spec.get("chapter_id")}) from exc
        return PublicationPrerequisite.objects.create(
            publication=publication,
            kind=kind,
            chapter=chapter,
            created_by=actor,
            trace_id=_trace(context),
        )
    if kind == PublicationPrerequisite.Kind.PUBLICATION:
        try:
            required = TaskPublication.objects.get(
                public_id=str(spec["publication_id"]), course=publication.course
            )
        except TaskPublication.DoesNotExist as exc:
            raise PublicationValidationError(
                detail={"publication_id": spec.get("publication_id")}
            ) from exc
        if required.pk == publication.pk:
            raise PublicationValidationError(detail={"reason": "SELF_PREREQUISITE"})
        frontier = [required.pk]
        visited: set[int] = set()
        cycle = False
        while frontier:
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            if current == publication.pk:
                cycle = True
                break
            frontier.extend(
                PublicationPrerequisite.objects.filter(
                    publication_id=current,
                    kind=PublicationPrerequisite.Kind.PUBLICATION,
                ).values_list("prerequisite_publication_id", flat=True)
            )
        if cycle:
            raise PublicationValidationError(detail={"reason": "PREREQUISITE_CYCLE"})
        return PublicationPrerequisite.objects.create(
            publication=publication,
            kind=kind,
            prerequisite_publication=required,
            created_by=actor,
            trace_id=_trace(context),
        )
    raise PublicationValidationError(detail={"kind": kind})


def _validate_dependencies(*, publication: TaskPublication) -> None:
    if publication.course.status != publication.course.Status.PUBLISHED:
        raise PublicationValidationError(detail={"course_status": publication.course.status})
    if publication.direct_assessment:
        return
    template = publication.template_version
    if template.template.course_id != publication.course_id:
        raise PublicationValidationError(detail={"template_version_id": template.public_id})
    if template.status != TemplateVersion.Status.PUBLISHED or not template.spec_digest:
        raise PublicationValidationError(detail={"template_version_status": template.status})
    rubric = publication.rubric_version
    if rubric is None:
        if publication.report_required and not (
            publication.report_template_asset_id or template.report_template_asset_id
        ):
            raise PublicationValidationError(detail={"rubric_version_id": "report_rubric_required"})
        return
    if rubric.rubric.course_id != publication.course_id:
        raise PublicationValidationError(detail={"rubric_version_id": rubric.public_id})
    if rubric.status != RubricVersion.Status.PUBLISHED:
        raise PublicationValidationError(detail={"rubric_version_status": rubric.status})


@transaction.atomic
def create_publication(
    *, course_id: str, actor: User, data: dict[str, Any], context: Any
) -> TaskPublication:
    from apps.courses.models import Course

    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
    except Course.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    require_course_capability(
        course=course, actor=actor, capability=CourseStaffGrant.Capability.PUBLISH_EXPERIMENT
    )
    try:
        template = TemplateVersion.objects.select_related("template").get(
            public_id=data["template_version_id"]
        )
        rubric = (
            RubricVersion.objects.select_related("rubric").get(public_id=data["rubric_version_id"])
            if data.get("rubric_version_id")
            else None
        )
    except (TemplateVersion.DoesNotExist, RubricVersion.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    if template.template.course_id != course.pk or (
        rubric is not None and rubric.rubric.course_id != course.pk
    ):
        raise PublicationValidationError(detail={"reason": "CROSS_COURSE_REFERENCE"})
    from apps.courses.models import Chapter

    chapter = None
    if data.get("course_chapter_id"):
        try:
            chapter = Chapter.objects.get(public_id=data["course_chapter_id"], course=course)
        except Chapter.DoesNotExist as exc:
            raise PublicationValidationError(
                detail={"course_chapter_id": "cross_course_or_missing"}
            ) from exc
    publication = TaskPublication.objects.create(
        course=course,
        course_chapter=chapter,
        template_version=template,
        rubric_version=rubric,
        title=str(data["title"]).strip(),
        description=str(data.get("description", "")).strip(),
        audience_mode=data["audience_mode"],
        late_enrollment_policy=data.get(
            "late_enrollment_policy", TaskPublication.LateEnrollmentPolicy.ASSIGN_UNTIL_DEADLINE
        ),
        window_start=data["window_start"],
        window_end=data["window_end"],
        score_release_at=data.get("score_release_at"),
        assignment_deadline=data.get("assignment_deadline"),
        report_required=bool(data.get("report_required", True)),
        review_mode=data["review_mode"],
    )
    for spec in data.get("prerequisites", []):
        _validate_prerequisite_spec(
            publication=publication, spec=spec, actor=actor, context=context
        )
    _audit(
        context=context,
        actor=actor,
        action="experiment.publication.create",
        target_type="task_publication",
        target_ref=publication.public_id,
        course_ref=course.public_id,
        after={"status": publication.status},
    )
    return publication


@transaction.atomic
def update_publication(
    *,
    course_id: str,
    publication_id: str,
    actor: User,
    expected_version: int,
    data: dict[str, Any],
    context: Any,
) -> TaskPublication:
    from apps.courses.models import Course

    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
        publication = (
            TaskPublication.objects
            .select_for_update()
            .select_related("template_version__template", "rubric_version__rubric", "course")
            .get(public_id=publication_id, course=course)
        )
    except (Course.DoesNotExist, TaskPublication.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    require_course_capability(
        course=course, actor=actor, capability=CourseStaffGrant.Capability.PUBLISH_EXPERIMENT
    )
    if publication.status != TaskPublication.Status.DRAFT:
        raise PublicationStateConflict(detail={"status": publication.status})
    if publication.direct_assessment:
        raise PublicationValidationError(detail={"draft": "use_experiment_design"})
    changes = {
        key: value
        for key, value in data.items()
        if key
        in {
            "title",
            "description",
            "audience_mode",
            "late_enrollment_policy",
            "window_start",
            "window_end",
            "score_release_at",
            "assignment_deadline",
            "report_required",
            "review_mode",
        }
    }
    if "course_chapter_id" in data:
        from apps.courses.models import Chapter

        try:
            changes["course_chapter"] = (
                Chapter.objects.get(
                    public_id=data["course_chapter_id"],
                    course=course,
                )
                if data["course_chapter_id"]
                else None
            )
        except Chapter.DoesNotExist as exc:
            raise PublicationValidationError(
                detail={"course_chapter_id": "cross_course_or_missing"}
            ) from exc
    if "template_version_id" in data:
        try:
            changes["template_version"] = TemplateVersion.objects.get(
                public_id=data["template_version_id"], template__course=course
            )
        except TemplateVersion.DoesNotExist as exc:
            raise PublicationValidationError(
                detail={"template_version_id": data["template_version_id"]}
            ) from exc
    if "rubric_version_id" in data:
        try:
            changes["rubric_version"] = RubricVersion.objects.get(
                public_id=data["rubric_version_id"], rubric__course=course
            )
        except RubricVersion.DoesNotExist as exc:
            raise PublicationValidationError(
                detail={"rubric_version_id": data["rubric_version_id"]}
            ) from exc
    candidate_start = changes.get("window_start", publication.window_start)
    candidate_end = changes.get("window_end", publication.window_end)
    candidate_deadline = changes.get("assignment_deadline", publication.assignment_deadline)
    release = changes.get("score_release_at", publication.score_release_at)
    if release is not None and release < candidate_end:
        raise PublicationValidationError(detail={"score_release_at": "before_deadline"})
    if candidate_end <= candidate_start:
        raise PublicationValidationError(detail={"reason": "INVALID_WINDOW"})
    if candidate_deadline is not None and candidate_deadline > candidate_end:
        raise PublicationValidationError(detail={"reason": "INVALID_ASSIGNMENT_DEADLINE"})
    changes = {
        key: (value.strip() if isinstance(value, str) else value) for key, value in changes.items()
    }
    changed = compare_and_swap(
        TaskPublication, pk=publication.pk, expected_version=expected_version, changes=changes
    )
    for spec in data.get("prerequisites", []):
        _validate_prerequisite_spec(publication=changed, spec=spec, actor=actor, context=context)
    return TaskPublication.objects.select_related(
        "course", "template_version__template", "rubric_version__rubric"
    ).get(pk=changed.pk)


def _audience_enrollments(
    *, publication: TaskPublication, selected_ids: list[str]
) -> list[Enrollment]:
    if publication.audience_mode == TaskPublication.AudienceMode.ALL_ACTIVE:
        if selected_ids:
            raise PublicationValidationError(
                detail={"selected_enrollment_ids": "全部在读学生模式不能指定单独受众"}
            )
        return list(
            Enrollment.objects
            .filter(course=publication.course, status=Enrollment.Status.ACTIVE)
            .select_related("student")
            .order_by("id")
        )
    if not selected_ids:
        raise PublicationValidationError(
            detail={"selected_enrollment_ids": "指定学生模式至少选择一名在读学生"}
        )
    if len(selected_ids) != len(set(selected_ids)):
        raise PublicationValidationError(
            detail={"selected_enrollment_ids": "指定学生列表不能包含重复记录"}
        )
    enrollments = list(
        Enrollment.objects
        .filter(
            course=publication.course, status=Enrollment.Status.ACTIVE, public_id__in=selected_ids
        )
        .select_related("student")
        .order_by("id")
    )
    if len(enrollments) != len(set(selected_ids)):
        raise PublicationValidationError(
            detail={"selected_enrollment_ids": "指定学生包含不存在、非在读或其他课程的选课记录"}
        )
    return enrollments


def _freeze_audience(*, publication: TaskPublication, selected_ids: list[str]) -> list[Enrollment]:
    enrollments = _audience_enrollments(publication=publication, selected_ids=selected_ids)
    ids = [item.public_id for item in enrollments]
    digest = _digest(ids)
    if publication.audience_mode == TaskPublication.AudienceMode.ALL_ACTIVE:
        PublicationAudience.objects.create(
            publication=publication,
            audience_kind=PublicationAudience.Kind.ALL_ACTIVE,
            snapshot_digest=digest,
            snapshot_enrollment_ids=ids,
        )
    else:
        for enrollment in enrollments:
            PublicationAudience.objects.create(
                publication=publication,
                enrollment=enrollment,
                audience_kind=PublicationAudience.Kind.SELECTED,
                snapshot_digest=digest,
            )
    return enrollments


def _transition_row(
    *,
    task: ExperimentTask,
    from_status: str,
    to_status: str,
    actor: User | None,
    trigger: str,
    reason: str,
    context: Any,
    detail: dict[str, Any] | None = None,
) -> None:
    TaskStateTransition.objects.create(
        task=task,
        from_status=from_status,
        to_status=to_status,
        trigger=trigger,
        actor=actor,
        reason=reason[:255],
        detail_masked=detail or {},
        trace_id=_trace(context),
    )
    TASK_TRANSITIONS_TOTAL.labels(from_status=from_status or "NONE", to_status=to_status).inc()
    _emit(
        event_type=events.TASK_STATUS_CHANGED,
        aggregate_type="experiment_task",
        aggregate_ref=task.public_id,
        payload={"task_id": task.public_id, "from_status": from_status, "to_status": to_status},
        context=context,
    )


def _link_retake_task(
    *, publication: TaskPublication, task: ExperimentTask, enrollment: Enrollment
) -> None:
    if publication.retake_of_id is None:
        return
    source_task = (
        ExperimentTask.objects
        .select_for_update()
        .filter(publication_id=publication.retake_of_id, student=enrollment.student)
        .first()
    )
    if source_task is None:
        raise PublicationValidationError(detail={"retake_source_task": "原实验任务不存在"})
    try:
        link = ExperimentRetakeLink.objects.select_for_update().get(
            source_task=source_task, retake_publication=publication
        )
    except ExperimentRetakeLink.DoesNotExist as exc:
        raise PublicationValidationError(detail={"retake_link": "补做任务关联记录不存在"}) from exc
    if link.retake_task_id == task.pk:
        return
    if link.retake_task_id is not None:
        raise PublicationValidationError(detail={"retake_link": "补做任务已关联其他任务"})
    compare_and_swap(
        ExperimentRetakeLink,
        pk=link.pk,
        expected_version=link.row_version,
        changes={"retake_task": task},
    )


def _create_task(
    *, publication: TaskPublication, enrollment: Enrollment, actor: User | None, context: Any
) -> ExperimentTask:
    template = publication.template_version
    snapshot = {
        "template_spec_digest": publication.template_spec_digest,
        "runtime_adapter": publication.runtime_adapter,
        "runtime_adapter_driver": publication.runtime_adapter_driver,
        "runtime_adapter_config_ref": publication.runtime_adapter_config_ref,
        "image": publication.image,
        "image_registry": publication.image_registry,
        "image_repository": publication.image_repository,
        "image_digest": publication.image_digest,
        "resource_profile": publication.resource_profile,
        "resource_profile_snapshot": dict(publication.resource_profile_snapshot or {}),
    }
    try:
        task = ExperimentTask.objects.create(
            course=publication.course,
            publication=publication,
            enrollment=enrollment,
            student=enrollment.student,
            template_version=template,
            runtime_type=template.runtime_type if template else "CONTAINER",
            template_spec_digest=snapshot["template_spec_digest"],
            runtime_adapter=snapshot["runtime_adapter"],
            runtime_adapter_driver=snapshot["runtime_adapter_driver"],
            runtime_adapter_config_ref=snapshot["runtime_adapter_config_ref"],
            image=snapshot["image"],
            image_registry=snapshot["image_registry"],
            image_repository=snapshot["image_repository"],
            image_digest=snapshot["image_digest"],
            resource_profile=snapshot["resource_profile"],
            resource_profile_snapshot=snapshot["resource_profile_snapshot"],
            effective_deadline=publication.window_end,
        )
    except IntegrityError:
        task = ExperimentTask.objects.get(publication=publication, student=enrollment.student)
        TASK_ASSIGNMENTS_TOTAL.labels(result="duplicate").inc()
        _link_retake_task(publication=publication, task=task, enrollment=enrollment)
        return task
    _link_retake_task(publication=publication, task=task, enrollment=enrollment)
    _transition_row(
        task=task,
        from_status="",
        to_status=ExperimentTask.Status.ASSIGNED,
        actor=actor,
        trigger="ASSIGN",
        reason="publication audience assignment",
        context=context,
    )
    _emit(
        event_type=events.TASK_ASSIGNED,
        aggregate_type="experiment_task",
        aggregate_ref=task.public_id,
        payload={
            "task_id": task.public_id,
            "publication_id": publication.public_id,
            "student_id": enrollment.student.public_id,
            "course_id": publication.course.public_id,
            "course_name": publication.course.title,
            "experiment_title": publication.title,
            "deadline": publication.window_end.isoformat(),
        },
        context=context,
    )
    TASK_ASSIGNMENTS_TOTAL.labels(result="created").inc()
    return task


def _copy_publication_snapshots(*, publication: TaskPublication, content: dict[str, Any]) -> None:
    for chapter_snapshot in content["chapters"]:
        chapter = PublicationChapter.objects.create(
            publication=publication,
            source_chapter_id=chapter_snapshot["source_chapter_id"],
            title=chapter_snapshot["title"],
            description=chapter_snapshot["description"],
            learning_objectives=chapter_snapshot["learning_objectives"],
            sort_order=chapter_snapshot["sort_order"],
            snapshot={
                "resource_profile_snapshot": chapter_snapshot["resource_profile_snapshot"],
            },
        )
        PublicationTask.objects.bulk_create([
            PublicationTask(
                publication_chapter=chapter,
                source_task_id=task_snapshot["source_task_id"],
                title=task_snapshot["title"],
                description=task_snapshot["description"],
                instructions=task_snapshot["instructions"],
                task_type=task_snapshot["task_type"],
                question_spec=task_snapshot["question_spec"],
                marking_spec=task_snapshot["marking_spec"],
                max_score=task_snapshot["max_score"],
                sort_order=task_snapshot["sort_order"],
                image_digest=task_snapshot["image_digest"],
                resource_profile_snapshot=task_snapshot["resource_profile_snapshot"],
                execution_snapshot=task_snapshot["execution_snapshot"],
                submission_policy=task_snapshot["submission_policy"],
                grading_policy=task_snapshot["grading_policy"],
            )
            for task_snapshot in chapter_snapshot["tasks"]
        ])


@transaction.atomic
def publish_publication(
    *,
    course_id: str,
    publication_id: str,
    actor: User,
    expected_version: int,
    selected_ids: list[str],
    context: Any,
) -> tuple[TaskPublication, int]:
    from apps.courses.models import Course

    started = timezone.now()
    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
        publication = (
            TaskPublication.objects
            .select_for_update()
            .select_related("course", "rubric_version__rubric", "retake_of")
            .get(public_id=publication_id, course=course)
        )
    except (Course.DoesNotExist, TaskPublication.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    require_course_capability(
        course=course, actor=actor, capability=CourseStaffGrant.Capability.PUBLISH_EXPERIMENT
    )
    if publication.status != TaskPublication.Status.DRAFT:
        raise PublicationStateConflict(detail={"status": publication.status})
    if publication.direct_assessment:
        from .design import direct_content
        from .models import TeachingEnvironment

        if publication.environment_id:
            publication.environment = TeachingEnvironment.objects.select_for_update().get(
                pk=publication.environment_id,
            )
        _validate_dependencies(publication=publication)
        content, runtime_snapshot = direct_content(publication)
    else:
        template = TemplateVersion.objects.select_for_update().get(
            pk=publication.template_version_id,
        )
        publication.template_version = template
        _validate_dependencies(publication=publication)
        content = publish_template_version(template_version=template)
        runtime_snapshot = _runtime_snapshot(template, content)
    enrollments = _freeze_audience(publication=publication, selected_ids=selected_ids)
    publication_digest = _json_digest({
        "course_id": course.public_id,
        "retake_of_publication_id": (
            publication.retake_of.public_id if publication.retake_of_id else None
        ),
        "template_digest": content["template_digest"],
        "audience_mode": publication.audience_mode,
        "audience_enrollment_ids": sorted(item.public_id for item in enrollments),
        "title": publication.title,
        "description": publication.description,
        "window_start": publication.window_start.isoformat(),
        "window_end": publication.window_end.isoformat(),
        "assignment_deadline": (
            publication.assignment_deadline.isoformat()
            if publication.assignment_deadline is not None
            else None
        ),
        "report_required": publication.report_required,
        "report_template": publication.report_template_asset.digest_sha256
        if publication.report_template_asset_id else None,
        "review_mode": publication.review_mode,
    })
    now = timezone.now()
    async_assignment = len(enrollments) >= int(getattr(settings, "PUBLICATION_SYNC_LIMIT", 100))
    next_status = (
        TaskPublication.Status.PUBLISHING if async_assignment else TaskPublication.Status.PUBLISHED
    )
    changes: dict[str, Any] = {
        "status": next_status,
        "published_by": actor,
        "template_digest": content["template_digest"],
        "publication_digest": publication_digest,
        **runtime_snapshot,
    }
    if not async_assignment:
        changes["published_at"] = now
    published = compare_and_swap(
        TaskPublication, pk=publication.pk, expected_version=expected_version, changes=changes
    )
    _copy_publication_snapshots(publication=published, content=content)
    if async_assignment:
        from .tasks import assign_publication_tasks

        transaction.on_commit(
            lambda: assign_publication_tasks.delay(published.public_id, _trace(context))
        )
    else:
        for enrollment in enrollments:
            _create_task(publication=published, enrollment=enrollment, actor=actor, context=context)
        _emit(
            event_type=events.PUBLICATION_PUBLISHED,
            aggregate_type="task_publication",
            aggregate_ref=published.public_id,
            payload={"publication_id": published.public_id, "task_count": len(enrollments)},
            context=context,
        )
    PUBLICATION_ASSIGNMENT_DURATION.observe((timezone.now() - started).total_seconds())
    PUBLICATION_DECISIONS_TOTAL.labels(result="async" if async_assignment else "published").inc()
    _audit(
        context=context,
        actor=actor,
        action="experiment.publication.publish",
        target_type="task_publication",
        target_ref=published.public_id,
        course_ref=course.public_id,
        before={"status": publication.status},
        after={"status": next_status, "audience_count": len(enrollments)},
    )
    return published, 202 if async_assignment else 201


@transaction.atomic
def create_retake_publication(
    *,
    course_id: str,
    publication_id: str,
    selected_enrollment_ids: list[str],
    window_start: datetime,
    window_end: datetime,
    actor: User,
    context: Any,
) -> tuple[TaskPublication, int]:
    from apps.courses.models import Course

    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
        source = (
            TaskPublication.objects
            .select_for_update()
            .select_related("course", "template_version", "rubric_version")
            .get(public_id=publication_id, course=course)
        )
    except (Course.DoesNotExist, TaskPublication.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    require_course_capability(
        course=course, actor=actor, capability=CourseStaffGrant.Capability.PUBLISH_EXPERIMENT
    )
    if source.direct_assessment:
        raise PublicationValidationError(detail={"publication_id": "use_part_redo"})
    if source.retake_of_id is not None:
        raise PublicationValidationError(detail={"publication_id": "不能对补做实验再次创建补做"})
    if source.status not in {TaskPublication.Status.PUBLISHED, TaskPublication.Status.CLOSED}:
        raise PublicationValidationError(detail={"publication_status": source.status})
    if window_end <= window_start or window_start <= timezone.now():
        raise PublicationValidationError(
            detail={"window_start": "补做开放时间必须在未来且早于截止时间"}
        )
    if not selected_enrollment_ids:
        raise PublicationValidationError(detail={"selected_enrollment_ids": "至少选择一名学生"})
    if len(selected_enrollment_ids) != len(set(selected_enrollment_ids)):
        raise PublicationValidationError(detail={"selected_enrollment_ids": "不能包含重复选课记录"})

    enrollments = list(
        Enrollment.objects
        .select_for_update()
        .filter(
            course=course,
            status=Enrollment.Status.ACTIVE,
            public_id__in=selected_enrollment_ids,
        )
        .select_related("student")
        .order_by("id")
    )
    if len(enrollments) != len(selected_enrollment_ids):
        raise PublicationValidationError(
            detail={"selected_enrollment_ids": "只能选择本课程有效选课学生"}
        )
    source_tasks = list(
        ExperimentTask.objects
        .select_for_update()
        .filter(publication=source, student_id__in=[item.student_id for item in enrollments])
        .select_related("enrollment")
        .order_by("id")
    )
    if len(source_tasks) != len(enrollments):
        raise PublicationValidationError(
            detail={"selected_enrollment_ids": "所选学生没有对应的原实验任务"}
        )
    if ExperimentRetakeLink.objects.filter(source_task__in=source_tasks).exists():
        raise PublicationValidationError(
            detail={"selected_enrollment_ids": "所选学生已有该实验的补做任务"}
        )

    retake = create_publication(
        course_id=course.public_id,
        actor=actor,
        data={
            "template_version_id": source.template_version.public_id,
            "course_chapter_id": source.course_chapter.public_id if source.course_chapter else None,
            "rubric_version_id": source.rubric_version.public_id if source.rubric_version else None,
            "title": source.title,
            "description": source.description,
            "audience_mode": TaskPublication.AudienceMode.SELECTED,
            "late_enrollment_policy": TaskPublication.LateEnrollmentPolicy.DO_NOT_ASSIGN,
            "window_start": window_start,
            "window_end": window_end,
            "assignment_deadline": window_end,
            "report_required": source.report_required,
            "review_mode": source.review_mode,
            "prerequisites": [],
        },
        context=context,
    )
    retake = compare_and_swap(
        TaskPublication,
        pk=retake.pk,
        expected_version=retake.row_version,
        changes={"retake_of": source, "report_template_asset": source.report_template_asset},
    )
    ExperimentRetakeLink.objects.bulk_create([
        ExperimentRetakeLink(
            source_task=source_task,
            retake_publication=retake,
            created_by=actor,
        )
        for source_task in source_tasks
    ])
    return publish_publication(
        course_id=course.public_id,
        publication_id=retake.public_id,
        actor=actor,
        expected_version=retake.row_version,
        selected_ids=selected_enrollment_ids,
        context=context,
    )


def publication_audience_enrollment_ids(publication: TaskPublication) -> list[str]:
    audience = publication.audience.filter(
        audience_kind=PublicationAudience.Kind.ALL_ACTIVE
    ).first()
    return list(
        audience.snapshot_enrollment_ids
        if audience
        else publication.audience.values_list("enrollment__public_id", flat=True)
    )


def _finalize_publication_assignment(
    *, publication: TaskPublication, expected_count: int, context: Any
) -> TaskPublication:
    task_count = publication.tasks.count()
    if task_count < expected_count:
        return publication
    changed = compare_and_swap(
        TaskPublication,
        pk=publication.pk,
        expected_version=publication.row_version,
        changes={"status": TaskPublication.Status.PUBLISHED, "published_at": timezone.now()},
    )
    _emit(
        event_type=events.PUBLICATION_PUBLISHED,
        aggregate_type="task_publication",
        aggregate_ref=changed.public_id,
        payload={"publication_id": changed.public_id, "task_count": task_count},
        context=context,
    )
    return changed


@transaction.atomic
def execute_publication_assignment_chunk(
    *, publication_id: str, enrollment_ids: list[str], context: Any
) -> TaskPublication:
    publication = (
        TaskPublication.objects
        .select_for_update()
        .select_related("course", "template_version", "published_by")
        .prefetch_related("audience")
        .get(public_id=publication_id)
    )
    if publication.status != TaskPublication.Status.PUBLISHING:
        return publication
    frozen_ids = publication_audience_enrollment_ids(publication)
    requested_ids = set(enrollment_ids) & set(frozen_ids)
    enrollments = Enrollment.objects.select_related("student").filter(
        public_id__in=requested_ids, course=publication.course
    )
    for enrollment in enrollments:
        _create_task(
            publication=publication,
            enrollment=enrollment,
            actor=publication.published_by,
            context=context,
        )
    return _finalize_publication_assignment(
        publication=publication,
        expected_count=len(frozen_ids),
        context=context,
    )


@transaction.atomic
def execute_publication_assignment(*, publication_id: str, context: Any) -> TaskPublication:
    publication = (
        TaskPublication.objects
        .select_for_update()
        .select_related("course", "template_version", "published_by")
        .prefetch_related("audience")
        .get(public_id=publication_id)
    )
    if publication.status != TaskPublication.Status.PUBLISHING:
        return publication
    enrollment_ids = publication_audience_enrollment_ids(publication)
    enrollments = Enrollment.objects.select_related("student").filter(
        public_id__in=enrollment_ids,
        course=publication.course,
    )
    for enrollment in enrollments:
        _create_task(
            publication=publication,
            enrollment=enrollment,
            actor=publication.published_by,
            context=context,
        )
    return _finalize_publication_assignment(
        publication=publication,
        expected_count=len(enrollment_ids),
        context=context,
    )


def retry_publication_assignment_compensation(task: CompensationTask) -> None:
    with transaction.atomic():
        publication = TaskPublication.objects.select_for_update().get(public_id=task.subject_ref)
        if publication.status in {
            TaskPublication.Status.PUBLISHED,
            TaskPublication.Status.CLOSED,
            TaskPublication.Status.WITHDRAWN,
        }:
            return
        if publication.status == TaskPublication.Status.PUBLISH_FAILED:
            compare_and_swap(
                TaskPublication,
                pk=publication.pk,
                expected_version=publication.row_version,
                changes={"status": TaskPublication.Status.PUBLISHING, "publication_error": {}},
            )
    execute_publication_assignment(
        publication_id=publication.public_id,
        context=type(
            "CompensationContext",
            (),
            {"trace_id": task.trace_id, "portal": "WORKER", "actor_ref": "compensation"},
        )(),
    )


def assign_late_enrollment(enrollment: Enrollment, context: Any) -> None:
    now = timezone.now()
    publication_ids = list(
        TaskPublication.objects
        .filter(
            course=enrollment.course,
            status=TaskPublication.Status.PUBLISHED,
            late_enrollment_policy=TaskPublication.LateEnrollmentPolicy.ASSIGN_UNTIL_DEADLINE,
        )
        .filter(models_q_assignment_deadline(now))
        .values_list("public_id", flat=True)
    )
    from .tasks import assign_late_enrollment_task

    for publication_id in publication_ids:
        transaction.on_commit(
            lambda publication_id=publication_id: assign_late_enrollment_task.delay(
                enrollment.public_id, publication_id, _trace(context)
            )
        )


def models_q_assignment_deadline(now: Any) -> Any:
    from django.db.models import Q

    return Q(assignment_deadline__isnull=True) | Q(assignment_deadline__gte=now)


@transaction.atomic
def assign_late_enrollment_task(
    *, enrollment_id: str, publication_id: str, context: Any
) -> ExperimentTask | None:
    try:
        enrollment = (
            Enrollment.objects
            .select_for_update()
            .select_related("course", "student")
            .get(public_id=enrollment_id)
        )
        publication = (
            TaskPublication.objects
            .select_for_update()
            .select_related("course", "template_version")
            .get(public_id=publication_id)
        )
    except Enrollment.DoesNotExist, TaskPublication.DoesNotExist:
        return None
    if (
        enrollment.status != Enrollment.Status.ACTIVE
        or publication.status != TaskPublication.Status.PUBLISHED
        or enrollment.course_id != publication.course_id
    ):
        return None
    if publication.audience_mode != TaskPublication.AudienceMode.ALL_ACTIVE:
        return None
    if publication.assignment_deadline and publication.assignment_deadline < timezone.now():
        return None
    return _create_task(
        publication=publication,
        enrollment=enrollment,
        actor=publication.published_by,
        context=context,
    )


@transaction.atomic
def close_publication(
    *, course_id: str, publication_id: str, actor: User, expected_version: int, context: Any
) -> TaskPublication:
    from apps.courses.models import Course

    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
        publication = TaskPublication.objects.select_for_update().get(
            public_id=publication_id, course=course
        )
    except (Course.DoesNotExist, TaskPublication.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    require_course_capability(
        course=course, actor=actor, capability=CourseStaffGrant.Capability.PUBLISH_EXPERIMENT
    )
    if publication.status != TaskPublication.Status.PUBLISHED:
        raise PublicationStateConflict(detail={"status": publication.status})
    changed = compare_and_swap(
        TaskPublication,
        pk=publication.pk,
        expected_version=expected_version,
        changes={
            "status": TaskPublication.Status.CLOSED,
            "closed_by": actor,
            "closed_at": timezone.now(),
        },
    )
    _emit(
        event_type=events.PUBLICATION_CLOSED,
        aggregate_type="task_publication",
        aggregate_ref=changed.public_id,
        payload={"publication_id": changed.public_id},
        context=context,
    )
    return changed


@transaction.atomic
def withdraw_publication(
    *, course_id: str, publication_id: str, actor: User, expected_version: int, context: Any
) -> TaskPublication:
    from apps.courses.models import Course

    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
        publication = TaskPublication.objects.select_for_update().get(
            public_id=publication_id, course=course
        )
    except (Course.DoesNotExist, TaskPublication.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    require_course_capability(
        course=course, actor=actor, capability=CourseStaffGrant.Capability.PUBLISH_EXPERIMENT
    )
    if publication.grades_published_at:
        raise PublicationStateConflict(detail={"publication": "grades_locked"})
    if publication.status not in {
        TaskPublication.Status.PUBLISHED,
        TaskPublication.Status.PUBLISHING,
        TaskPublication.Status.PUBLISH_FAILED,
    }:
        raise PublicationStateConflict(detail={"status": publication.status})
    changed = compare_and_swap(
        TaskPublication,
        pk=publication.pk,
        expected_version=expected_version,
        changes={
            "status": TaskPublication.Status.WITHDRAWN,
            "withdrawn_by": actor,
            "withdrawn_at": timezone.now(),
        },
    )
    for task in (
        ExperimentTask.objects
        .select_for_update()
        .filter(publication=publication)
        .exclude(
            status__in=(
                ExperimentTask.Status.COMPLETED,
                ExperimentTask.Status.CANCELLED,
                ExperimentTask.Status.EXPIRED,
            )
        )
    ):
        if task.status == ExperimentTask.Status.ASSIGNED:
            transition_task(
                task_id=task.public_id,
                to_status=ExperimentTask.Status.CANCELLED,
                actor=actor,
                expected_version=task.row_version,
                trigger="WITHDRAW",
                reason="publication withdrawn",
                context=context,
            )
        else:
            request_task_terminal(
                task_id=task.public_id,
                terminal_target=ExperimentTask.TerminalTarget.CANCELLED,
                trigger="WITHDRAW",
                context=context,
                actor=actor,
            )
    _emit(
        event_type=events.PUBLICATION_WITHDRAWN,
        aggregate_type="task_publication",
        aggregate_ref=changed.public_id,
        payload={"publication_id": changed.public_id},
        context=context,
    )
    return changed


def _timestamp_changes(to_status: str) -> dict[str, Any]:
    now = timezone.now()
    return {
        ExperimentTask.Status.IN_PROGRESS: {"entered_at": now},
        ExperimentTask.Status.UNDER_REVIEW: {"submitted_at": now},
        ExperimentTask.Status.APPROVED: {"reviewed_at": now},
        ExperimentTask.Status.ARCHIVING: {"archived_at": now},
        ExperimentTask.Status.COMPLETED: {"completed_at": now, "progress": 100},
    }.get(to_status, {})


@transaction.atomic
def transition_task(
    *,
    task_id: str,
    to_status: str,
    actor: User | None,
    expected_version: int,
    trigger: str,
    reason: str,
    context: Any,
    detail: dict[str, Any] | None = None,
) -> ExperimentTask:
    task = (
        ExperimentTask.objects
        .select_for_update()
        .select_related("course", "publication", "enrollment", "student")
        .get(public_id=task_id)
    )
    current = task.status
    allowed = TASK_TRANSITIONS.get(current, set())
    if current == ExperimentTask.Status.FAILED:
        failure = task.current_failure or {}
        if not failure.get("retryable") or to_status != failure.get("previous_status"):
            raise TaskStateConflict(
                detail={"status": current, "previous_status": failure.get("previous_status")}
            )
    elif to_status not in allowed:
        raise TaskStateConflict(detail={"from_status": current, "to_status": to_status})
    changes: dict[str, Any] = {"status": to_status, "current_failure": {}}
    changes.update(_timestamp_changes(to_status))
    if to_status == ExperimentTask.Status.FAILED:
        changes["current_failure"] = {
            "previous_status": current,
            "retryable": bool((detail or {}).get("retryable", False)),
            "error_code": (detail or {}).get("error_code", "TASK_STEP_FAILED"),
        }
    changed = compare_and_swap(
        ExperimentTask, pk=task.pk, expected_version=expected_version, changes=changes
    )
    _transition_row(
        task=changed,
        from_status=current,
        to_status=to_status,
        actor=actor,
        trigger=trigger,
        reason=reason,
        context=context,
        detail=detail,
    )
    _audit(
        context=context,
        actor=actor,
        action="experiment.task.transition",
        target_type="experiment_task",
        target_ref=changed.public_id,
        course_ref=changed.course.public_id,
        before={"status": current},
        after={"status": to_status},
    )
    return changed


def allowed_actions(task: ExperimentTask, *, actor: User | None = None) -> list[str]:
    actions: list[str] = []
    if (
        actor is None
        or actor.pk != task.student_id
        or task.enrollment.status != Enrollment.Status.ACTIVE
    ):
        return actions
    if task.status not in {
        ExperimentTask.Status.COMPLETED,
        ExperimentTask.Status.CANCELLED,
        ExperimentTask.Status.EXPIRED,
    }:
        actions.append("REQUEST_EXTENSION")
    return actions


@transaction.atomic
def request_extension(
    *, task_id: str, actor: User, data: dict[str, Any], context: Any
) -> TaskExtensionRequest:
    try:
        task = (
            ExperimentTask.objects
            .select_for_update()
            .select_related("publication", "course", "student")
            .get(public_id=task_id, student=actor)
        )
    except ExperimentTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if task.status in {
        ExperimentTask.Status.COMPLETED,
        ExperimentTask.Status.CANCELLED,
        ExperimentTask.Status.EXPIRED,
    }:
        raise TaskExtensionConflict(detail={"status": task.status})
    original = task.effective_deadline or task.publication.window_end
    requested = data["requested_deadline"]
    if requested <= original:
        raise TaskExtensionConflict(detail={"original_deadline": original})
    request = TaskExtensionRequest.objects.create(
        task=task,
        requested_by=actor,
        original_deadline=original,
        requested_deadline=requested,
        reason=str(data["reason"]).strip(),
    )
    _audit(
        context=context,
        actor=actor,
        action="experiment.extension.request",
        target_type="task_extension_request",
        target_ref=request.public_id,
        course_ref=task.course.public_id,
        after={"status": request.status, "requested_deadline": requested.isoformat()},
    )
    return request


@transaction.atomic
def decide_extension(
    *,
    course_id: str,
    request_id: str,
    actor: User,
    decision: str,
    reason: str,
    expected_version: int,
    context: Any,
) -> TaskExtensionRequest:
    from apps.courses.models import Course

    try:
        course = Course.objects.select_for_update().get(public_id=course_id)
        request = (
            TaskExtensionRequest.objects
            .select_for_update()
            .select_related("task", "task__publication", "task__student", "task__course")
            .get(public_id=request_id, task__course=course)
        )
    except (Course.DoesNotExist, TaskExtensionRequest.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    require_course_capability(
        course=course, actor=actor, capability=CourseStaffGrant.Capability.MANAGE_EXTENSION
    )
    if request.status != TaskExtensionRequest.Status.PENDING:
        raise TaskExtensionConflict(detail={"status": request.status})
    if decision not in {
        TaskExtensionDecision.Decision.APPROVE,
        TaskExtensionDecision.Decision.REJECT,
    }:
        raise TaskExtensionConflict(detail={"decision": decision})
    now = timezone.now()
    approved_deadline = (
        request.requested_deadline if decision == TaskExtensionDecision.Decision.APPROVE else None
    )
    TaskExtensionDecision.objects.create(
        request=request,
        actor=actor,
        decision=decision,
        effective_deadline=approved_deadline,
        reason=reason.strip(),
        trace_id=_trace(context),
    )
    changed = compare_and_swap(
        TaskExtensionRequest,
        pk=request.pk,
        expected_version=expected_version,
        changes={
            "status": TaskExtensionRequest.Status.APPROVED
            if decision == "APPROVE"
            else TaskExtensionRequest.Status.REJECTED,
            "decided_at": now,
            "effective_deadline": approved_deadline,
        },
    )
    if approved_deadline is not None:
        task = ExperimentTask.objects.select_for_update().get(pk=request.task_id)
        compare_and_swap(
            ExperimentTask,
            pk=task.pk,
            expected_version=task.row_version,
            changes={"effective_deadline": approved_deadline},
        )
    _emit(
        event_type=events.TASK_EXTENSION_DECIDED,
        aggregate_type="task_extension_request",
        aggregate_ref=changed.public_id,
        payload={"request_id": changed.public_id, "decision": decision},
        context=context,
    )
    _audit(
        context=context,
        actor=actor,
        action="experiment.extension.decide",
        target_type="task_extension_request",
        target_ref=changed.public_id,
        course_ref=course.public_id,
        before={"status": request.status},
        after={"status": changed.status, "decision": decision},
    )
    return changed


def enrollment_task_blockers(enrollment: Enrollment) -> list[Blocker]:
    active = ExperimentTask.objects.filter(
        enrollment=enrollment,
    ).exclude(
        status__in=(
            ExperimentTask.Status.COMPLETED,
            ExperimentTask.Status.CANCELLED,
            ExperimentTask.Status.EXPIRED,
        )
    )
    if not active.exists():
        return []
    return [
        Blocker(
            type="UNFINISHED_TASK",
            count=active.count(),
            refs=tuple(active.values_list("public_id", flat=True)[:10]),
            message="存在未终止的课程实验任务",
        )
    ]


def teaching_progress(*, course_id: str, actor: User) -> dict[str, Any]:
    from apps.courses.models import Course

    try:
        course = Course.objects.get(public_id=course_id)
    except Course.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    require_course_capability(
        course=course, actor=actor, capability=CourseStaffGrant.Capability.VIEW_PROGRESS
    )
    counts = {
        item["status"]: item["count"]
        for item in ExperimentTask.objects
        .filter(course=course, publication__retake_of__isnull=True)
        .values("status")
        .annotate(count=Count("id"))
    }
    experiments: dict[str, dict[str, Any]] = {}
    for item in (
        ExperimentTask.objects
        .filter(course=course, publication__retake_of__isnull=True)
        .values("publication__public_id", "publication__title", "status")
        .annotate(count=Count("id"))
    ):
        publication_id = item["publication__public_id"]
        progress = experiments.setdefault(
            publication_id,
            {
                "publication_id": publication_id,
                "title": item["publication__title"],
                "task_counts": {},
                "total": 0,
            },
        )
        progress["task_counts"][item["status"]] = item["count"]
        progress["total"] += item["count"]
    course_tasks = list(
        ExperimentTask.objects
        .filter(course=course, publication__retake_of__isnull=True)
        .select_related("publication", "student")
        .order_by("publication__created_at", "student__display_name", "id")
    )
    grades = task_grades(course_tasks)
    for task in course_tasks:
        progress = experiments[task.publication.public_id]
        progress.setdefault("students", []).append({
            "task_id": task.public_id,
            "student_id": task.student.public_id,
            "student_name": task.student.display_name,
            "status": task.status,
            "progress": task.progress,
            "completed_at": task.completed_at,
            "decision": (None),
            **grades[task.pk],
        })
    return {
        "course_id": course.public_id,
        "task_counts": counts,
        "total": sum(counts.values()),
        "student_count": ExperimentTask.objects
        .filter(course=course)
        .values("student_id")
        .distinct()
        .count(),
        "experiments": list(experiments.values()),
    }


def student_learning_history(*, actor: User) -> dict[str, Any]:
    enrollments = list(
        Enrollment.objects
        .filter(
            student=actor,
            status__in=(
                Enrollment.Status.ACTIVE,
                Enrollment.Status.DROPPED,
                Enrollment.Status.REMOVED,
            ),
        )
        .select_related("course__term")
        .order_by("course__term__starts_at", "course__title", "cycle_no")
    )
    tasks = list(
        ExperimentTask.objects
        .filter(enrollment__in=enrollments, publication__retake_of__isnull=True)
        .select_related("publication", "enrollment", "course__term")
        .order_by("created_at", "id")
    )
    grades = task_grades(tasks, student=True)
    tasks_by_enrollment: dict[int, list[ExperimentTask]] = {}
    for task in tasks:
        tasks_by_enrollment.setdefault(task.enrollment_id, []).append(task)

    academic_years = {
        enrollment.course.term.starts_at.year
        if enrollment.course.term.starts_at.month >= 8
        else enrollment.course.term.starts_at.year - 1
        for enrollment in enrollments
    }
    if not academic_years:
        return {"years": []}
    first_year = min(academic_years)
    year_count = max(4, max(academic_years) - first_year + 1)
    years: list[dict[str, Any]] = [
        {
            "university_year": index + 1,
            "academic_year": f"{first_year + index}-{first_year + index + 1}",
            "terms": {},
        }
        for index in range(year_count)
    ]
    for enrollment in enrollments:
        term = enrollment.course.term
        academic_year = (
            term.starts_at.year if term.starts_at.month >= 8 else term.starts_at.year - 1
        )
        year = years[academic_year - first_year]
        terms: dict[str, Any] = year["terms"]
        term_data = terms.setdefault(
            term.public_id,
            {"term_id": term.public_id, "code": term.code, "name": term.name, "courses": []},
        )
        course_tasks = tasks_by_enrollment.get(enrollment.pk, [])
        term_data["courses"].append({
            "course_id": enrollment.course.public_id,
            "course_code": enrollment.course.code,
            "course_title": enrollment.course.title,
            "class_type": "TEACHING",
            "enrollment": {
                "public_id": enrollment.public_id,
                "cycle_no": enrollment.cycle_no,
                "status": enrollment.status,
                "activated_at": enrollment.activated_at,
                "ended_at": enrollment.ended_at,
            },
            "experiments": [
                {
                    "task_id": task.public_id,
                    "publication_id": task.publication.public_id,
                    "title": task.publication.title,
                    "status": task.status,
                    "progress": task.progress,
                    "completed_at": task.completed_at,
                    "decision": None,
                    **grades[task.pk],
                }
                for task in course_tasks
            ],
        })
    return {"years": [{**year, "terms": list(year["terms"].values())} for year in years]}
