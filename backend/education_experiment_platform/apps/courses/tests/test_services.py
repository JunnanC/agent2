from django.test import TestCase

from apps.accounts.models import TeacherQualification
from apps.accounts.services import ActorContext as AccountActorContext
from apps.accounts.services import change_teacher_qualification
from apps.accounts.tests.helpers import create_user
from apps.core.models import AuditLog, OutboxEvent

from ..errors import (
    CourseGrantRequired,
    EnrollmentAlreadyLive,
    EnrollmentBlocked,
    EnrollmentCapacityFull,
    OwnerTransferRequired,
)
from ..models import Course, CourseStaff, CourseStaffGrant, Enrollment, EnrollmentEvent
from ..ports import Blocker, clear_blocker_providers, register_enrollment_blocker
from ..selectors import has_course_capability
from ..services import (
    ActorContext,
    apply_for_course,
    appoint_course_assistant,
    drop_enrollment,
    grant_course_capability,
    publish_course,
    review_enrollment,
    transfer_course_ownership,
)
from .helpers import create_draft_course, create_teacher


class CourseServiceTests(TestCase):
    def setUp(self) -> None:
        self.owner = create_teacher()
        self.course = create_draft_course(self.owner, capacity=1)
        self.context = ActorContext(self.owner.public_id, "TEACHING", "b" * 32)

    def tearDown(self) -> None:
        clear_blocker_providers()

    def _publish(self) -> Course:
        return publish_course(
            course_id=self.course.public_id,
            actor=self.owner,
            expected_version=self.course.row_version,
            context=self.context,
        )

    def test_owner_transfer_keeps_one_owner_and_blocks_qualification_revocation(self) -> None:
        new_owner = create_teacher(suffix="new-owner")
        changed = transfer_course_ownership(
            course_id=self.course.public_id,
            new_owner_id=new_owner.public_id,
            actor=self.owner,
            expected_version=self.course.row_version,
            reason="handoff",
            context=self.context,
        )

        self.assertEqual(changed.owner, new_owner)
        self.assertEqual(
            CourseStaff.objects.filter(
                course=self.course,
                role=CourseStaff.Role.OWNER,
                status=CourseStaff.Status.ACTIVE,
            ).count(),
            1,
        )
        qualification = TeacherQualification.objects.get(user=new_owner)
        with self.assertRaises(OwnerTransferRequired):
            change_teacher_qualification(
                qualification_public_id=qualification.public_id,
                status=TeacherQualification.Status.SUSPENDED,
                reason="blocked",
                expected_version=qualification.row_version,
                actor=self.owner,
                context=AccountActorContext(self.owner.public_id, "PLATFORM", "c" * 32),
            )

    def test_assistant_requires_explicit_grant(self) -> None:
        assistant = create_teacher(suffix="assistant")
        staff = appoint_course_assistant(
            course_id=self.course.public_id,
            user_id=assistant.public_id,
            actor=self.owner,
            reason="help",
            context=self.context,
        )
        self.assertFalse(
            has_course_capability(
                course=self.course,
                actor=assistant,
                capability=CourseStaffGrant.Capability.MANAGE_ENROLLMENT,
            )
        )
        grant_course_capability(
            course_id=self.course.public_id,
            staff_id=staff.public_id,
            capability=CourseStaffGrant.Capability.MANAGE_ENROLLMENT,
            expires_at=None,
            actor=self.owner,
            reason="roster",
            context=self.context,
        )
        self.assertTrue(
            has_course_capability(
                course=self.course,
                actor=assistant,
                capability=CourseStaffGrant.Capability.MANAGE_ENROLLMENT,
            )
        )
        with self.assertRaises(CourseGrantRequired):
            from ..selectors import require_course_capability

            require_course_capability(
                course=self.course,
                actor=assistant,
                capability=CourseStaffGrant.Capability.MODERATE_QA,
            )

    def test_open_enrollment_locks_capacity_and_rejects_duplicate_live_cycle(self) -> None:
        self._publish()
        first = create_user(email="first@example.edu", username="first")
        second = create_user(email="second-student@example.edu", username="second-student")
        first_enrollment = apply_for_course(
            course_id=self.course.public_id,
            student=first,
            application_message="",
            context=ActorContext(first.public_id, "USER", "d" * 32),
        )
        self.assertEqual(first_enrollment.status, Enrollment.Status.ACTIVE)
        with self.assertRaises(EnrollmentAlreadyLive):
            apply_for_course(
                course_id=self.course.public_id,
                student=first,
                application_message="again",
                context=ActorContext(first.public_id, "USER", "e" * 32),
            )
        with self.assertRaises(EnrollmentCapacityFull):
            apply_for_course(
                course_id=self.course.public_id,
                student=second,
                application_message="",
                context=ActorContext(second.public_id, "USER", "f" * 32),
            )

    def test_approval_rechecks_capacity_and_appends_event(self) -> None:
        Course.objects.filter(pk=self.course.pk).update(
            enrollment_mode=Course.EnrollmentMode.APPROVAL
        )
        self.course.refresh_from_db()
        self._publish()
        first = create_user(email="first@example.edu", username="first")
        second = create_user(email="second-student@example.edu", username="second-student")
        applications = [
            apply_for_course(
                course_id=self.course.public_id,
                student=student,
                application_message="",
                context=ActorContext(student.public_id, "USER", "1" * 32),
            )
            for student in (first, second)
        ]
        approved = review_enrollment(
            course_id=self.course.public_id,
            enrollment_id=applications[0].public_id,
            decision="APPROVE",
            note="ok",
            actor=self.owner,
            expected_version=applications[0].row_version,
            context=self.context,
        )
        self.assertEqual(approved.status, Enrollment.Status.ACTIVE)
        with self.assertRaises(EnrollmentCapacityFull):
            review_enrollment(
                course_id=self.course.public_id,
                enrollment_id=applications[1].public_id,
                decision="APPROVE",
                note="full",
                actor=self.owner,
                expected_version=applications[1].row_version,
                context=self.context,
            )
        self.assertEqual(EnrollmentEvent.objects.filter(enrollment=approved).count(), 2)

    def test_drop_rechecks_blockers_and_records_audit_outbox(self) -> None:
        self._publish()
        student = create_user(email="student@example.edu", username="student")
        enrollment = apply_for_course(
            course_id=self.course.public_id,
            student=student,
            application_message="",
            context=ActorContext(student.public_id, "USER", "2" * 32),
        )
        register_enrollment_blocker(
            lambda _enrollment: [Blocker("UNFINISHED_TASK", 1, ("EXP-1",), "未完成")]
        )
        with self.assertRaises(EnrollmentBlocked):
            drop_enrollment(
                enrollment_id=enrollment.public_id,
                student=student,
                expected_version=enrollment.row_version,
                reason="leave",
                context=ActorContext(student.public_id, "USER", "3" * 32),
            )
        clear_blocker_providers()
        changed = drop_enrollment(
            enrollment_id=enrollment.public_id,
            student=student,
            expected_version=enrollment.row_version,
            reason="leave",
            context=ActorContext(student.public_id, "USER", "4" * 32),
        )
        self.assertEqual(changed.status, Enrollment.Status.DROPPED)
        self.assertTrue(AuditLog.objects.filter(target_ref=enrollment.public_id).exists())
        self.assertTrue(OutboxEvent.objects.filter(aggregate_ref=enrollment.public_id).exists())
