from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.tests.helpers import create_user, grant_teacher
from apps.analytics.models import CourseDaily, CourseQualitySnapshot, StudentRiskSignal
from apps.analytics.services import rebuild_course_analytics, resolve_risk_signal
from apps.core.errors import RowVersionConflict
from apps.courses.services import ActorContext
from apps.courses.tests.helpers import create_draft_course


class AnalyticsProjectionTests(TestCase):
    def setUp(self) -> None:
        self.teacher = create_user(email="teacher-p13@example.edu", username="teacher-p13")
        grant_teacher(self.teacher)
        self.student = create_user(email="student-p13@example.edu", username="student-p13")
        self.course = create_draft_course(self.teacher, code="P13-ANALYTICS")

    def test_rebuild_is_idempotent_and_keeps_projection_metadata(self) -> None:
        self.assertEqual(rebuild_course_analytics(course_id=self.course.public_id), 1)
        self.assertEqual(rebuild_course_analytics(course_id=self.course.public_id), 1)
        daily = CourseDaily.objects.get(course=self.course)
        quality = CourseQualitySnapshot.objects.get(course=self.course)
        self.assertEqual(CourseDaily.objects.filter(course=self.course).count(), 1)
        self.assertEqual(CourseQualitySnapshot.objects.filter(course=self.course).count(), 1)
        self.assertEqual(daily.projection_version, "p13-v1")
        self.assertTrue(daily.source_cursor == "" or "|" in daily.source_cursor)
        self.assertEqual(quality.metrics["task_total"], 0)

    def test_teacher_can_resolve_risk_with_cas_and_stale_version_is_rejected(self) -> None:
        signal = StudentRiskSignal.objects.create(
            course=self.course,
            student=self.student,
            kind="MANUAL_TEST",
            severity="HIGH",
            explanation_masked="test explanation",
            source_digest="a" * 64,
            projection_version="p13-v1",
            calculated_at=timezone.now(),
            valid_until=timezone.now() + timedelta(days=1),
        )
        context = ActorContext(self.teacher.public_id, "TEACHING", "p13-trace")
        updated = resolve_risk_signal(
            signal_id=signal.public_id,
            actor=self.teacher,
            status=StudentRiskSignal.Status.ACKNOWLEDGED,
            expected_version=signal.row_version,
            context=context,
            reason="已联系学生",
        )
        self.assertEqual(updated.status, StudentRiskSignal.Status.ACKNOWLEDGED)
        with self.assertRaises(RowVersionConflict):
            resolve_risk_signal(
                signal_id=signal.public_id,
                actor=self.teacher,
                status=StudentRiskSignal.Status.CLOSED,
                expected_version=signal.row_version,
                context=context,
            )
