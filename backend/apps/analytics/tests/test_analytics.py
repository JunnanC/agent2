from datetime import timedelta
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.tests.helpers import create_user, grant_teacher
from apps.analytics.models import CourseDaily, CourseQualitySnapshot, StudentRiskSignal
from apps.analytics.observability import operations_summary
from apps.analytics.services import rebuild_course_analytics, resolve_risk_signal
from apps.analytics.views import PlatformAuditLogsView, TeachingAnalyticsSeriesView
from apps.core.errors import RowVersionConflict
from apps.core.models import AuditLog
from apps.courses.services import ActorContext
from apps.courses.tests.helpers import create_draft_course


class AnalyticsProjectionTests(TestCase):
    def setUp(self) -> None:
        self.teacher = create_user(
            email="teacher-analytics@example.edu", username="teacher-analytics"
        )
        grant_teacher(self.teacher)
        self.student = create_user(
            email="student-analytics@example.edu", username="student-analytics"
        )
        self.course = create_draft_course(self.teacher, code="analytics-ANALYTICS")

    @patch("apps.analytics.observability.collect_runtime_inventory")
    def test_operations_summary_collects_runtime_on_worker(self, collect: Mock) -> None:
        collect.delay.return_value.get.return_value = {
            "status": "HEALTHY", "drivers": [], "orphans": {}, "inventory": {}
        }
        summary = operations_summary(trace_id="runtime-trace")
        collect.delay.assert_called_once_with("runtime-trace")
        collect.delay.return_value.get.assert_called_once_with(timeout=15)
        self.assertEqual(summary["runtime"]["status"], "HEALTHY")

        collect.delay.return_value.get.side_effect = TimeoutError("worker unavailable")
        with self.assertLogs("runtime.inventory", level="ERROR"):
            summary = operations_summary(trace_id="runtime-trace")
        self.assertEqual(summary["runtime"]["status"], "UNAVAILABLE")
        self.assertEqual(summary["runtime"]["error_code"], "RUNTIME_INVENTORY_WORKER_UNAVAILABLE")
        self.assertEqual(summary["runtime"]["trace_id"], "runtime-trace")
        self.assertIn("RUNTIME_ENGINE_UNAVAILABLE", [alert["code"] for alert in summary["alerts"]])

    def test_audit_endpoint_uses_business_audit_fields_and_pagination(self) -> None:
        AuditLog.objects.create(
            actor_ref="admin-regression",
            actor_portal="PLATFORM",
            action="course.create",
            target_type="course",
            target_ref=self.course.public_id,
            result="SUCCESS",
            trace_id="a" * 32,
        )
        request = APIRequestFactory().get(
            "/api/v2/platform/operations/audit?page_size=1&search=admin-regression"
        )
        force_authenticate(request, user=self.teacher)
        request.portal = "PLATFORM"
        response = PlatformAuditLogsView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        row = response.data["data"][0]
        self.assertEqual(row["action"], "course.create")
        self.assertEqual(row["actor"], "admin-regression")
        self.assertEqual(row["target"], f"course:{self.course.public_id}")
        self.assertTrue(row["occurred_at"])
        self.assertEqual(response.data["meta"]["total"], 1)
        request.portal = "TEACHING"
        denied = PlatformAuditLogsView.as_view()(request)
        self.assertEqual(denied.status_code, 403)

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

    def test_series_endpoint_returns_recent_daily_projections(self) -> None:
        self.assertEqual(rebuild_course_analytics(course_id=self.course.public_id), 1)
        request = APIRequestFactory().get(
            f"/api/v2/teaching/courses/{self.course.public_id}/analytics/series?days=7"
        )
        force_authenticate(request, user=self.teacher)
        request.portal = "TEACHING"  # type: ignore[attr-defined]
        request.trace_id = "analytics-series-test"  # type: ignore[attr-defined]
        response = TeachingAnalyticsSeriesView.as_view()(request, course_id=self.course.public_id)
        self.assertEqual(response.status_code, 200, response.data)
        expected_date = CourseDaily.objects.get(course=self.course).period_start
        series = response.data["data"]["series"]
        self.assertEqual(len(series), 1)
        self.assertEqual(str(series[0]["period_start"]), expected_date.isoformat())
        self.assertEqual(series[0]["metrics"]["task_total"], 0)

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
        context = ActorContext(self.teacher.public_id, "TEACHING", "analytics-trace")
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
