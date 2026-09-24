from typing import Any

from celery import shared_task

from apps.accounts.models import User
from apps.core.audit import append_failure
from apps.core.tasks import TraceTask

from .services import (
    destroy_instance_as_admin,
    execute_archive_job,
    reconcile_archives,
    scan_due_tasks,
    worker_context,
)


@shared_task(base=TraceTask, bind=True, acks_late=True, name="apps.archives.run_archive_job")
def run_archive_job(_task: Any, *, job_id: str, trace_id: str = "") -> str:
    return execute_archive_job(job_id=job_id, trace_id=trace_id).public_id


@shared_task(base=TraceTask, bind=True, acks_late=True, name="apps.archives.scan_due_tasks")
def scan_archive_deadlines(_task: Any, *, trace_id: str = "") -> int:
    return scan_due_tasks(trace_id=trace_id)


@shared_task(base=TraceTask, bind=True, acks_late=True, name="apps.archives.reconcile")
def reconcile_archive_state(_task: Any, *, trace_id: str = "") -> dict[str, int]:
    return reconcile_archives(trace_id=trace_id)


@shared_task(
    base=TraceTask,
    bind=True,
    acks_late=True,
    name="apps.archives.reconcile_course",
)
def reconcile_course_archives(_task: Any, *, course_id: str, trace_id: str = "") -> dict[str, int]:
    due = scan_due_tasks(trace_id=trace_id, course_id=course_id)
    result = reconcile_archives(trace_id=trace_id)
    return {"due_tasks": due, **result}


@shared_task(
    base=TraceTask,
    bind=True,
    acks_late=True,
    name="apps.archives.destroy_instance_by_admin",
)
def destroy_instance_by_admin(
    _task: Any,
    *,
    instance_id: str,
    actor_id: str,
    expected_version: int,
    reason: str,
    trace_id: str = "",
) -> str:
    actor = User.objects.get(public_id=actor_id)
    try:
        instance = destroy_instance_as_admin(
            instance_id=instance_id,
            actor=actor,
            expected_version=expected_version,
            reason=reason,
            context=worker_context(trace_id=trace_id, actor_ref=actor.public_id),
        )
    except Exception as exc:
        append_failure(
            failure_type="ADMIN_RUNTIME_DESTROY",
            subject_type="PROVISIONING_INSTANCE",
            subject_ref=instance_id,
            error_code=getattr(exc, "code", "ADMIN_RUNTIME_DESTROY_FAILED"),
            message=str(exc),
            detail={"reason": reason},
            retryable=True,
            trace_id=trace_id,
        )
        raise
    return instance.public_id
