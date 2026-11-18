from celery import shared_task

from apps.core.models import OutboxEvent
from apps.core.tasks import TraceTask

from .services import consume_notification_event
from .services import notify_ended_publications as send_publication_end_notices
from .services import remind_unfinished_experiments as send_deadline_reminders


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


@shared_task(
    base=TraceTask,
    bind=True,
    acks_late=True,
    name="apps.notifications.remind_unfinished_experiments",
)
def remind_unfinished_experiments(_task: TraceTask, *, trace_id: str = "") -> int:
    return send_deadline_reminders()


@shared_task(
    base=TraceTask,
    bind=True,
    acks_late=True,
    name="apps.notifications.notify_ended_publications",
)
def notify_ended_publications(_task: TraceTask, *, trace_id: str = "") -> int:
    return send_publication_end_notices()
