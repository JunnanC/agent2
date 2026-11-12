from typing import Any

from celery import shared_task

from apps.core.tasks import TraceTask

from .services import (
    execute_archive_job,
    purge_expired_archive_objects,
    reconcile_archives,
)


@shared_task(base=TraceTask, bind=True, acks_late=True, name="apps.archives.run_archive_job")
def run_archive_job(_task: Any, *, job_id: str, trace_id: str = "") -> str:
    return execute_archive_job(job_id=job_id, trace_id=trace_id).public_id


@shared_task(base=TraceTask, bind=True, acks_late=True, name="apps.archives.reconcile")
def reconcile_archive_state(_task: Any, *, trace_id: str = "") -> dict[str, int]:
    return reconcile_archives(trace_id=trace_id)


@shared_task(base=TraceTask, bind=True, acks_late=True, name="apps.archives.purge_retention")
def purge_archive_retention(_task: Any, *, trace_id: str = "") -> dict[str, int]:
    return purge_expired_archive_objects(trace_id=trace_id)


@shared_task(base=TraceTask, bind=True, acks_late=True, name="apps.archives.reconcile_course")
def reconcile_course_archives(_task: Any, *, course_id: str, trace_id: str = "") -> dict[str, int]:
    from apps.experiments.assessment_workers import archive_closed_assessments
    archive_closed_assessments()
    return reconcile_archives(trace_id=trace_id)
