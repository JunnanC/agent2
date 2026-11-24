"""Teaching grade release and published results for the teaching and student portals."""

from django.http import HttpRequest
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsTeachingPortal, IsUserPortal
from apps.core.errors import ResourceNotFound
from apps.courses.models import CourseStaffGrant
from apps.courses.selectors import require_course_capability
from apps.reports.assessment_review import request_reviews

from .assessment import _task
from .assessment_views import AssessmentResponseSerializer
from .grade_release import published_results, release_grades, release_status
from .models import PublishedExperimentGrade, TaskPublication
from .selectors import publication_for_course, teaching_course
from .views import _response


class BatchWordReviewView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(request=None, responses={202: AssessmentResponseSerializer})
    def post(self, request: HttpRequest, course_id: str, publication_id: str) -> Response:
        publication = publication_for_course(
            actor=request.user,
            course_id=course_id,
            publication_id=publication_id,
        )
        require_course_capability(
            course=publication.course,
            actor=request.user,
            capability=CourseStaffGrant.Capability.REVIEW_SUBMISSION,
        )
        return _response(request, request_reviews(publication), status=202)


class GradeReleaseView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, course_id: str, publication_id: str) -> Response:
        publication = publication_for_course(
            actor=request.user,
            course_id=course_id,
            publication_id=publication_id,
        )
        return _response(request, release_status(publication))

    @extend_schema(request=None, responses=AssessmentResponseSerializer)
    def post(self, request: HttpRequest, course_id: str, publication_id: str) -> Response:
        publication = publication_for_course(
            actor=request.user,
            course_id=course_id,
            publication_id=publication_id,
        )
        require_course_capability(
            course=publication.course,
            actor=request.user,
            capability=CourseStaffGrant.Capability.REVIEW_SUBMISSION,
        )
        return _response(
            request, release_grades(
                publication, actor=request.user, trace_id=str(getattr(request, "trace_id", "")),
            ),
        )


class TeachingPublishedGradesView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, course_id: str, publication_id: str) -> Response:
        course = teaching_course(
            actor=request.user, course_id=course_id,
            capability=CourseStaffGrant.Capability.VIEW_PROGRESS,
        )
        publication = TaskPublication.objects.filter(
            course=course, public_id=publication_id,
        ).first()
        if publication is None:
            raise ResourceNotFound()
        return _response(
            request,
            {
                "grades_published_at": publication.grades_published_at,
                "rows": published_results(publication),
            },
        )


class StudentPublishedGradeView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, task_id: str) -> Response:
        task = _task(request.user, task_id)
        grade = PublishedExperimentGrade.objects.filter(task=task).first()
        if grade is None or not task.publication.grades_published_at:
            raise ResourceNotFound()
        return _response(
            request,
            {
                **grade.result,
                "grades_published_at": task.publication.grades_published_at,
            },
        )
