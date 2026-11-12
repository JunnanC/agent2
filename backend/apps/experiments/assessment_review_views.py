from django.http import HttpRequest
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsTeachingPortal
from apps.core.concurrency import parse_if_match
from apps.core.errors import ResourceNotFound
from apps.core.idempotency import StoredResponse
from apps.reviews.selectors import teaching_course

from .assessment import review_programming, section_result
from .assessment_views import AssessmentResponseSerializer
from .models import AssessmentSection, ExperimentTask
from .views import IDEMPOTENCY_KEY, IF_MATCH, _body, _idempotent, _response


class AssessmentReviewWriteSerializer(serializers.Serializer):
    submission_version = serializers.IntegerField(min_value=1)
    scores = serializers.DictField(child=serializers.CharField(), required=False, default=dict)
    feedback = serializers.CharField(allow_blank=True, required=False, default="")
    return_until = serializers.DateTimeField(required=False, allow_null=True)
    retry_judge = serializers.BooleanField(required=False, default=False)


class AssessmentTeachingView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, course_id: str, task_id: str) -> Response:
        course = teaching_course(actor=request.user, course_id=course_id)
        try:
            task = ExperimentTask.objects.get(public_id=task_id, course=course)
        except ExperimentTask.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        sections = list(
            AssessmentSection.objects.filter(task=task).select_related("current_submission")
        )
        programming = next((s for s in sections if s.kind == "PROGRAMMING"), None)
        report = programming.current_submission.report_version if (
            programming and programming.current_submission_id
        ) else None
        sources = []
        if programming and programming.current_submission_id:
            from .assessment_workers import _read_source

            sources = [{
                "question_id": answer.question.public_id, "language": answer.language,
                "files": _read_source(answer.code_snapshot),
            } for answer in programming.current_submission.answers.select_related(
                "question", "code_snapshot__asset",
            ) if answer.code_snapshot_id]
        history = [{
            "kind": section.kind, "versions": [{
                "version_no": submission.version_no, "submitted_at": submission.submitted_at,
            } for submission in section.sectionsubmission_set.order_by("version_no")],
        } for section in sections]
        return _response(request, {
            "task_id": task.public_id, "student_name": task.student.display_name,
            "sections": [section_result(section, student=False) for section in sections],
            "report": {"body_markdown": report.body_markdown, "version_no": report.version_no}
            if report else None,
            "report_criteria": [{
                "id": criterion.public_id, "title": criterion.title,
                "max_score": str(criterion.max_score),
            } for criterion in task.publication.rubric_version.criteria.all()]
            if task.publication.rubric_version_id and task.publication.report_required else [],
            "history": history,
            "sources": sources,
        })

    @extend_schema(
        request=AssessmentReviewWriteSerializer, responses=AssessmentResponseSerializer,
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
    )
    def post(self, request: HttpRequest, course_id: str, task_id: str) -> Response:
        serializer = AssessmentReviewWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            data = review_programming(
                actor=request.user, course_id=course_id, task_id=task_id,
                expected_version=parse_if_match(request.headers.get("If-Match")),
                trace_id=str(getattr(request, "trace_id", "")), **serializer.validated_data,
            )
            return StoredResponse(200, _body(request, data), {})

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class AssessmentReviewListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = teaching_course(actor=request.user, course_id=course_id)
        sections = AssessmentSection.objects.filter(
            task__course=course, kind="PROGRAMMING", current_submission__isnull=False,
        ).select_related(
            "task__student", "task__publication", "current_submission",
        ).order_by("-updated_at")
        return _response(request, {"rows": [{
            "task_id": section.task.public_id, "student_name": section.task.student.display_name,
            "title": section.task.publication.title, "status": section.status,
            "version_no": section.current_submission.version_no,
        } for section in sections[:500]]})
