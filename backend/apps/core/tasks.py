import logging
from typing import Any

from celery import Task, shared_task

from education_experiment_platform.logging import portal_var, trace_id_var

from .compensation import claim_compensations, run_compensation
from .outbox import claim_deliveries, deliver_claimed

logger = logging.getLogger(__name__)


class TraceTask(Task):
    abstract = True

    def __call__(self, *args: object, **kwargs: Any) -> Any:
        headers = getattr(self.request, "headers", {}) or {}
        trace_id = str(kwargs.get("trace_id") or headers.get("trace_id") or "")
        portal = str(headers.get("portal") or "")
        trace_token = trace_id_var.set(trace_id)
        portal_token = portal_var.set(portal)
        try:
            return self.run(*args, **kwargs)
        finally:
            portal_var.reset(portal_token)
            trace_id_var.reset(trace_token)


@shared_task(base=TraceTask, bind=True, acks_late=True, name="apps.core.relay_outbox")
def relay_outbox(_task: Task, *, trace_id: str = "") -> int:
    delivered = 0
    for delivery_id in claim_deliveries():
        try:
            deliver_claimed(delivery_id)
        except Exception:
            continue
        delivered += 1
    logger.info(
        "outbox relay completed",
        extra={"action": "outbox.relay", "result": "SUCCEEDED", "delivered": delivered},
    )
    return delivered


@shared_task(base=TraceTask, bind=True, acks_late=True, name="apps.core.run_compensations")
def run_compensations(_task: Task, *, trace_id: str = "") -> int:
    processed = 0
    for task_id in claim_compensations():
        run_compensation(task_id)
        processed += 1
    logger.info(
        "compensation batch completed",
        extra={
            "action": "compensation.run",
            "result": "SUCCEEDED",
            "processed": processed,
        },
    )
    return processed
