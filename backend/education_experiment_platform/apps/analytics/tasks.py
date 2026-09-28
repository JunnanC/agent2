from contextlib import suppress

from celery import shared_task

from apps.core.audit import append_failure
from apps.core.tasks import TraceTask

from .metrics import ANALYTICS_PROJECTION_RUNS
from .services import rebuild_course_analytics


def _rebuild_or_record_failure(*, course_id: str | None, trace_id: str) -> int:
    try:
        return rebuild_course_analytics(course_id=course_id, trace_id=trace_id)
    except Exception as exc:
        ANALYTICS_PROJECTION_RUNS.labels(kind="course", result="FAILED").inc()
        with suppress(Exception):
            append_failure(
                failure_type="ANALYTICS_PROJECTION",
                subject_type="COURSE" if course_id else "ANALYTICS_PROJECTION",
                subject_ref=course_id or "all",
                error_code="ANALYTICS_PROJECTION_FAILED",
                message=str(exc),
                detail={"course_id": course_id or "", "trace_id": trace_id},
                retryable=True,
                trace_id=trace_id,
            )
        raise


@shared_task(
    base=TraceTask, bind=True, acks_late=True, name="apps.analytics.rebuild_course_analytics"
)
def rebuild_analytics(_task: TraceTask, *, course_id: str | None = None, trace_id: str = "") -> int:
    return _rebuild_or_record_failure(course_id=course_id, trace_id=trace_id)


@shared_task(base=TraceTask, bind=True, acks_late=True, name="apps.analytics.refresh_projection")
def refresh_projection(_task: TraceTask, *, trace_id: str = "") -> int:
    return _rebuild_or_record_failure(course_id=None, trace_id=trace_id)


@shared_task(
    base=TraceTask, bind=True, acks_late=True, name="apps.analytics.replay_projection"
)
def replay_projection(
    _task: TraceTask, *, course_id: str | None = None, trace_id: str = ""
) -> int:
    """Replay the deterministic MySQL-backed projection for one course or all courses."""
    return _rebuild_or_record_failure(course_id=course_id, trace_id=trace_id)
