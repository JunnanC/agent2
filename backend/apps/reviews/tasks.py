from typing import Any

from celery import shared_task

from apps.core.tasks import TraceTask

from .services import (
    execute_ai_score_suggestion,
    execute_auto_check,
    execute_similarity_run,
    purge_expired_similarity_evidence,
)


@shared_task(
    bind=True,
    base=TraceTask,
    acks_late=True,
    max_retries=2,
    queue="q_provision",
    name="apps.reviews.run_auto_check",
)
def run_auto_check(_task: Any, *, run_id: str) -> str:
    result = execute_auto_check(run_id=run_id)
    if result.status == result.Status.QUEUED:
        raise _task.retry(
            exc=RuntimeError("AUTO_CHECK_EXECUTION_RETRY"),
            countdown=2 ** max(0, result.attempt_count - 1),
        )
    return result.public_id


@shared_task(
    bind=True,
    base=TraceTask,
    acks_late=True,
    max_retries=2,
    queue="q_analytics",
    name="apps.reviews.run_similarity_check",
)
def run_similarity_check(_task: Any, *, run_id: str) -> str:
    return execute_similarity_run(run_id=run_id).public_id


@shared_task(
    bind=True,
    base=TraceTask,
    acks_late=True,
    queue="q_agent",
    name="apps.reviews.run_ai_score_suggestion",
)
def run_ai_score_suggestion(_task: Any, *, suggestion_id: str, trace_id: str = "") -> str:
    del trace_id
    return execute_ai_score_suggestion(suggestion_id=suggestion_id).public_id


@shared_task(queue="q_default", name="apps.reviews.purge_similarity_evidence")
def purge_similarity_evidence() -> int:
    return purge_expired_similarity_evidence()
