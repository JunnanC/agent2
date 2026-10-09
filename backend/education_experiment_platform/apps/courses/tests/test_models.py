from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.core.errors import ImmutableRecordError

from ..models import AcademicTerm, Course, CourseStaff, CourseStaffEvent, Enrollment
from .helpers import create_draft_course, create_teacher


class CourseModelTests(TestCase):
    def test_only_one_academic_term_can_be_current(self) -> None:
        self.assertEqual(AcademicTerm.objects.filter(is_current=True).count(), 1)

        with self.assertRaises(IntegrityError), transaction.atomic():
            AcademicTerm.objects.create(
                code="2026-FALL",
                name="Fall 2026",
                starts_at=timezone.now(),
                ends_at=timezone.now() + timedelta(days=180),
                status=AcademicTerm.Status.CURRENT,
                is_current=True,
            )

    def test_course_requires_an_academic_term(self) -> None:
        owner = create_teacher()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Course.objects.create(
                code="UNTIMED-COURSE",
                title="Untimed Course",
                owner=owner,
                term=None,
            )

    def test_course_has_exactly_one_active_owner_slot(self) -> None:
        owner = create_teacher()
        second = create_teacher(suffix="second")
        course = create_draft_course(owner)

        with self.assertRaises(IntegrityError), transaction.atomic():
            CourseStaff.objects.create(
                course=course,
                user=second,
                role=CourseStaff.Role.OWNER,
                status=CourseStaff.Status.ACTIVE,
                appointed_by=owner,
                appointed_at=timezone.now(),
            )

    def test_live_enrollment_unique_constraint_preserves_history(self) -> None:
        owner = create_teacher()
        student = create_teacher(suffix="student")
        course = create_draft_course(owner)
        Enrollment.objects.create(
            course=course,
            student=student,
            cycle_no=1,
            status=Enrollment.Status.ACTIVE,
            applied_at=timezone.now(),
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrollment.objects.create(
                course=course,
                student=student,
                cycle_no=2,
                status=Enrollment.Status.PENDING,
                applied_at=timezone.now(),
            )

    def test_staff_events_are_append_only(self) -> None:
        owner = create_teacher()
        course = create_draft_course(owner)
        event = CourseStaffEvent.objects.get(course=course)

        with self.assertRaises(ImmutableRecordError):
            CourseStaffEvent.objects.filter(pk=event.pk).update(reason="forbidden")
        with self.assertRaises(ImmutableRecordError):
            event.delete()
