from django.db.models import QuerySet

from apps.accounts.models import User
from apps.core.errors import ResourceNotFound
from apps.core.models import ObjectAsset
from apps.courses.models import Course, CourseStaffGrant
from apps.courses.selectors import require_course_capability
from apps.experiments.models import ExperimentTask

from .models import ReportDraft, ReportVersion


def task_for_user(*, actor: User, task_id: str) -> ExperimentTask:
    try:
        return ExperimentTask.objects.select_related(
            "course", "publication", "enrollment", "student"
        ).get(public_id=task_id, student=actor)
    except ExperimentTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def task_for_teaching(*, actor: User, course_id: str, task_id: str) -> ExperimentTask:
    try:
        course = Course.objects.get(public_id=course_id)
        task = ExperimentTask.objects.select_related(
            "course", "publication", "enrollment", "student"
        ).get(public_id=task_id, course=course)
    except (Course.DoesNotExist, ExperimentTask.DoesNotExist) as exc:
        raise ResourceNotFound() from exc
    require_course_capability(
        course=course,
        actor=actor,
        capability=CourseStaffGrant.Capability.REVIEW_SUBMISSION,
    )
    return task


def draft_for_user(*, actor: User, task_id: str) -> ReportDraft:
    task_for_user(actor=actor, task_id=task_id)
    try:
        return (
            ReportDraft.objects.select_related("task", "student", "workspace_snapshot")
            .prefetch_related("attachments__asset")
            .get(task__public_id=task_id, student=actor)
        )
    except ReportDraft.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def versions_for_user(*, actor: User, task_id: str) -> QuerySet[ReportVersion]:
    task_for_user(actor=actor, task_id=task_id)
    return (
        ReportVersion.objects.select_related("task", "student", "workspace_snapshot")
        .prefetch_related("attachments__attachment__asset")
        .filter(task__public_id=task_id, student=actor)
        .order_by("-version_no")
    )


def visible_report_asset(*, asset_id: str) -> ObjectAsset:
    try:
        return ObjectAsset.objects.get(public_id=asset_id)
    except ObjectAsset.DoesNotExist as exc:
        raise ResourceNotFound() from exc
