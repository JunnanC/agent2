from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import TeacherQualification
from apps.accounts.services import ActorContext as AccountActorContext
from apps.accounts.services import change_teacher_qualification
from apps.accounts.tests.helpers import create_user
from apps.core.models import AuditLog, OutboxEvent

from ..content_services import create_invitation
from ..errors import (
    CourseGrantRequired,
    EnrollmentAlreadyLive,
    EnrollmentBlocked,
    EnrollmentCapacityFull,
    InvitationInvalid,
    OwnerTransferRequired,
)
from ..models import Course, CourseStaff, CourseStaffGrant, Enrollment, EnrollmentEvent
from ..ports import Blocker, clear_blocker_providers, register_enrollment_blocker
from ..selectors import (
    has_course_capability,
    student_courses_for_term,
    teacher_courses_for_term,
)
from ..services import (
    ActorContext,
    apply_for_course,
    appoint_course_assistant,
    current_academic_term,
    drop_enrollment,
    enrollment_exit_check,
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

    def test_current_academic_term_and_term_course_selectors_filter_active_relations(self) -> None:
        term = current_academic_term()
        Course.objects.filter(pk=self.course.pk).update(term=term)
        self.course.refresh_from_db()
        self.assertEqual(list(teacher_courses_for_term(self.owner, "current")), [self.course])
        student = create_user(email="term-student@example.edu", username="term-student")
        active = Enrollment.objects.create(
            course=self.course,
            student=student,
            cycle_no=1,
            status=Enrollment.Status.ACTIVE,
            applied_at=timezone.now(),
        )
        closed = create_draft_course(self.owner, code="CLOSED-TERM-001")
        Course.objects.filter(pk=closed.pk).update(term=term, status=Course.Status.CLOSED)
        archived = create_draft_course(self.owner, code="ARCHIVED-TERM-001")
        Course.objects.filter(pk=archived.pk).update(term=term, status=Course.Status.ARCHIVED)
        self.assertEqual(list(student_courses_for_term(student, "current")), [self.course])
        CourseStaff.objects.filter(course=self.course, user=self.owner).update(
            status=CourseStaff.Status.REVOKED
        )
        self.assertEqual(list(teacher_courses_for_term(self.owner, "current")), [])
        self.assertEqual(list(student_courses_for_term(student, term.public_id)), [active.course])

    def test_current_window_course_is_visible_from_current_term(self) -> None:
        now = timezone.now()
        Course.objects.filter(pk=self.course.pk).update(
            term=current_academic_term(),
            teaching_start=now - timedelta(days=7),
            teaching_end=now + timedelta(days=7),
        )
        self.assertEqual(list(teacher_courses_for_term(self.owner, "current")), [self.course])

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

    def test_teacher_invitation_activates_and_locks_capacity(self) -> None:
        self._publish()
        first = create_user(email="first@example.edu", username="first")
        second = create_user(email="second-student@example.edu", username="second-student")
        _, invitation_code = create_invitation(
            course_id=self.course.public_id,
            actor=self.owner,
            max_uses=10,
            expires_at=timezone.now() + timedelta(days=1),
            context=self.context,
        )
        first_enrollment = apply_for_course(
            course_id=self.course.public_id,
            student=first,
            application_message="",
            invited_by=self.owner,
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
                invited_by=self.owner,
                context=ActorContext(second.public_id, "USER", "f" * 32),
            )

    def test_course_without_invitation_always_waits_for_teacher(self) -> None:
        self._publish()
        student = create_user(email="approval-student@example.edu", username="approval-student")
        enrollment = apply_for_course(
            course_id=self.course.public_id,
            student=student,
            application_message="",
            context=ActorContext(student.public_id, "USER", "a" * 32),
        )
        self.assertEqual(enrollment.status, Enrollment.Status.PENDING)

    def test_invitation_requires_teacher_review(self) -> None:
        self._publish()
        Course.objects.filter(pk=self.course.pk).update(
            enrollment_mode=Course.EnrollmentMode.APPROVAL
        )
        student = create_user(email="invited@example.edu", username="invited")
        invitation, code = create_invitation(
            course_id=self.course.public_id,
            actor=self.owner,
            max_uses=1,
            expires_at=timezone.now() + timedelta(days=1),
            context=self.context,
        )
        enrollment = apply_for_course(
            course_id=self.course.public_id,
            student=student,
            application_message="",
            invitation_code=f"  {code}  ",
            context=ActorContext(student.public_id, "USER", "a" * 32),
        )
        invitation.refresh_from_db()
        self.assertEqual(enrollment.status, Enrollment.Status.PENDING)
        self.assertIsNone(enrollment.activated_at)
        self.assertEqual(invitation.used_count, 1)

    def test_invalid_invitation_does_not_create_pending_application(self) -> None:
        self._publish()
        student = create_user(email="invalid-code@example.edu", username="invalid-code")
        with self.assertRaises(InvitationInvalid):
            apply_for_course(
                course_id=self.course.public_id,
                student=student,
                application_message="",
                invitation_code="wrong-code",
                context=ActorContext(student.public_id, "USER", "a" * 32),
            )
        self.assertFalse(Enrollment.objects.filter(course=self.course, student=student).exists())

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

    def test_student_drop_allows_unfinished_tasks_but_rechecks_other_blockers(self) -> None:
        self._publish()
        student = create_user(email="student@example.edu", username="student")
        enrollment = apply_for_course(
            course_id=self.course.public_id,
            student=student,
            application_message="",
            context=ActorContext(student.public_id, "USER", "2" * 32),
        )
        enrollment = review_enrollment(
            course_id=self.course.public_id,
            enrollment_id=enrollment.public_id,
            decision="APPROVE",
            note="ok",
            actor=self.owner,
            expected_version=enrollment.row_version,
            context=self.context,
        )
        register_enrollment_blocker(
            lambda _enrollment: [Blocker("UNFINISHED_TASK", 1, ("EXP-1",), "未完成")]
        )
        self.assertEqual(enrollment_exit_check(enrollment=enrollment)[0].type, "UNFINISHED_TASK")
        self.assertEqual(
            enrollment_exit_check(enrollment=enrollment, allow_unfinished_tasks=True), []
        )
        register_enrollment_blocker(
            lambda _enrollment: [Blocker("RUNTIME_BUSY", 1, ("runtime-1",), "其他阻塞")]
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
        register_enrollment_blocker(
            lambda _enrollment: [Blocker("UNFINISHED_TASK", 1, ("EXP-1",), "未完成")]
        )
        changed = drop_enrollment(
            enrollment_id=enrollment.public_id,
            student=student,
            expected_version=enrollment.row_version,
            reason="leave",
            context=ActorContext(student.public_id, "USER", "4" * 32),
        )
        self.assertEqual(changed.status, Enrollment.Status.DROPPED)
        self.assertEqual(changed.end_reason, "leave")
        self.assertEqual(
            enrollment_exit_check(enrollment=changed, allow_unfinished_tasks=True)[0].type,
            "ENROLLMENT_NOT_ACTIVE",
        )
        with self.assertRaises(EnrollmentBlocked):
            drop_enrollment(
                enrollment_id=changed.public_id,
                student=student,
                expected_version=changed.row_version,
                reason="again",
                context=ActorContext(student.public_id, "USER", "5" * 32),
            )
        self.assertTrue(AuditLog.objects.filter(target_ref=enrollment.public_id).exists())
        self.assertTrue(OutboxEvent.objects.filter(aggregate_ref=enrollment.public_id).exists())
