from typing import Any

from celery import shared_task

from apps.accounts.models import User
from apps.core.audit import append_failure
from apps.core.tasks import TraceTask

from .services import (
    destroy_instance_as_admin,
    destroy_orphan_as_admin,
    execute_archive_job,
    purge_expired_archive_objects,
    purge_expired_runtime_objects,
    purge_expired_runtime_resources,
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


@shared_task(base=TraceTask, bind=True, acks_late=True, name="apps.archives.purge_retention")
def purge_archive_retention(_task: Any, *, trace_id: str = "") -> dict[str, int]:
    archive = purge_expired_archive_objects(trace_id=trace_id)
    runtime = purge_expired_runtime_objects(trace_id=trace_id)
    resources = purge_expired_runtime_resources(trace_id=trace_id)
    return {
        "purged": archive["purged"] + runtime["purged"] + resources["purged"],
        "skipped": archive["skipped"] + runtime["skipped"] + resources["skipped"],
        "failed": archive["failed"] + runtime["failed"] + resources["failed"],
        "archive_purged": archive["purged"],
        "runtime_purged": runtime["purged"],
        "resource_purged": resources["purged"],
        "resource_failed": resources["failed"],
    }


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
        error_code = getattr(exc, "code", "ADMIN_RUNTIME_DESTROY_FAILED")
        append_failure(
            failure_type="ADMIN_RUNTIME_DESTROY",
            subject_type="PROVISIONING_INSTANCE",
            subject_ref=instance_id,
            error_code=error_code,
            message=error_code,
            detail={"reason": reason},
            retryable=True,
            trace_id=trace_id,
        )
        raise
    return instance.public_id


@shared_task(
    base=TraceTask,
    bind=True,
    acks_late=True,
    name="apps.archives.destroy_orphan_by_admin",
)
def destroy_orphan_by_admin(
    _task: Any,
    *,
    orphan_ref: str,
    actor_id: str,
    reason: str,
    trace_id: str = "",
) -> str:
    actor = User.objects.get(public_id=actor_id)
    try:
        destroy_orphan_as_admin(
            orphan_ref=orphan_ref, actor=actor, reason=reason, trace_id=trace_id
        )
    except Exception as exc:
        error_code = getattr(exc, "code", "ADMIN_RUNTIME_ORPHAN_DESTROY_FAILED")
        append_failure(
            failure_type="ADMIN_RUNTIME_ORPHAN_DESTROY",
            subject_type="RUNTIME_ORPHAN",
            subject_ref=orphan_ref.removeprefix("external:"),
            error_code=error_code,
            message=error_code,
            detail={"reason": reason},
            retryable=True,
            trace_id=trace_id,
        )
        raise
    return orphan_ref
