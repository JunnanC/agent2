from typing import Any

from celery import shared_task
from django.conf import settings
from django.db import transaction

from apps.core.audit import append_failure
from apps.core.compensation import create_compensation
from apps.core.concurrency import compare_and_swap
from apps.core.tasks import run_compensations

from .assessment_workers import (  # noqa: F401
    archive_closed_assessments,
    cleanup_assessment_objects,
    cleanup_assessment_resources,
    dispatch_assessments,
    run_assessment_job,
)
from .models import TaskPublication
from .services import assign_late_enrollment_task as assign_late_enrollment_service
from .services import (
    execute_publication_assignment,
    execute_publication_assignment_chunk,
    publication_audience_enrollment_ids,
)


def _context(trace_id: str) -> Any:
    return type(
        "TaskContext",
        (),
        {"trace_id": trace_id, "portal": "WORKER", "actor_ref": "worker"},
    )()


def _record_publication_failure(publication_id: str, trace_id: str, exc: Exception) -> None:
    with transaction.atomic():
        publication = TaskPublication.objects.select_for_update().filter(
            public_id=publication_id
        ).first()
        if publication is None or publication.status != TaskPublication.Status.PUBLISHING:
            return
        compare_and_swap(
            TaskPublication,
            pk=publication.pk,
            expected_version=publication.row_version,
            changes={
                "status": TaskPublication.Status.PUBLISH_FAILED,
                "publication_error": {
                    "code": "PUBLICATION_ASSIGNMENT_FAILED",
                    "retryable": True,
                },
            },
        )
        failure = append_failure(
            failure_type="EXPERIMENT_PUBLICATION_ASSIGNMENT",
            subject_type="TASK_PUBLICATION",
            subject_ref=publication_id,
            error_code="PUBLICATION_ASSIGNMENT_FAILED",
            message=str(exc),
            detail={"publication_id": publication_id},
            retryable=True,
            trace_id=trace_id,
        )
        compensation = create_compensation(
            task_type="RETRY_EXPERIMENT_PUBLICATION",
            subject_type="TASK_PUBLICATION",
            subject_ref=publication_id,
            payload={"failure_id": failure.pk},
            trace_id=trace_id,
            max_attempts=3,
        )
        transaction.on_commit(
            lambda: run_compensations.apply_async(
                kwargs={"trace_id": trace_id},
                queue="q_compensate",
                task_id=f"p06-compensation-{compensation.public_id}",
            )
        )


@shared_task(bind=True, max_retries=2, queue="q_default", acks_late=True)
def assign_publication_tasks(self: Any, publication_id: str, trace_id: str = "") -> str:
    try:
        publication = TaskPublication.objects.prefetch_related("audience").get(
            public_id=publication_id
        )
        if publication.status != TaskPublication.Status.PUBLISHING:
            return publication.public_id
        enrollment_ids = publication_audience_enrollment_ids(publication)
        chunk_size = max(int(getattr(settings, "PUBLICATION_CHUNK_SIZE", 50)), 1)
        if not enrollment_ids:
            execute_publication_assignment(
                publication_id=publication_id,
                context=_context(trace_id),
            )
        else:
            for offset in range(0, len(enrollment_ids), chunk_size):
                assign_publication_task_batch.delay(
                    publication_id,
                    enrollment_ids[offset : offset + chunk_size],
                    trace_id,
                )
        return publication.public_id
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=2**self.request.retries) from exc
        _record_publication_failure(publication_id, trace_id, exc)
        raise


@shared_task(bind=True, max_retries=2, queue="q_default", acks_late=True)
def assign_publication_task_batch(
    self: Any,
    publication_id: str,
    enrollment_ids: list[str],
    trace_id: str = "",
) -> str:
    try:
        publication = execute_publication_assignment_chunk(
            publication_id=publication_id,
            enrollment_ids=enrollment_ids,
            context=_context(trace_id),
        )
        return publication.public_id
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=2**self.request.retries) from exc
        _record_publication_failure(publication_id, trace_id, exc)
        raise


@shared_task(bind=True, max_retries=2, queue="q_default", acks_late=True)
def assign_late_enrollment_task(
    self: Any, enrollment_id: str, publication_id: str, trace_id: str = ""
) -> str | None:
    try:
        task = assign_late_enrollment_service(
            enrollment_id=enrollment_id,
            publication_id=publication_id,
            context=_context(trace_id),
        )
        return task.public_id if task else None
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=2**self.request.retries) from exc
        append_failure(
            failure_type="EXPERIMENT_LATE_ASSIGNMENT",
            subject_type="ENROLLMENT",
            subject_ref=enrollment_id,
            error_code="LATE_ASSIGNMENT_FAILED",
            message=str(exc),
            detail={"publication_id": publication_id},
            retryable=False,
            trace_id=trace_id,
        )
        raise
