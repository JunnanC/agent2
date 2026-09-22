from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.core.errors import ImmutableRecordError

from ..models import CourseStaff, CourseStaffEvent, Enrollment
from .helpers import create_draft_course, create_teacher


class CourseModelTests(TestCase):
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
