import json
import uuid
from collections.abc import Callable, Iterable
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from redis import Redis

from .audit import append_failure
from .concurrency import compare_and_swap
from .models import OutboxDelivery, OutboxEvent
from .redaction import redact

RELAY_DESTINATION = "redis-stream"


def backoff_seconds(attempt: int) -> int:
    return min(2 ** max(attempt - 1, 0), 900)


def append_outbox_event(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_ref: str,
    payload: dict[str, Any],
    trace_id: str,
    destinations: Iterable[str] = (RELAY_DESTINATION,),
) -> OutboxEvent:
    event = OutboxEvent.objects.create(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_ref=aggregate_ref,
        payload=redact(payload),
        trace_id=trace_id,
    )
    for destination in destinations:
        OutboxDelivery.objects.create(event=event, destination=destination)
    return event


def enqueue_relay_after_commit(*, trace_id: str) -> None:
    from .tasks import relay_outbox

    transaction.on_commit(lambda: relay_outbox.apply_async(kwargs={"trace_id": trace_id}))


def claim_deliveries(*, batch_size: int = 100, lease_seconds: int = 60) -> list[int]:
    now = timezone.now()
    token = uuid.uuid4()
    with transaction.atomic():
        queryset = (
            OutboxDelivery.objects.select_for_update(skip_locked=True)
            .filter(destination=RELAY_DESTINATION)
            .filter(
                Q(status__in=(OutboxDelivery.Status.PENDING, OutboxDelivery.Status.RETRY))
                | Q(status=OutboxDelivery.Status.IN_FLIGHT, lease_until__lt=now)
            )
            .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
            .order_by("created_at")[:batch_size]
        )
        claimed: list[int] = []
        for delivery in queryset:
            current = compare_and_swap(
                OutboxDelivery,
                pk=delivery.pk,
                expected_version=delivery.row_version,
                changes={
                    "status": OutboxDelivery.Status.IN_FLIGHT,
                    "lease_token": token,
                    "lease_until": now + timedelta(seconds=lease_seconds),
                    "attempt_count": delivery.attempt_count + 1,
                },
            )
            claimed.append(current.pk)
        return claimed


def _redis_client() -> Redis:
    return Redis.from_url(settings.REDIS_URL, decode_responses=True)


def deliver_claimed(delivery_id: object, *, client: Redis | None = None) -> None:
    delivery = OutboxDelivery.objects.select_related("event").get(pk=delivery_id)
    if delivery.status != OutboxDelivery.Status.IN_FLIGHT:
        return
    event = delivery.event
    redis_client = client or _redis_client()
    try:
        redis_client.xadd(
            settings.OUTBOX_REDIS_STREAM,
            {
                "event_id": str(event.pk),
                "event_type": event.event_type,
                "aggregate_type": event.aggregate_type,
                "aggregate_ref": event.aggregate_ref,
                "payload": json.dumps(
                    event.payload,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "trace_id": event.trace_id,
                "occurred_at": event.created_at.isoformat(),
            },
            maxlen=settings.OUTBOX_REDIS_MAXLEN,
            approximate=True,
        )
    except Exception as exc:
        _record_delivery_failure(delivery, exc)
        raise
    compare_and_swap(
        OutboxDelivery,
        pk=delivery.pk,
        expected_version=delivery.row_version,
        changes={
            "status": OutboxDelivery.Status.DELIVERED,
            "delivered_at": timezone.now(),
            "lease_token": None,
            "lease_until": None,
            "last_error_code": "",
            "last_error_masked": "",
        },
    )


def _record_delivery_failure(delivery: OutboxDelivery, exc: Exception) -> None:
    next_status = (
        OutboxDelivery.Status.DEAD
        if delivery.attempt_count >= delivery.max_attempts
        else OutboxDelivery.Status.RETRY
    )
    next_attempt = (
        None
        if next_status == OutboxDelivery.Status.DEAD
        else timezone.now() + timedelta(seconds=backoff_seconds(delivery.attempt_count))
    )
    failure = append_failure(
        failure_type="OUTBOX_DELIVERY",
        subject_type="OUTBOX_EVENT",
        subject_ref=str(delivery.event_id),
        error_code="OUTBOX_DELIVERY_FAILED",
        message=str(redact(str(exc))),
        detail={"destination": delivery.destination},
        retryable=next_status != OutboxDelivery.Status.DEAD,
        trace_id=delivery.event.trace_id,
    )
    compare_and_swap(
        OutboxDelivery,
        pk=delivery.pk,
        expected_version=delivery.row_version,
        changes={
            "status": next_status,
            "next_attempt_at": next_attempt,
            "lease_token": None,
            "lease_until": None,
            "last_error_code": failure.error_code,
            "last_error_masked": failure.message_masked,
        },
    )


def consume_once(
    *,
    event_id: object,
    consumer: str,
    handler: Callable[[OutboxEvent], None],
) -> bool:
    destination = f"consumer:{consumer}"
    with transaction.atomic():
        delivery, _ = OutboxDelivery.objects.select_for_update().get_or_create(
            event_id=event_id,
            destination=destination,
            defaults={"status": OutboxDelivery.Status.PENDING},
        )
        if delivery.status == OutboxDelivery.Status.DELIVERED:
            return False
        event = OutboxEvent.objects.get(pk=event_id)
        handler(event)
        compare_and_swap(
            OutboxDelivery,
            pk=delivery.pk,
            expected_version=delivery.row_version,
            changes={
                "status": OutboxDelivery.Status.DELIVERED,
                "delivered_at": timezone.now(),
            },
        )
        return True
