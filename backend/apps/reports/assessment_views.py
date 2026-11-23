import hashlib
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import UploadedFile
from django.http import FileResponse, HttpRequest
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsTeachingPortal, IsUserPortal
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.errors import ResourceNotFound, StateConflict
from apps.core.idempotency import StoredResponse
from apps.courses.models import CourseStaffGrant
from apps.experiments.assessment import _task
from apps.experiments.assessment_parts import can_start_session, grant_redo, part_scores
from apps.experiments.assessment_views import AssessmentResponseSerializer
from apps.experiments.models import ExperimentTask, PartRedo
from apps.experiments.selectors import publication_for_course, teaching_course
from apps.experiments.serializers import publication_data
from apps.experiments.views import IDEMPOTENCY_KEY, IF_MATCH, _body, _idempotent, _response

from .assessment_reports import attach_template, grade_report, report_data, submit_report
from .models import ReportSubmission
from .word_review import annotated_docx, asset_bytes, document_paragraphs


class FileSerializer(serializers.Serializer):
    file = serializers.FileField()


class ReportCommentSerializer(serializers.Serializer):
    paragraph = serializers.IntegerField(min_value=1)
    text = serializers.CharField(max_length=1000)


class ReportGradeSerializer(serializers.Serializer):
    score = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal(0))
    feedback = serializers.CharField(max_length=1000, default="", allow_blank=True)
    comments = ReportCommentSerializer(many=True, max_length=50, required=False)


class RedoSerializer(serializers.Serializer):
    part = serializers.ChoiceField(choices=PartRedo.Part.choices)
    redo_until = serializers.DateTimeField()
    reason = serializers.CharField(max_length=500, default="", allow_blank=True)


def _file_payload(file: UploadedFile) -> dict[str, str | None]:
    digest = hashlib.sha256()
    for chunk in file.chunks():
        digest.update(chunk)
    file.seek(0)
    return {"name": file.name, "digest": digest.hexdigest()}


def _teaching_task(request: HttpRequest, course_id: str, task_id: str) -> ExperimentTask:
    course = teaching_course(
        actor=request.user,
        course_id=course_id,
        capability=CourseStaffGrant.Capability.REVIEW_SUBMISSION,
    )
    task = ExperimentTask.objects.filter(course=course, public_id=task_id).first()
    if task is None:
        raise ResourceNotFound()
    return task


class StudentReportView(APIView):
    permission_classes = [IsUserPortal]
    parser_classes = [MultiPartParser]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, task_id: str) -> Response:
        return _response(request, report_data(_task(request.user, task_id)))

    @extend_schema(
        request=FileSerializer,
        responses=AssessmentResponseSerializer,
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: HttpRequest, task_id: str) -> Response:
        serializer = FileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        file = serializer.validated_data["file"]

        def operation() -> StoredResponse:
            data = submit_report(actor=request.user, task_id=task_id, file=file)
            return StoredResponse(200, _body(request, data), {})

        return _idempotent(request, payload=_file_payload(file), operation=operation)


class PublicationReportTemplateView(APIView):
    permission_classes = [IsTeachingPortal]
    parser_classes = [MultiPartParser]

    @extend_schema(
        request=FileSerializer,
        responses=AssessmentResponseSerializer,
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
    )
    def post(self, request: HttpRequest, course_id: str, publication_id: str) -> Response:
        publication = publication_for_course(
            actor=request.user,
            course_id=course_id,
            publication_id=publication_id,
        )
        serializer = FileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        file = serializer.validated_data["file"]
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            updated = attach_template(publication=publication, file=file, expected_version=expected)
            return StoredResponse(
                200,
                _body(request, publication_data(updated)),
                {"ETag": etag_for_version(updated.row_version)},
            )

        return _idempotent(
            request,
            payload={**_file_payload(file), "version": expected},
            operation=operation,
        )


class TeachingReportListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = teaching_course(
            actor=request.user,
            course_id=course_id,
            capability=CourseStaffGrant.Capability.REVIEW_SUBMISSION,
        )
        reports = (
            ReportSubmission.objects.filter(task__course=course)
            .select_related(
                "task__student",
                "task__publication",
                "asset",
            )
            .order_by("-submitted_at", "pk")
        )
        if publication_id := request.query_params.get("publication_id"):
            reports = reports.filter(task__publication__public_id=publication_id)
        rows = [
            {
                "task_id": report.task.public_id,
                "student_name": report.task.student.display_name,
                "title": report.task.publication.title,
                "status": report.status,
                "review_status": report.review_status,
                "submitted_at": report.submitted_at,
            }
            for report in reports[:500]
        ]
        return _response(request, {"rows": rows})


class TeachingReportView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, course_id: str, task_id: str) -> Response:
        task = _teaching_task(request, course_id, task_id)
        result = report_data(task, teaching=True)
        if task.publication.direct_assessment and request.query_params.get("paragraphs") == "1":
            report = ReportSubmission.objects.select_related("asset").filter(task=task).first()
            if report:
                try:
                    rows = document_paragraphs(asset_bytes(report.asset))
                    result["paragraphs"] = [
                        {**item, "text": item["text"][:300]} for item in rows[:300]
                    ]
                except Exception:
                    result["paragraphs_unavailable"] = True
        return _response(request, result)

    @extend_schema(
        request=ReportGradeSerializer,
        responses=AssessmentResponseSerializer,
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
    )
    def post(self, request: HttpRequest, course_id: str, task_id: str) -> Response:
        task = _teaching_task(request, course_id, task_id)
        serializer = ReportGradeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            data = grade_report(
                task=task,
                actor=request.user,
                expected_version=expected,
                **serializer.validated_data,
            )
            return StoredResponse(200, _body(request, data), {})

        return _idempotent(
            request,
            payload={**serializer.validated_data, "version": expected},
            operation=operation,
        )


class AssessmentPartsView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, course_id: str, task_id: str) -> Response:
        task = _teaching_task(request, course_id, task_id)
        return _response(
            request,
            {
                "parts": part_scores(task) if can_start_session(task) else [],
                "redo_available": not task.publication.grades_published_at
                and task.publication.status in {"PUBLISHED", "CLOSED"}
                and timezone.now() >= task.publication.window_end,
            },
        )

    @extend_schema(
        request=RedoSerializer,
        responses=AssessmentResponseSerializer,
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: HttpRequest, course_id: str, task_id: str) -> Response:
        task = _teaching_task(request, course_id, task_id)
        serializer = RedoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            grant_redo(task=task, actor=request.user, **serializer.validated_data)
            data = {"parts": part_scores(ExperimentTask.objects.get(pk=task.pk))}
            return StoredResponse(200, _body(request, data), {})

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class StudentReviewedReportDownloadView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(responses={
        (200, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"):
        OpenApiTypes.BINARY,
    })
    def get(self, request: HttpRequest, task_id: str) -> FileResponse:
        task = _task(request.user, task_id)
        publication = task.publication
        report = ReportSubmission.objects.select_related("asset").filter(
            task=task, status="GRADED", asset__status="ACTIVE", asset__scan_status="CLEAN",
        ).first()
        if not publication.grades_published_at or report is None:
            raise ResourceNotFound()
        try:
            content = annotated_docx(
                asset_bytes(report.asset), entries=report.comments, signer=publication.grade_signer,
                date=timezone.localtime(publication.grades_published_at).date().isoformat(),
                score=str(report_data(task)["score"]), feedback=report.feedback,
            )
        except Exception as exc:
            raise StateConflict(detail={"report": "review_file_unavailable"}) from exc
        result = FileResponse(
            BytesIO(content), as_attachment=True, filename="实验报告-已批阅.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        result["Cache-Control"] = "private, no-store"
        return result
