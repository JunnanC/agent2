from django.db.models import QuerySet

from apps.accounts.models import User
from apps.core.errors import ResourceNotFound
from apps.courses.models import Course, CourseStaffGrant
from apps.courses.selectors import require_course_capability, visible_course

from .models import Review, Rubric, RubricVersion, SimilarityMatch, SimilarityRun


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


def reviews_for_course(
    *, actor: User, course_id: str, status: str = "", publication_id: str = ""
) -> QuerySet[Review]:
    course = teaching_course(actor=actor, course_id=course_id)
    values = Review.objects.filter(course=course).select_related(
        "task__student", "task__publication", "rubric_version", "assigned_to"
    )
    if status:
        values = values.filter(status=status)
    if publication_id:
        values = values.filter(task__publication__public_id=publication_id)
    return values.order_by("status", "created_at", "id")


def review_for_course(*, actor: User, course_id: str, review_id: str) -> Review:
    course = teaching_course(actor=actor, course_id=course_id)
    try:
        return (
            Review.objects.select_related(
                "course",
                "task__student",
                "task__publication",
                "rubric_version__rubric",
                "report_version__workspace_snapshot__asset",
                "system_artifact__asset",
            )
            .prefetch_related(
                "rubric_version__criteria",
                "criterion_scores__criterion",
                "annotations__revisions",
                "annotations__asset",
                "auto_check_runs__rule",
                "similarity_runs",
            )
            .get(public_id=review_id, course=course)
        )
    except Review.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def reviews_for_user_result(*, actor: User, task_id: str) -> QuerySet[Review]:
    values = (
        Review.objects.filter(task__public_id=task_id, task__student=actor)
        .select_related(
            "task",
            "rubric_version",
            "report_version",
            "system_artifact",
        )
        .prefetch_related(
            "rubric_version__criteria",
            "criterion_scores__criterion",
            "annotations__revisions",
        )
        .order_by("-round_no")
    )
    if not values.exists():
        raise ResourceNotFound()
    return values


def similarity_run_for_course(
    *, actor: User, course_id: str, run_id: str
) -> SimilarityRun:
    course = teaching_course(actor=actor, course_id=course_id)
    try:
        return SimilarityRun.objects.select_related(
            "review", "target_report_version", "course"
        ).get(public_id=run_id, course=course)
    except SimilarityRun.DoesNotExist as exc:
        raise ResourceNotFound() from exc


def similarity_matches_for_course(
    *, actor: User, course_id: str, run_id: str
) -> QuerySet[SimilarityMatch]:
    run = similarity_run_for_course(actor=actor, course_id=course_id, run_id=run_id)
    return SimilarityMatch.objects.filter(run=run).select_related(
        "candidate_report_version__task__student"
    ).order_by("-score", "id")
