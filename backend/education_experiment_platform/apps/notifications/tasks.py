from celery import shared_task

from apps.core.models import OutboxEvent
from apps.core.tasks import TraceTask

from .services import consume_notification_event


@shared_task(base=TraceTask, bind=True, acks_late=True, name="apps.notifications.consume_outbox")
def consume_outbox(_task: TraceTask, *, trace_id: str = "") -> int:
    count = 0
    for event in OutboxEvent.objects.order_by("created_at").iterator():
        try:
            if consume_notification_event(event_id=event.id):
                count += 1
        except Exception:
            continue
    return count
