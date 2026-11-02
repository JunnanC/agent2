from django.db.models import Q, QuerySet

from apps.accounts.models import User
from apps.core.errors import ResourceNotFound
from apps.core.models import CompensationTask
from apps.courses.models import Course, CourseStaffGrant
from apps.courses.selectors import has_course_capability, visible_course
from apps.experiments.models import ExperimentTask
from apps.provisioning.models import ProvisioningInstance

from .errors import ArchiveExportDenied
from .models import ArchiveJob


def archive_for_user(*, actor: User, task_id: str) -> ArchiveJob:
    try:
        return archive_queryset().get(task__public_id=task_id, task__student=actor)
    except ArchiveJob.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def teaching_archive_course(*, actor: User, course_id: str, export: bool = False) -> Course:
    course = visible_course(actor=actor, portal="TEACHING", course_id=course_id)
    capabilities = (
        (CourseStaffGrant.Capability.EXPORT_RESULT,)
        if export
        else (
            CourseStaffGrant.Capability.VIEW_PROGRESS,
            CourseStaffGrant.Capability.EXPORT_RESULT,
        )
    )
    if not any(
        has_course_capability(course=course, actor=actor, capability=capability)
        for capability in capabilities
    ):
        raise ArchiveExportDenied()
    return course


def archive_queryset() -> QuerySet[ArchiveJob]:
    return (
        ArchiveJob.objects.select_related(
            "task__student",
            "task__publication",
            "course",
            "failure_record",
            "compensation_task",
            "manifest__package_asset",
        )
        .prefetch_related("verifications", "manifest__export_grants__download_grant")
        .order_by("-updated_at", "-id")
    )


def archives_for_course(*, actor: User, course_id: str) -> QuerySet[ArchiveJob]:
    course = teaching_archive_course(actor=actor, course_id=course_id)
    return archive_queryset().filter(course=course)


def archive_for_course(*, actor: User, course_id: str, archive_id: str) -> ArchiveJob:
    course = teaching_archive_course(actor=actor, course_id=course_id)
    try:
        return archive_queryset().get(public_id=archive_id, course=course)
    except ArchiveJob.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def instance_rows() -> QuerySet[ProvisioningInstance]:
    return ProvisioningInstance.objects.select_related(
        "task", "task__student", "course", "runtime_adapter"
    ).order_by("status", "updated_at", "id")


def compensation_rows(*, status: str = "") -> QuerySet[CompensationTask]:
    values = CompensationTask.objects.select_related("last_failure").filter(
        Q(task_type__in=("RETRY_ARCHIVE_JOB", "RETRY_RUNTIME_DESTROY"))
        | Q(subject_type__in=("ARCHIVE_JOB", "PROVISIONING_INSTANCE"))
    )
    if status:
        values = values.filter(status=status)
    return values.order_by("status", "next_attempt_at", "id")


def task_for_archive_request(*, task_id: str) -> ExperimentTask:
    try:
        return ExperimentTask.objects.select_related(
            "course", "student", "publication", "enrollment"
        ).get(public_id=task_id)
    except ExperimentTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc
