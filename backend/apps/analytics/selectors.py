from django.db.models import QuerySet

from apps.accounts.models import User
from apps.core.errors import ResourceNotFound
from apps.courses.models import Course
from apps.courses.selectors import has_course_capability, visible_course

from .models import (
    CourseDaily,
    CourseQualitySnapshot,
    LearningRecommendation,
    ResourceCostDaily,
    StudentRiskSignal,
)


def teaching_course(*, actor: User, course_id: str) -> Course:
    course = visible_course(actor=actor, portal="TEACHING", course_id=course_id)
    if not has_course_capability(course=course, actor=actor, capability="VIEW_PROGRESS"):
        raise ResourceNotFound()
    return course


def user_recommendations(*, actor: User) -> QuerySet[LearningRecommendation]:
    return LearningRecommendation.objects.filter(student=actor).select_related("course", "task")


def user_risk_signals(*, actor: User) -> QuerySet[StudentRiskSignal]:
    return StudentRiskSignal.objects.filter(student=actor).select_related("course", "task")


def course_daily(*, course: Course) -> QuerySet[CourseDaily]:
    return CourseDaily.objects.filter(course=course).order_by("-period_start")


def course_risk_signals(*, course: Course) -> QuerySet[StudentRiskSignal]:
    return (
        StudentRiskSignal.objects.filter(course=course)
        .select_related("student", "task")
        .order_by("-created_at")
    )


def course_quality(*, course: Course) -> QuerySet[CourseQualitySnapshot]:
    return CourseQualitySnapshot.objects.filter(course=course).order_by("-period_start")


def course_costs(*, course: Course) -> QuerySet[ResourceCostDaily]:
    return ResourceCostDaily.objects.filter(course=course).order_by("-period_start")
