import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.core.concurrency import compare_and_swap
from apps.core.models import OutboxEvent
from apps.core.outbox import consume_once
from apps.courses.services import ActorContext

from .metrics import NOTIFICATIONS_TOTAL
from .models import Notification, Preference

logger = logging.getLogger(__name__)


def _targets(event: OutboxEvent) -> list[tuple[User, str]]:
    payload = event.payload or {}
    portal = str(payload.get("portal", "USER"))
    values = [payload.get("user_id"), payload.get("student_id"), payload.get("actor_id")]
    result: list[tuple[User, str]] = []
    for value in dict.fromkeys(str(item) for item in values if item):
        user = User.objects.filter(public_id=value).first()
        if user:
            result.append((user, portal))
    return result


@transaction.atomic
def create_notifications_for_event(event: OutboxEvent) -> int:
    payload = event.payload or {}
    kind = event.event_type
    created = 0
    for account, portal in _targets(event):
        preference = Preference.objects.filter(account=account, portal=portal).first()
        if preference and kind in preference.muted_kinds:
            continue
        _, made = Notification.objects.get_or_create(
            account=account,
            portal=portal,
            source_event_id=str(event.id),
            kind=kind,
            defaults={
                "title": str(payload.get("title", "平台通知")),
                "body_masked": str(payload.get("message", payload.get("body", "有新的平台动态"))),
                "link_url": str(payload.get("link_url", "")),
                "course_ref": str(payload.get("course_id", "")),
                "task_ref": str(payload.get("task_id", "")),
                "scope": {"actor_ref": account.public_id, "portal": portal},
            },
        )
        if made:
            created += 1
            NOTIFICATIONS_TOTAL.labels(kind=kind, result="CREATED").inc()
    return created


def consume_notification_event(*, event_id: object) -> bool:
    event = OutboxEvent.objects.get(pk=event_id)
    return consume_once(
        event_id=event.id, consumer="notifications", handler=create_notifications_for_event
    )


@transaction.atomic
def mark_read(*, item: Notification, expected_version: int, context: ActorContext) -> Notification:
    if item.read_at is None:
        item = compare_and_swap(
            Notification,
            pk=item.pk,
            expected_version=expected_version,
            changes={"read_at": timezone.now()},
        )
        NOTIFICATIONS_TOTAL.labels(kind=item.kind, result="READ").inc()
    return item


@transaction.atomic
def update_preference(
    *, actor: User, portal: str, data: dict[str, Any], expected_version: int | None = None
) -> Preference:
    item, created = Preference.objects.get_or_create(account=actor, portal=portal, defaults=data)
    if created:
        return item
    if expected_version is None:
        from apps.core.errors import PreconditionRequired

        raise PreconditionRequired()
    return compare_and_swap(Preference, pk=item.pk, expected_version=expected_version, changes=data)
