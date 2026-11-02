from django.test import TestCase

from apps.accounts.tests.helpers import create_user
from apps.core.models import OutboxDelivery, OutboxEvent
from apps.courses.services import ActorContext
from apps.notifications.models import Notification, Preference
from apps.notifications.services import consume_notification_event, mark_read, update_preference


class NotificationDeliveryTests(TestCase):
    def setUp(self) -> None:
        self.user = create_user(email="notify-p13@example.edu", username="notify-p13")

    def test_consumer_destination_and_notification_unique_key_are_idempotent(self) -> None:
        event = OutboxEvent.objects.create(
            event_type="courses.course.published",
            aggregate_type="course",
            aggregate_ref="course-p13",
            payload={"user_id": self.user.public_id, "portal": "USER", "title": "课程已发布"},
            trace_id="notify-trace",
        )
        self.assertTrue(consume_notification_event(event_id=event.pk))
        self.assertFalse(consume_notification_event(event_id=event.pk))
        self.assertEqual(Notification.objects.filter(account=self.user).count(), 1)
        self.assertEqual(
            OutboxDelivery.objects.filter(
                event=event, destination="consumer:notifications"
            ).count(),
            1,
        )

    def test_read_and_preference_updates_use_versioned_rows(self) -> None:
        event = OutboxEvent.objects.create(
            event_type="tasks.task.assigned",
            aggregate_type="task",
            aggregate_ref="task-p13",
            payload={"user_id": self.user.public_id, "portal": "USER"},
            trace_id="notify-trace",
        )
        consume_notification_event(event_id=event.pk)
        notification = Notification.objects.get(account=self.user)
        read = mark_read(
            item=notification,
            expected_version=notification.row_version,
            context=ActorContext(self.user.public_id, "USER", "notify-trace"),
        )
        self.assertIsNotNone(read.read_at)
        preference = update_preference(
            actor=self.user,
            portal="USER",
            data={"muted_kinds": ["tasks.task.assigned"]},
        )
        self.assertEqual(preference.muted_kinds, ["tasks.task.assigned"])
        updated = update_preference(
            actor=self.user,
            portal="USER",
            data={"digest_enabled": True},
            expected_version=preference.row_version,
        )
        self.assertTrue(updated.digest_enabled)
        self.assertEqual(Preference.objects.get(account=self.user).row_version, 2)
