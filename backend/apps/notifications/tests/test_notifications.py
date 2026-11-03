from django.test import TestCase

from apps.accounts.tests.helpers import create_user
from apps.core.models import OutboxDelivery, OutboxEvent
from apps.courses.services import ActorContext
from apps.notifications.models import Notification, Preference
from apps.notifications.services import (
    backfill_notification_content,
    consume_notification_event,
    mark_read,
    update_preference,
)


class NotificationDeliveryTests(TestCase):
    def setUp(self) -> None:
        self.user = create_user(
            email="notify-notifications@example.edu", username="notify-notifications"
        )

    def test_consumer_destination_and_notification_unique_key_are_idempotent(self) -> None:
        event = OutboxEvent.objects.create(
            event_type="courses.course.published",
            aggregate_type="course",
            aggregate_ref="course-notifications",
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
            aggregate_ref="task-notifications",
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

    def test_system_events_have_specific_body_and_historical_messages_are_repaired(self) -> None:
        for kind, expected in [
            ("account.created", "你的平台账号已创建"),
            ("teacher.qualification.changed", "你的教师资格信息已更新"),
            ("governance.quota.reserved", "平台已为实验预留所需资源配额"),
        ]:
            with self.subTest(kind=kind):
                event = OutboxEvent.objects.create(
                    event_type=kind,
                    aggregate_type="account",
                    aggregate_ref=self.user.public_id,
                    payload={"user_id": self.user.public_id},
                    trace_id="system-notice",
                )
                consume_notification_event(event_id=event.pk)
                notice = Notification.objects.get(source_event_id=str(event.pk))
                self.assertIn(expected, notice.body_masked)
                Notification.objects.filter(pk=notice.pk).update(body_masked="有新的平台动态")
                self.assertEqual(backfill_notification_content(), 1)
                notice.refresh_from_db()
                self.assertIn(expected, notice.body_masked)
