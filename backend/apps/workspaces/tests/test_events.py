import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.tests.helpers import create_user
from apps.core.models import OutboxEvent
from apps.courses.models import CourseStaff, CourseStaffGrant, Enrollment
from apps.courses.tests.helpers import create_draft_course, create_teacher
from education_experiment_platform.events import _event_id, _event_stream, _visible


class WorkspaceEventScopeTests(TestCase):
    def setUp(self) -> None:
        self.owner = create_teacher(suffix="p08-event-owner")
        self.course = create_draft_course(self.owner, code="P08-EVENT-SCOPE")

    def event(self, payload: dict[str, str]) -> OutboxEvent:
        return OutboxEvent(
            event_type="workspace.snapshot.saved",
            aggregate_type="workspace_session",
            aggregate_ref="opaque-session",
            payload=payload,
            trace_id="e" * 32,
        )

    def test_teaching_visibility_requires_a_live_view_progress_grant(self) -> None:
        assistant = create_teacher(suffix="p08-event-assistant")
        staff = CourseStaff.objects.create(
            course=self.course,
            user=assistant,
            role=CourseStaff.Role.ASSISTANT,
            status=CourseStaff.Status.ACTIVE,
            appointed_by=self.owner,
            appointed_at=timezone.now(),
        )
        grant = CourseStaffGrant.objects.create(
            course_staff=staff,
            capability=CourseStaffGrant.Capability.VIEW_PROGRESS,
            status=CourseStaffGrant.Status.ACTIVE,
            granted_by=self.owner,
            granted_at=timezone.now(),
        )
        event = self.event({"course_id": self.course.public_id})

        self.assertTrue(_visible(event, user=assistant, portal="TEACHING"))
        CourseStaffGrant.objects.filter(pk=grant.pk).update(
            status=CourseStaffGrant.Status.REVOKED,
            revoked_by=self.owner,
            revoked_at=timezone.now(),
        )
        self.assertFalse(_visible(event, user=assistant, portal="TEACHING"))

    def test_user_visibility_requires_a_live_enrollment(self) -> None:
        student = create_user(
            email="p08-event-student@example.edu",
            username="p08-event-student",
            display_name="P08 Event Student",
        )
        enrollment = Enrollment.objects.create(
            course=self.course,
            student=student,
            cycle_no=1,
            status=Enrollment.Status.ACTIVE,
            applied_at=timezone.now(),
            activated_at=timezone.now(),
        )
        event = self.event({"course_id": self.course.public_id})

        self.assertTrue(_visible(event, user=student, portal="USER"))
        Enrollment.objects.filter(pk=enrollment.pk).update(
            status=Enrollment.Status.DROPPED,
            ended_at=timezone.now(),
        )
        self.assertFalse(_visible(event, user=student, portal="USER"))

    @patch("education_experiment_platform.events._redis_replay", return_value=[])
    def test_current_cursor_with_no_new_event_yields_heartbeat_without_resync(
        self, _replay: object
    ) -> None:
        student = create_user(
            email="p08-cursor-student@example.edu",
            username="p08-cursor-student",
            display_name="P08 Cursor Student",
        )
        event = OutboxEvent.objects.create(
            event_type="account.changed",
            aggregate_type="account",
            aggregate_ref=student.public_id,
            payload={"user_id": student.public_id},
            trace_id="c" * 32,
        )
        request = SimpleNamespace(
            user=student,
            portal="USER",
            headers={"Last-Event-ID": _event_id(event)},
        )

        content = b"".join(_event_stream(trace_id="t" * 32, request=request)).decode()

        self.assertIn(": heartbeat", content)
        self.assertNotIn("resync.required", content)

    @patch("education_experiment_platform.events._redis_replay", return_value=[])
    def test_unknown_cursor_requires_resync(self, _replay: object) -> None:
        student = create_user(
            email="p08-expired-cursor@example.edu",
            username="p08-expired-cursor",
            display_name="P08 Expired Cursor",
        )
        cursor = f"{timezone.now().isoformat()}|{uuid.uuid4()}"
        request = SimpleNamespace(
            user=student,
            portal="USER",
            headers={"Last-Event-ID": cursor},
        )

        content = b"".join(_event_stream(trace_id="t" * 32, request=request)).decode()

        self.assertIn("resync.required", content)
        self.assertIn("SSE_CURSOR_EXPIRED", content)
