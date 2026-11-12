from django.db.models import QuerySet

from apps.accounts.models import User
from apps.core.errors import ResourceNotFound
from apps.courses.models import Course, CourseStaffGrant
from apps.courses.selectors import require_course_capability, visible_course

from .models import Rubric, RubricVersion


def teaching_course(*, actor: User, course_id: str) -> Course:
    course = visible_course(actor=actor, portal="TEACHING", course_id=course_id)
    require_course_capability(
        course=course,
        actor=actor,
        capability=CourseStaffGrant.Capability.REVIEW_SUBMISSION,
    )
    return course


def rubrics_for_course(*, actor: User, course_id: str) -> QuerySet[Rubric]:
    course = teaching_course(actor=actor, course_id=course_id)
    return Rubric.objects.filter(course=course).select_related("current_version").order_by("name")


def rubric_for_course(*, actor: User, course_id: str, rubric_id: str) -> Rubric:
    course = teaching_course(actor=actor, course_id=course_id)
    try:
        return Rubric.objects.select_related("current_version").get(
            public_id=rubric_id, course=course
        )
    except Rubric.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def version_for_course(*, actor: User, course_id: str, version_id: str) -> RubricVersion:
    course = teaching_course(actor=actor, course_id=course_id)
    try:
        return (
            RubricVersion.objects.select_related("rubric__course")
            .prefetch_related("criteria")
            .get(public_id=version_id, rubric__course=course)
        )
    except RubricVersion.DoesNotExist as exc:
        raise ResourceNotFound() from exc
