from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.models import OutboxEvent
from apps.courses.models import Course, Enrollment
from apps.experiments.events import (
    PUBLICATION_CLOSED,
    PUBLICATION_FAILED,
    PUBLICATION_PUBLISHED,
    TASK_ASSIGNED,
)
from apps.experiments.models import ExperimentTask, TaskPublication
from apps.experiments.services import publish_publication
from apps.experiments.tasks import _record_publication_failure
from apps.experiments.tests.helpers import (
    context,
    create_domain,
    create_draft_publication,
    create_enrollment,
)
from apps.notifications.models import Notification, Preference
from apps.notifications.services import (
    DEADLINE_REMINDER_KIND,
    backfill_notification_content,
    consume_notification_event,
    create_notifications_for_event,
    notify_ended_publications,
    remind_unfinished_experiments,
)


@override_settings(NOTIFICATION_DEADLINE_REMINDER_HOURS=24)
class ExperimentNotificationTests(TestCase):
    def setUp(self) -> None:
        self.owner, self.course, version, rubric = create_domain(suffix="notices")
        self.enrollment = create_enrollment(self.course, suffix="notice-student")
        self.publication = create_draft_publication(
            owner=self.owner,
            course=self.course,
            template_version=version,
            rubric_version=rubric,
            suffix="完成冒泡排序",
        )
        publish_publication(
            course_id=self.course.public_id,
            publication_id=self.publication.public_id,
            actor=self.owner,
            expected_version=self.publication.row_version,
            selected_ids=[],
            context=context(self.owner),
        )
        self.task = ExperimentTask.objects.get(publication=self.publication)
        self.now = timezone.now()
        self.deadline = self.now + timedelta(hours=12)
        ExperimentTask.objects.filter(pk=self.task.pk).update(effective_deadline=self.deadline)

    def test_real_publication_event_creates_descriptive_notification_once(self) -> None:
        event = OutboxEvent.objects.get(event_type=TASK_ASSIGNED, aggregate_ref=self.task.public_id)
        self.assertEqual(event.payload["experiment_title"], self.publication.title)
        self.assertEqual(event.payload["course_name"], self.course.title)
        self.assertTrue(consume_notification_event(event_id=event.pk))
        self.assertFalse(consume_notification_event(event_id=event.pk))
        notice = Notification.objects.get(account=self.enrollment.student)
        self.assertIn(f"教师发布了新实验：{self.publication.title}", notice.body_masked)
        self.assertIn(self.course.title, notice.body_masked)
        self.assertIn("截止时间：", notice.body_masked)
        self.assertEqual(notice.task_ref, self.task.public_id)
        self.assertEqual(notice.link_url, f"/experiments/{self.task.public_id}")

    def test_publication_success_and_failure_notify_course_teachers(self) -> None:
        published = OutboxEvent.objects.get(
            event_type=PUBLICATION_PUBLISHED, aggregate_ref=self.publication.public_id
        )
        self.assertEqual(create_notifications_for_event(published), 1)
        success = Notification.objects.get(account=self.owner, kind=PUBLICATION_PUBLISHED)
        self.assertIn("已发布", success.body_masked)
        self.assertEqual(success.portal, "TEACHING")

        TaskPublication.objects.filter(pk=self.publication.pk).update(
            status=TaskPublication.Status.PUBLISHING
        )
        _record_publication_failure(
            self.publication.public_id, "publication-failure", RuntimeError()
        )
        failed = OutboxEvent.objects.get(
            event_type=PUBLICATION_FAILED, aggregate_ref=self.publication.public_id
        )
        self.assertEqual(create_notifications_for_event(failed), 1)
        failure = Notification.objects.get(account=self.owner, kind=PUBLICATION_FAILED)
        self.assertIn("发布失败", failure.title)
        self.assertEqual(failure.link_url, f"/courses/{self.course.public_id}/publishing")

    def test_ended_publication_notice_reports_completed_count_once(self) -> None:
        ExperimentTask.objects.filter(pk=self.task.pk).update(
            status=ExperimentTask.Status.COMPLETED,
            completed_at=self.now,
        )
        TaskPublication.objects.filter(pk=self.publication.pk).update(
            window_start=self.now - timedelta(minutes=1),
            window_end=self.now,
            assignment_deadline=None,
        )

        self.assertEqual(notify_ended_publications(now=self.now), 1)
        self.assertEqual(notify_ended_publications(now=self.now), 0)
        notice = Notification.objects.get(account=self.owner, kind=PUBLICATION_CLOSED)
        self.assertIn("已完成 1 / 1 人", notice.body_masked)
        self.assertEqual(notice.portal, "TEACHING")
        close_event = OutboxEvent.objects.create(
            event_type=PUBLICATION_CLOSED,
            aggregate_type="task_publication",
            aggregate_ref=self.publication.public_id,
            trace_id="publication-ended-event",
            payload={"publication_id": self.publication.public_id},
        )
        self.assertEqual(create_notifications_for_event(close_event), 0)

    def test_legacy_event_resolves_names_from_task(self) -> None:
        event = OutboxEvent.objects.create(
            event_type=TASK_ASSIGNED,
            aggregate_type="experiment_task",
            aggregate_ref=self.task.public_id,
            trace_id="legacy-notice",
            payload={
                "task_id": self.task.public_id,
                "student_id": self.enrollment.student.public_id,
            },
        )
        self.assertEqual(create_notifications_for_event(event), 1)
        notice = Notification.objects.get(account=self.enrollment.student)
        self.assertIn(self.publication.title, notice.body_masked)
        self.assertIn(self.course.title, notice.body_masked)

    def test_backfill_preserves_read_state_and_is_idempotent(self) -> None:
        notice = Notification.objects.create(
            account=self.enrollment.student,
            portal="USER",
            kind=TASK_ASSIGNED,
            source_event_id="legacy",
            title="平台通知",
            body_masked="有新的平台动态",
            task_ref=self.task.public_id,
            read_at=self.now,
        )
        self.assertEqual(backfill_notification_content(), 1)
        self.assertEqual(backfill_notification_content(), 0)
        notice.refresh_from_db()
        self.assertEqual(notice.read_at, self.now)
        self.assertEqual(notice.row_version, 2)
        self.assertIn(self.publication.title, notice.body_masked)

    def test_upcoming_reminder_is_descriptive_and_idempotent(self) -> None:
        self.assertEqual(remind_unfinished_experiments(now=self.now), 1)
        self.assertEqual(remind_unfinished_experiments(now=self.now), 0)
        notice = Notification.objects.get(kind=DEADLINE_REMINDER_KIND)
        self.assertIn(f"实验未完成：{self.publication.title}", notice.body_masked)
        self.assertIn(self.course.title, notice.body_masked)
        self.assertEqual(notice.account, self.enrollment.student)
        self.assertIsNone(notice.read_at)

    def test_submitted_and_terminal_statuses_are_not_reminded(self) -> None:
        for status in [
            "UNDER_REVIEW",
            "APPROVED",
            "ARCHIVING",
            "COMPLETED",
            "CANCELLED",
            "EXPIRED",
            "FAILED",
        ]:
            with self.subTest(status=status):
                ExperimentTask.objects.filter(pk=self.task.pk).update(status=status)
                self.assertEqual(remind_unfinished_experiments(now=self.now), 0)

    def test_unfinished_and_rejected_tasks_are_reminded(self) -> None:
        for index, status in enumerate([
            "ASSIGNED",
            "IN_PROGRESS",
            "REPORT_DRAFT",
        ]):
            with self.subTest(status=status):
                # A distinct effective deadline creates a distinct legitimate reminder.
                ExperimentTask.objects.filter(pk=self.task.pk).update(
                    status=status,
                    effective_deadline=self.deadline + timedelta(minutes=index),
                )
                self.assertEqual(remind_unfinished_experiments(now=self.now), 1)

    def test_retryable_failure_can_receive_reminder(self) -> None:
        ExperimentTask.objects.filter(pk=self.task.pk).update(
            status="FAILED",
            current_failure={"retryable": True},
        )
        self.assertEqual(remind_unfinished_experiments(now=self.now), 1)

    def test_deadline_window_boundaries(self) -> None:
        for hours, expected in [(-1, 0), (0, 0), (25, 0), (24, 1)]:
            with self.subTest(hours=hours):
                ExperimentTask.objects.filter(pk=self.task.pk).update(
                    effective_deadline=self.now + timedelta(hours=hours),
                )
                self.assertEqual(remind_unfinished_experiments(now=self.now), expected)

    def test_extension_uses_effective_deadline_and_can_remind_again(self) -> None:
        self.assertEqual(remind_unfinished_experiments(now=self.now), 1)
        extended = self.now + timedelta(hours=48)
        ExperimentTask.objects.filter(pk=self.task.pk).update(effective_deadline=extended)
        self.assertEqual(remind_unfinished_experiments(now=self.now), 0)
        self.assertEqual(remind_unfinished_experiments(now=extended - timedelta(hours=23)), 1)
        self.assertEqual(remind_unfinished_experiments(now=extended - timedelta(hours=22)), 0)

    def test_null_effective_deadline_falls_back_to_publication_window(self) -> None:
        ExperimentTask.objects.filter(pk=self.task.pk).update(effective_deadline=None)
        TaskPublication.objects.filter(pk=self.publication.pk).update(
            window_end=self.deadline,
            assignment_deadline=self.deadline,
        )
        self.assertEqual(remind_unfinished_experiments(now=self.now), 1)

    def test_inactive_enrollment_or_closed_publication_or_course_are_excluded(self) -> None:
        Enrollment.objects.filter(pk=self.enrollment.pk).update(status=Enrollment.Status.DROPPED)
        self.assertEqual(remind_unfinished_experiments(now=self.now), 0)
        Enrollment.objects.filter(pk=self.enrollment.pk).update(status=Enrollment.Status.ACTIVE)
        TaskPublication.objects.filter(pk=self.publication.pk).update(
            status=TaskPublication.Status.CLOSED
        )
        self.assertEqual(remind_unfinished_experiments(now=self.now), 0)
        TaskPublication.objects.filter(pk=self.publication.pk).update(
            status=TaskPublication.Status.PUBLISHED
        )
        Course.objects.filter(pk=self.course.pk).update(status=Course.Status.CLOSED)
        self.assertEqual(remind_unfinished_experiments(now=self.now), 0)

    def test_preferences_suppress_reminders(self) -> None:
        preference = Preference.objects.create(
            account=self.enrollment.student,
            portal="USER",
            muted_kinds=[DEADLINE_REMINDER_KIND],
        )
        self.assertEqual(remind_unfinished_experiments(now=self.now), 0)
        Preference.objects.filter(pk=preference.pk).update(
            muted_kinds=[], channels={"in_app": False}
        )
        self.assertEqual(remind_unfinished_experiments(now=self.now), 0)

    def test_assignment_respects_in_app_preference(self) -> None:
        Preference.objects.create(
            account=self.enrollment.student,
            portal="USER",
            channels={"in_app": False},
        )
        event = OutboxEvent.objects.get(event_type=TASK_ASSIGNED, aggregate_ref=self.task.public_id)
        self.assertEqual(create_notifications_for_event(event), 0)
