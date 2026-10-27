from datetime import timedelta

from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.models import User
from apps.core.errors import ResourceNotFound
from apps.courses.models import CourseStaffGrant
from apps.courses.selectors import require_course_capability, visible_course
from apps.experiments.models import ExperimentTask

from .errors import WorkspaceSessionInvalid
from .models import (
    OperationEvent,
    WorkspaceAutosaveLog,
    WorkspaceCheckpoint,
    WorkspaceExecutionRun,
    WorkspaceSession,
    WorkspaceSnapshot,
    WorkspaceStorageJob,
)


def task_for_user(*, actor: User, task_id: str) -> ExperimentTask:
    try:
        return ExperimentTask.objects.select_related(
            "course", "publication", "enrollment", "student", "template_version"
        ).get(public_id=task_id, student=actor)
    except ExperimentTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def weekly_study_minutes_for_student(*, student: User) -> dict[str, object]:
    """Aggregate per-day judge-run minutes for the current (Mon-based) week."""

    local_now = timezone.localtime(timezone.now())
    monday = (
        local_now - timedelta(days=local_now.weekday())
    ).replace(hour=0, minute=0, second=0, microsecond=0)
    last_monday = monday - timedelta(days=7)
    next_monday = monday + timedelta(days=7)
    runs = (
        WorkspaceExecutionRun.objects.filter(
            task__student=student,
            started_at__isnull=False,
            started_at__gte=last_monday,
            started_at__lt=next_monday,
        )
        .exclude(status=WorkspaceExecutionRun.Status.REJECTED)
        .only("started_at", "duration_ms", "status")
    )
    minutes_by_day = [0] * 7
    last_week_minutes = 0
    for run in runs:
        local_started = timezone.localtime(run.started_at)
        minutes = round((run.duration_ms or 0) / 60000)
        if local_started < monday:
            last_week_minutes += minutes
            continue
        minutes_by_day[(local_started - monday).days] += minutes
    total_minutes = sum(minutes_by_day)
    return {
        "minutes_by_day": minutes_by_day,
        "total_minutes": total_minutes,
        "last_week_minutes": last_week_minutes,
        "has_records": bool(total_minutes or last_week_minutes),
    }


def workbench_task_for_user(*, actor: User, task_id: str) -> ExperimentTask:
    """Load the read-only projection needed by the student workbench."""

    try:
        return (
            ExperimentTask.objects.select_related(
                "course",
                "publication",
                "enrollment",
                "student",
                "runtime_adapter",
                "template_version__template",
                "template_version__manual_asset",
                "template_version__starter_asset",
                "template_version__report_template_asset",
            )
            .prefetch_related(
                "template_version__auto_check_rules",
                "provisioning_jobs__failure_record",
                "provisioning_jobs__stage_events",
                "report_draft__attachments__asset",
                "workspace_execution_runs",
            )
            .get(
                public_id=task_id,
                student=actor,
                enrollment__student=actor,
                enrollment__status="ACTIVE",
            )
        )
    except ExperimentTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def task_for_teaching(*, actor: User, course_id: str, task_id: str) -> ExperimentTask:
    course = visible_course(actor=actor, portal="TEACHING", course_id=course_id)
    require_course_capability(
        course=course, actor=actor, capability=CourseStaffGrant.Capability.VIEW_PROGRESS
    )
    try:
        return ExperimentTask.objects.select_related(
            "course", "publication", "enrollment", "student", "template_version"
        ).get(public_id=task_id, course=course)
    except ExperimentTask.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def active_session_for_user(*, actor: User, task_id: str) -> WorkspaceSession:
    session = (
        WorkspaceSession.objects.select_related(
            "task__enrollment",
            "task__publication",
            "student",
            "course",
            "instance",
            "latest_snapshot",
        )
        .filter(task__public_id=task_id, student=actor, status=WorkspaceSession.Status.ACTIVE)
        .order_by("-created_at")
        .first()
    )
    if session is None:
        raise WorkspaceSessionInvalid()
    return session


def session_by_public_id(*, session_id: str) -> WorkspaceSession:
    try:
        return WorkspaceSession.objects.select_related(
            "task__enrollment",
            "task__publication",
            "student",
            "course",
            "instance",
            "latest_snapshot",
        ).get(public_id=session_id)
    except WorkspaceSession.DoesNotExist as exc:
        raise WorkspaceSessionInvalid() from exc


def checkpoints_for_user(*, actor: User, task_id: str) -> QuerySet[WorkspaceCheckpoint]:
    return (
        WorkspaceCheckpoint.objects.select_related("snapshot", "snapshot__asset")
        .filter(task__public_id=task_id, task__student=actor)
        .order_by("-checkpoint_no", "-created_at")
    )


def replay_for_user(*, actor: User, task_id: str) -> QuerySet[OperationEvent]:
    return OperationEvent.objects.filter(task__public_id=task_id, task__student=actor).order_by(
        "-occurred_at", "-id"
    )


def replay_for_teaching(*, actor: User, course_id: str, task_id: str) -> QuerySet[OperationEvent]:
    task_for_teaching(actor=actor, course_id=course_id, task_id=task_id)
    return OperationEvent.objects.filter(task__public_id=task_id).order_by("-occurred_at", "-id")


def snapshots_for_teaching(
    *, actor: User, course_id: str, task_id: str
) -> QuerySet[WorkspaceSnapshot]:
    task_for_teaching(actor=actor, course_id=course_id, task_id=task_id)
    return (
        WorkspaceSnapshot.objects.select_related("asset", "session")
        .filter(task__public_id=task_id)
        .order_by("-version_no", "-created_at")
    )


def sessions_for_platform() -> QuerySet[WorkspaceSession]:
    return WorkspaceSession.objects.select_related(
        "task", "student", "course", "instance"
    ).order_by("-created_at", "-id")


def autosave_for_seq(*, task_id: int, client_seq: int) -> WorkspaceAutosaveLog | None:
    return (
        WorkspaceAutosaveLog.objects.select_related("snapshot", "snapshot__asset")
        .filter(task_id=task_id, client_seq=client_seq)
        .first()
    )


def execution_runs_for_user(*, actor: User, task_id: str) -> QuerySet[WorkspaceExecutionRun]:
    return (
        WorkspaceExecutionRun.objects.select_related(
            "task", "session", "snapshot", "stdout_asset", "stderr_asset", "test_report_asset"
        )
        .filter(task__public_id=task_id, task__student=actor)
        .order_by("-created_at", "-id")
    )


def execution_run_for_user(
    *, actor: User, task_id: str, execution_id: str
) -> WorkspaceExecutionRun:
    try:
        return (
            WorkspaceExecutionRun.objects.select_related(
                "task", "session", "snapshot", "stdout_asset", "stderr_asset", "test_report_asset"
            )
            .get(public_id=execution_id, task__public_id=task_id, task__student=actor)
        )
    except WorkspaceExecutionRun.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def storage_job_for_user(*, actor: User, job_id: str) -> WorkspaceStorageJob:
    """Return a storage job only when it belongs to the current student."""

    try:
        return (
            WorkspaceStorageJob.objects.select_related(
                "task",
                "session",
                "source_snapshot",
                "result_snapshot",
                "failure_record",
            )
            .get(public_id=job_id, task__student=actor)
        )
    except WorkspaceStorageJob.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def active_storage_job_for_user(*, actor: User, task_id: str) -> WorkspaceStorageJob | None:
    return (
        WorkspaceStorageJob.objects.select_related(
            "task",
            "session",
            "source_snapshot",
            "result_snapshot",
            "failure_record",
        )
        .filter(
            task__public_id=task_id,
            task__student=actor,
            session__status=WorkspaceSession.Status.ACTIVE,
            kind__in=(
                WorkspaceStorageJob.Kind.INITIALIZE,
                WorkspaceStorageJob.Kind.CAPTURE,
                WorkspaceStorageJob.Kind.RESTORE,
                WorkspaceStorageJob.Kind.FINALIZE,
            ),
            status__in=(WorkspaceStorageJob.Status.QUEUED, WorkspaceStorageJob.Status.RUNNING),
        )
        .order_by("queued_at", "id")
        .first()
    )
