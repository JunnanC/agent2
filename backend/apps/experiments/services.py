import hashlib
import json
import re
from collections.abc import Iterable, Mapping
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
from apps.labtemplates.errors import TemplateValidationError
from apps.labtemplates.models import ExperimentImage, TemplateChapter, TemplateTask, TemplateVersion
from apps.labtemplates.services import _normalize_execution_spec
from apps.reviews.models import RubricVersion

from . import events
from .errors import (
    PublicationPrerequisiteBlocked,
    PublicationStateConflict,
    PublicationValidationError,
    TaskExtensionConflict,
    TaskStateConflict,
)
from .metrics import (
    PUBLICATION_ASSIGNMENT_DURATION,
    PUBLICATION_DECISIONS_TOTAL,
    TASK_ASSIGNMENTS_TOTAL,
    TASK_TRANSITIONS_TOTAL,
)
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
from .ports import request_task_terminal

TASK_TRANSITIONS: dict[str, set[str]] = {
    ExperimentTask.Status.ASSIGNED: {
        ExperimentTask.Status.PROVISIONING,
        ExperimentTask.Status.CANCELLED,
        ExperimentTask.Status.EXPIRED,
    },
    ExperimentTask.Status.PROVISIONING: {
        ExperimentTask.Status.READY,
        ExperimentTask.Status.FAILED,
        ExperimentTask.Status.ARCHIVING,
    },
    ExperimentTask.Status.READY: {
        ExperimentTask.Status.IN_PROGRESS,
        ExperimentTask.Status.FAILED,
        ExperimentTask.Status.ARCHIVING,
    },
    ExperimentTask.Status.IN_PROGRESS: {
        ExperimentTask.Status.REPORT_DRAFT,
        ExperimentTask.Status.UNDER_REVIEW,
        ExperimentTask.Status.FAILED,
        ExperimentTask.Status.ARCHIVING,
    },
    ExperimentTask.Status.REPORT_DRAFT: {
        ExperimentTask.Status.UNDER_REVIEW,
        ExperimentTask.Status.FAILED,
        ExperimentTask.Status.ARCHIVING,
    },
    ExperimentTask.Status.UNDER_REVIEW: {
        ExperimentTask.Status.APPROVED,
        ExperimentTask.Status.REJECTED,
        ExperimentTask.Status.FAILED,
    },
    ExperimentTask.Status.APPROVED: {ExperimentTask.Status.ARCHIVING},
    ExperimentTask.Status.REJECTED: {
        ExperimentTask.Status.REPORT_DRAFT,
        ExperimentTask.Status.IN_PROGRESS,
    },
    ExperimentTask.Status.ARCHIVING: {
        ExperimentTask.Status.DESTROYING,
        ExperimentTask.Status.FAILED,
    },
    ExperimentTask.Status.DESTROYING: {
        ExperimentTask.Status.COMPLETED,
        ExperimentTask.Status.CANCELLED,
        ExperimentTask.Status.EXPIRED,
        ExperimentTask.Status.FAILED,
    },
    ExperimentTask.Status.FAILED: set(),
    ExperimentTask.Status.COMPLETED: set(),
    ExperimentTask.Status.CANCELLED: set(),
    ExperimentTask.Status.EXPIRED: set(),
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
        raise PublicationValidationError(
            detail={"resource_profile_id": {source_id: "required"}}
        )
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
        ExperimentImage.objects.filter(
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
    all_chapters = list(
        TemplateChapter.objects.filter(template_version=template)
        .select_related("resource_profile")
        .prefetch_related("tasks__resource_profile")
        .order_by("sort_order", "id")
    )
    if not all_chapters:
        raise PublicationValidationError(detail={"chapters": "at_least_one_required"})
    draft_chapters = [
        chapter.public_id
        for chapter in all_chapters
        if chapter.status != TemplateChapter.Status.PUBLISHED
    ]
    if draft_chapters:
        raise PublicationValidationError(
            detail={"chapters": {"not_published": draft_chapters}}
        )
    chapters = [
        chapter for chapter in all_chapters if chapter.status == TemplateChapter.Status.PUBLISHED
    ]
    chapter_orders = [chapter.sort_order for chapter in chapters]
    if len(chapter_orders) != len(set(chapter_orders)) or any(
        order < 1 for order in chapter_orders
    ):
        raise PublicationValidationError(detail={"chapter_sort_order": "unique_positive_required"})

    image_snapshot = _ready_image_snapshot(template)
    version_profile = _resource_snapshot(
        template.resource_profile,
        runtime_type=template.runtime_type,
        source_id=template.public_id,
    )
    chapter_snapshots: list[dict[str, Any]] = []
    for chapter in chapters:
        all_tasks = list(chapter.tasks.all().order_by("sort_order", "id"))
        draft_tasks = [
            task.public_id
            for task in all_tasks
            if task.status != TemplateTask.Status.PUBLISHED
        ]
        if draft_tasks:
            raise PublicationValidationError(
                detail={"chapter_tasks": {chapter.public_id: {"not_published": draft_tasks}}}
            )
        tasks = [task for task in all_tasks if task.status == TemplateTask.Status.PUBLISHED]
        if not tasks:
            raise PublicationValidationError(
                detail={"chapter_tasks": {chapter.public_id: "at_least_one_required"}}
            )
        task_orders = [task.sort_order for task in tasks]
        if len(task_orders) != len(set(task_orders)) or any(order < 1 for order in task_orders):
            raise PublicationValidationError(
                detail={"task_sort_order": {chapter.public_id: "unique_positive_required"}}
            )
        task_snapshots: list[dict[str, Any]] = []
        for task in tasks:
            profile = task.resource_profile or chapter.resource_profile or template.resource_profile
            resource_snapshot = _resource_snapshot(
                profile,
                runtime_type=template.runtime_type,
                source_id=task.public_id,
            )
            merged_execution_spec = {
                **dict(template.execution_spec or {}),
                **dict(task.execution_spec or {}),
            }
            try:
                normalized_execution_spec = _normalize_execution_spec(merged_execution_spec)
            except TemplateValidationError as exc:
                raise PublicationValidationError(
                    detail={"execution_spec": {task.public_id: exc.detail}}
                ) from exc
            execution_snapshot = {
                "execution_spec": normalized_execution_spec,
                "network_policy": dict(template.network_policy or {}),
                "workspace_capabilities": dict(template.workspace_capabilities or {}),
                "report_policy": dict(template.report_policy or {}),
                "review_policy": dict(template.review_policy or {}),
            }
            task_snapshots.append({
                "source_task_id": task.public_id,
                "title": task.title,
                "description": task.description,
                "instructions": task.instructions,
                "task_type": task.task_type,
                "sort_order": task.sort_order,
                "image_digest": image_snapshot["digest"],
                "resource_profile_snapshot": resource_snapshot,
                "execution_snapshot": execution_snapshot,
                "submission_policy": dict(task.submission_policy or {}),
                "grading_policy": dict(task.grading_policy or {}),
            })
        chapter_snapshots.append({
            "source_chapter_id": chapter.public_id,
            "title": chapter.title,
            "description": chapter.description,
            "learning_objectives": list(chapter.learning_objectives or []),
            "sort_order": chapter.sort_order,
            "resource_profile_snapshot": _resource_snapshot(
                chapter.resource_profile or template.resource_profile,
                runtime_type=template.runtime_type,
                source_id=chapter.public_id,
            ),
            "tasks": task_snapshots,
        })

    template_digest = _json_digest({
        "template_version_id": template.public_id,
        "template_spec_digest": template.spec_digest,
        "runtime_type": template.runtime_type,
        "runtime_adapter_id": template.runtime_adapter.public_id,
        "runtime_adapter_driver": template.runtime_adapter.driver,
        "runtime_adapter_config_ref": template.runtime_adapter.config_ref,
        "image": {
            "registry": image_snapshot["registry"],
            "repository": image_snapshot["repository"],
            "digest": image_snapshot["digest"],
        },
        "resource_profile": version_profile,
        "execution_spec": dict(template.execution_spec or {}),
        "network_policy": dict(template.network_policy or {}),
        "workspace_capabilities": dict(template.workspace_capabilities or {}),
        "chapters": chapter_snapshots,
    })
    return {
        "chapters": chapter_snapshots,
        "template_digest": template_digest,
        "image": image_snapshot,
        "resource_profile": version_profile,
        "template_spec_digest": template.spec_digest,
        "execution_spec": dict(template.execution_spec or {}),
        "runtime_adapter": template.runtime_adapter,
        "runtime_adapter_driver": template.runtime_adapter.driver,
        "runtime_adapter_config_ref": template.runtime_adapter.config_ref,
    }


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
            TemplateVersion.objects.select_for_update()
            .select_related("template", "runtime_adapter", "resource_profile")
            .get(**lookup)
        )
    except TemplateVersion.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if (
        locked_template.status != TemplateVersion.Status.PUBLISHED
        or not locked_template.spec_digest
    ):
        raise PublicationValidationError(
            detail={"template_version_status": locked_template.status}
        )
    return _content_snapshot(locked_template)


def publish_template_version(*, template_version: TemplateVersion) -> dict[str, Any]:
    return precheck_template_version(template_version=template_version)


def _runtime_snapshot(
    template: TemplateVersion, content: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Capture mutable runtime inputs when a publication is frozen."""

    adapter = template.runtime_adapter
    image = content["image"]["image"] if content is not None else template.image
    profile = template.resource_profile
    image_registry = content["image"]["registry"] if content is not None else image.registry
    image_repository = content["image"]["repository"] if content is not None else image.repository
    image_digest = content["image"]["digest"] if content is not None else image.digest
    execution_spec = dict(
        content["execution_spec"] if content is not None else template.execution_spec or {}
    )
    execution_spec["_runtime"] = {
        "network_policy": dict(template.network_policy or {}),
        "workspace_capabilities": dict(template.workspace_capabilities or {}),
    }
    return {
        "template_spec_digest": (
            content["template_spec_digest"] if content is not None else template.spec_digest
        ),
        "execution_spec": execution_spec,
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
    template = publication.template_version
    if template.template.course_id != publication.course_id:
        raise PublicationValidationError(detail={"template_version_id": template.public_id})
    if template.status != TemplateVersion.Status.PUBLISHED or not template.spec_digest:
        raise PublicationValidationError(detail={"template_version_status": template.status})
    rubric = publication.rubric_version
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
        rubric = RubricVersion.objects.select_related("rubric").get(
            public_id=data["rubric_version_id"]
        )
    except (TemplateVersion.DoesNotExist, RubricVersion.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    if template.template.course_id != course.pk or rubric.rubric.course_id != course.pk:
        raise PublicationValidationError(detail={"reason": "CROSS_COURSE_REFERENCE"})
    publication = TaskPublication.objects.create(
        course=course,
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
            TaskPublication.objects.select_for_update()
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
            "assignment_deadline",
            "report_required",
            "review_mode",
        }
    }
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
            Enrollment.objects.filter(course=publication.course, status=Enrollment.Status.ACTIVE)
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
        Enrollment.objects.filter(
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


def _create_task(
    *, publication: TaskPublication, enrollment: Enrollment, actor: User | None, context: Any
) -> ExperimentTask:
    template = publication.template_version
    snapshot = _runtime_snapshot(template)
    # Publications created before runtime snapshots have no snapshot columns. Keep those
    # historical rows assignable while every new task is fully frozen.
    if publication.runtime_adapter_id:
        snapshot = {
            "template_spec_digest": publication.template_spec_digest,
            "execution_spec": dict(publication.execution_spec or {}),
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
            runtime_type=template.runtime_type,
            template_spec_digest=snapshot["template_spec_digest"],
            execution_spec=snapshot["execution_spec"],
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
        return task
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
        },
        context=context,
    )
    TASK_ASSIGNMENTS_TOTAL.labels(result="created").inc()
    return task


def _copy_publication_snapshots(
    *, publication: TaskPublication, content: dict[str, Any]
) -> None:
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
            TaskPublication.objects.select_for_update()
            .select_related("course", "rubric_version__rubric")
            .get(public_id=publication_id, course=course)
        )
    except (Course.DoesNotExist, TaskPublication.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    require_course_capability(
        course=course, actor=actor, capability=CourseStaffGrant.Capability.PUBLISH_EXPERIMENT
    )
    if publication.status != TaskPublication.Status.DRAFT:
        raise PublicationStateConflict(detail={"status": publication.status})
    try:
        template = (
            TemplateVersion.objects.select_for_update()
            .select_related("template", "runtime_adapter", "image", "resource_profile")
            .get(pk=publication.template_version_id)
        )
    except TemplateVersion.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    publication.template_version = template
    _validate_dependencies(publication=publication)
    content = publish_template_version(template_version=template)
    enrollments = _freeze_audience(publication=publication, selected_ids=selected_ids)
    publication_digest = _json_digest({
        "course_id": course.public_id,
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
        **_runtime_snapshot(template, content),
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
    if getattr(settings, "AUTO_PROVISION_ON_ASSIGNMENT", True):
        from apps.provisioning.tasks import warmup_publication_image_task

        transaction.on_commit(
            lambda: warmup_publication_image_task.apply_async(
                kwargs={
                    "publication_id": published.public_id,
                    "trace_id": _trace(context),
                }
            )
        )
    return published, 202 if async_assignment else 201


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
        TaskPublication.objects.select_for_update()
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
        TaskPublication.objects.select_for_update()
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
        TaskPublication.objects.filter(
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
            Enrollment.objects.select_for_update()
            .select_related("course", "student")
            .get(public_id=enrollment_id)
        )
        publication = (
            TaskPublication.objects.select_for_update()
            .select_related("course", "template_version")
            .get(public_id=publication_id)
        )
    except (Enrollment.DoesNotExist, TaskPublication.DoesNotExist):
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
        ExperimentTask.objects.select_for_update()
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
        ExperimentTask.Status.PROVISIONING: {"started_at": now},
        ExperimentTask.Status.READY: {"ready_at": now},
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
        ExperimentTask.objects.select_for_update()
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
    if actor is None or actor.pk != task.student_id:
        return actions
    if task.status == ExperimentTask.Status.ASSIGNED:
        actions.append("START")
    if task.status in {
        ExperimentTask.Status.READY,
        ExperimentTask.Status.IN_PROGRESS,
        ExperimentTask.Status.REPORT_DRAFT,
    }:
        # 工作区可用的三个状态都允许(重)进入:enter 对 READY 会推进 IN_PROGRESS,其余状态仅轮换会话
        actions.append("ENTER")
    if task.status == ExperimentTask.Status.FAILED and (task.current_failure or {}).get(
        "retryable"
    ):
        actions.append("RETRY")
    if task.status not in {
        ExperimentTask.Status.COMPLETED,
        ExperimentTask.Status.CANCELLED,
        ExperimentTask.Status.EXPIRED,
    }:
        actions.append("REQUEST_EXTENSION")
    return actions


@transaction.atomic
def start_task(*, task_id: str, actor: User, expected_version: int, context: Any) -> ExperimentTask:
    try:
        task = (
            ExperimentTask.objects.select_for_update()
            .select_related("publication", "course", "enrollment", "student")
            .get(public_id=task_id, student=actor)
        )
    except ExperimentTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if task.status != ExperimentTask.Status.ASSIGNED:
        raise TaskStateConflict(detail={"status": task.status})
    if task.publication.status != task.publication.Status.PUBLISHED:
        raise TaskStateConflict(detail={"publication_status": task.publication.status})
    if task.enrollment.status != Enrollment.Status.ACTIVE:
        raise TaskStateConflict(detail={"enrollment_status": task.enrollment.status})
    now = timezone.now()
    if now < task.publication.window_start or now > task.effective_deadline:
        raise TaskStateConflict(
            detail={
                "window_start": task.publication.window_start,
                "effective_deadline": task.effective_deadline,
            }
        )
    blockers = prerequisite_blockers_for_publication(publication=task.publication, student=actor)
    if blockers:
        raise PublicationPrerequisiteBlocked(detail={"blockers": blockers})
    return transition_task(
        task_id=task.public_id,
        to_status=ExperimentTask.Status.PROVISIONING,
        actor=actor,
        expected_version=expected_version,
        trigger="START",
        reason="student started experiment",
        context=context,
    )


def start_task_runtime(
    *,
    task_id: str,
    actor: User,
    context: Any,
    expected_version: int | None = None,
    overrides: Mapping[str, object] | None = None,
    payload: Mapping[str, object] | None = None,
) -> tuple[ExperimentTask, Any]:
    """Start or reuse the student's runtime from the published task snapshot."""

    from apps.provisioning.services import start_provisioning

    try:
        task = ExperimentTask.objects.get(public_id=task_id, student=actor)
    except ExperimentTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    requested = overrides if overrides is not None else payload
    return start_provisioning(
        task_id=task_id,
        actor=actor,
        expected_version=task.row_version if expected_version is None else expected_version,
        context=context,
        overrides=requested,
    )


def stop_task_runtime(
    *, runtime_id: str, actor: User, context: Any, expected_version: int | None = None
) -> Any:
    """Destroy a student-owned runtime and revoke its workspace sessions."""

    from apps.provisioning.models import ProvisioningInstance
    from apps.provisioning.services import destroy_task_instance
    from apps.workspaces.services import revoke_task_sessions

    try:
        instance = (
            ProvisioningInstance.objects.select_related("task", "task__student")
            .get(public_id=runtime_id, task__student=actor)
        )
    except ProvisioningInstance.DoesNotExist as exc:
        raise ResourceNotFound() from exc
    if expected_version is not None and instance.task.row_version != expected_version:
        from apps.core.errors import RowVersionConflict

        raise RowVersionConflict(
            detail={
                "expected_row_version": expected_version,
                "actual_row_version": instance.task.row_version,
            }
        )
    instance_version = instance.row_version
    revoke_task_sessions(
        task_id=instance.task.public_id,
        reason="student stopped runtime",
        context=context,
    )
    destroyed = destroy_task_instance(
        task_id=instance.task.public_id,
        idempotency_key=f"student-stop:{runtime_id}",
        context=context,
        expected_version=instance_version,
    )
    return destroyed or instance


@transaction.atomic
def request_extension(
    *, task_id: str, actor: User, data: dict[str, Any], context: Any
) -> TaskExtensionRequest:
    try:
        task = (
            ExperimentTask.objects.select_for_update()
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
            TaskExtensionRequest.objects.select_for_update()
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
        for item in ExperimentTask.objects.filter(course=course)
        .values("status")
        .annotate(count=Count("id"))
    }
    return {"course_id": course.public_id, "task_counts": counts, "total": sum(counts.values())}
