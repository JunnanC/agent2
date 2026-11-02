from django.http import HttpRequest, HttpResponse
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest

from apps.core.models import CompensationTask, OutboxDelivery

OUTBOX_DELIVERIES = Gauge("outbox_deliveries", "Outbox deliveries by state", ("status",))
COMPENSATION_TASKS = Gauge("compensation_tasks", "Compensation tasks by state", ("status",))


def metrics(_request: HttpRequest) -> HttpResponse:
    try:
        for status, _label in OutboxDelivery.Status.choices:
            OUTBOX_DELIVERIES.labels(status=status).set(
                OutboxDelivery.objects.filter(status=status).count()
            )
        for status, _label in CompensationTask.Status.choices:
            COMPENSATION_TASKS.labels(status=status).set(
                CompensationTask.objects.filter(status=status).count()
            )
    except Exception:
        # Metrics remain available while migrations or MySQL are unavailable.
        pass
    return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)
