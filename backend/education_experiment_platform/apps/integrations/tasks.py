from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from apps.core.tasks import TraceTask

from .models import WebhookDelivery
from .services import deliver_webhook


@shared_task(
    base=TraceTask,
    bind=True,
    acks_late=True,
    name="apps.integrations.deliver_due_webhooks",
)
def deliver_due_webhooks(_task: TraceTask, *, trace_id: str = "", limit: int = 100) -> int:
    now = timezone.now()
    rows = WebhookDelivery.objects.filter(
        Q(status=WebhookDelivery.Status.PENDING)
        | Q(status=WebhookDelivery.Status.RETRY, next_retry_at__lte=now)
    ).order_by("created_at")[: max(1, min(limit, 500))]
    delivered = 0
    for item in rows:
        deliver_webhook(delivery=item, trace_id=trace_id)
        delivered += 1
    return delivered
