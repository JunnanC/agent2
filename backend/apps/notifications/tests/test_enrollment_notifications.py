from datetime import timedelta

from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from apps.core.errors import RowVersionConflict
from apps.core.models import OutboxEvent
from apps.courses.events import ENROLLMENT_ENDED, ENROLLMENT_STUDENT_DROPPED
from apps.courses.models import CourseStaff, CourseStaffGrant, Enrollment
from apps.courses.services import (
    ActorContext,
    drop_enrollment,
    remove_enrollment,
    withdraw_application,
)
from apps.courses.tests.helpers import create_draft_course, create_teacher
from apps.experiments.tests.helpers import create_enrollment
from apps.notifications.models import Notification
from apps.notifications.selectors import visible_notifications
from apps.notifications.services import consume_notification_event, create_notifications_for_event


class EnrollmentNotificationTests(TestCase):
    def setUp(self) -> None:
        self.owner = create_teacher(suffix="drop-notice-owner")
        self.course = create_draft_course(self.owner)
        self.enrollment = create_enrollment(self.course, suffix="drop-notice-student")
        self.student = self.enrollment.student
        self.context = ActorContext(self.student.public_id, "USER", "d" * 32)

    def _drop(self) -> Enrollment:
        return drop_enrollment(
            enrollment_id=self.enrollment.public_id, student=self.student,
            expected_version=self.enrollment.row_version, reason="  课程安排冲突  ",
            context=self.context,
        )

    def _assistant(self, suffix: str, *, capability: str, expired: bool = False,
                   revoked: bool = False) -> None:
        teacher = create_teacher(suffix=suffix)
        staff = CourseStaff.objects.create(
            course=self.course, user=teacher, role=CourseStaff.Role.ASSISTANT,
            status=CourseStaff.Status.REVOKED if revoked else CourseStaff.Status.ACTIVE,
            appointed_by=self.owner, appointed_at=timezone.now(),
        )
        CourseStaffGrant.objects.create(
            course_staff=staff, capability=capability, status=CourseStaffGrant.Status.ACTIVE,
            granted_by=self.owner, granted_at=timezone.now(),
            expires_at=timezone.now() - timedelta(days=1) if expired else None,
        )

    def test_drop_is_effective_before_teacher_notification_and_delivery_is_idempotent(self) -> None:
        changed = self._drop()
        self.assertEqual(changed.status, Enrollment.Status.DROPPED)
        self.assertFalse(Notification.objects.exists())
        event = OutboxEvent.objects.get(event_type=ENROLLMENT_STUDENT_DROPPED)
        self.assertEqual(event.payload["teacher_ids"], [self.owner.public_id])
        self.assertEqual(event.payload["reason"], "课程安排冲突")
        self.assertTrue(consume_notification_event(event_id=event.pk))
        self.assertFalse(consume_notification_event(event_id=event.pk))
        self.assertEqual(create_notifications_for_event(event), 0)
        notice = Notification.objects.get(kind=ENROLLMENT_STUDENT_DROPPED)
        self.assertEqual(notice.account, self.owner)
        self.assertEqual(notice.portal, "TEACHING")
        self.assertEqual(notice.title, "学生退课通知")
        self.assertIn(self.student.display_name, notice.body_masked)
        self.assertIn(self.student.username, notice.body_masked)
        self.assertIn(self.course.title, notice.body_masked)
        self.assertIn("课程安排冲突", notice.body_masked)
        self.assertIn("退课时间：", notice.body_masked)
        self.assertIn("退课已生效，无需教师审批", notice.body_masked)
        self.assertEqual(notice.link_url, f"/courses/{self.course.public_id}/enrollments")
        self.assertEqual(notice.course_ref, self.course.public_id)
        self.assertEqual(list(visible_notifications(actor=self.owner, portal="TEACHING")), [notice])
        self.assertFalse(visible_notifications(actor=self.student, portal="TEACHING").exists())
        self.assertFalse(visible_notifications(actor=self.owner, portal="USER").exists())
        # The existing student end-of-enrollment notification is still separate.
        ended = OutboxEvent.objects.get(event_type=ENROLLMENT_ENDED)
        consume_notification_event(event_id=ended.pk)
        self.assertTrue(Notification.objects.filter(
            account=self.student, portal="USER", kind=ENROLLMENT_ENDED,
        ).exists())
        changed.refresh_from_db()
        self.assertEqual(changed.status, Enrollment.Status.DROPPED)

    def test_recipients_require_active_course_enrollment_management_access(self) -> None:
        self._assistant("drop-manager", capability=CourseStaffGrant.Capability.MANAGE_ENROLLMENT)
        self._assistant("drop-viewer", capability=CourseStaffGrant.Capability.VIEW_PROGRESS)
        self._assistant("drop-expired", capability=CourseStaffGrant.Capability.MANAGE_ENROLLMENT,
                        expired=True)
        self._assistant("drop-revoked", capability=CourseStaffGrant.Capability.MANAGE_ENROLLMENT,
                        revoked=True)
        other = create_teacher(suffix="drop-other-course")
        create_draft_course(other, code="OTHER-DROP-COURSE")
        self._drop()
        event = OutboxEvent.objects.get(event_type=ENROLLMENT_STUDENT_DROPPED)
        self.assertEqual(create_notifications_for_event(event), 2)
        self.assertEqual(set(Notification.objects.values_list("account__username", flat=True)),
                         {"drop-notice-owner", "drop-manager"})

    def test_notification_uses_drop_time_snapshot(self) -> None:
        self._drop()
        event = OutboxEvent.objects.get(event_type=ENROLLMENT_STUDENT_DROPPED)
        original_name = self.student.display_name
        original_title = self.course.title
        type(self.student).objects.filter(pk=self.student.pk).update(display_name="后来改名")
        type(self.course).objects.filter(pk=self.course.pk).update(title="后来改课名")
        create_notifications_for_event(event)
        notice = Notification.objects.get(kind=ENROLLMENT_STUDENT_DROPPED)
        self.assertIn(original_name, notice.body_masked)
        self.assertIn(original_title, notice.body_masked)
        self.assertNotIn("后来改", notice.body_masked)

    def test_failed_or_rolled_back_drop_has_no_teacher_event(self) -> None:
        with self.assertRaises(RowVersionConflict):
            drop_enrollment(
                enrollment_id=self.enrollment.public_id, student=self.student,
                expected_version=self.enrollment.row_version + 1, reason="无效版本",
                context=self.context,
            )
        self.assertFalse(OutboxEvent.objects.filter(event_type=ENROLLMENT_STUDENT_DROPPED).exists())
        with self.assertRaises(RuntimeError), transaction.atomic():
            self._drop()
            raise RuntimeError("rollback")
        self.assertFalse(OutboxEvent.objects.filter(event_type=ENROLLMENT_STUDENT_DROPPED).exists())
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, Enrollment.Status.ACTIVE)

    def test_pending_application_withdrawal_does_not_emit_student_drop_notice(self) -> None:
        Enrollment.objects.filter(pk=self.enrollment.pk).update(status=Enrollment.Status.PENDING)
        withdraw_application(
            enrollment_id=self.enrollment.public_id, student=self.student,
            expected_version=self.enrollment.row_version, context=self.context,
        )
        self.assertFalse(OutboxEvent.objects.filter(event_type=ENROLLMENT_STUDENT_DROPPED).exists())

    def test_teacher_removal_does_not_emit_student_drop_notice(self) -> None:
        changed = remove_enrollment(
            course_id=self.course.public_id, enrollment_id=self.enrollment.public_id,
            actor=self.owner, expected_version=self.enrollment.row_version,
            reason="教师移除", context=ActorContext(self.owner.public_id, "TEACHING", "f" * 32),
        )
        self.assertEqual(changed.status, Enrollment.Status.REMOVED)
        self.assertFalse(OutboxEvent.objects.filter(event_type=ENROLLMENT_STUDENT_DROPPED).exists())
