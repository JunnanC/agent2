from django.db.models import Max
from django.http import HttpRequest
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsTeachingPortal
from apps.core.concurrency import parse_if_match
from apps.core.errors import ResourceNotFound, StateConflict
from apps.core.idempotency import StoredResponse
from apps.reviews.selectors import teaching_course

from .assessment import choice_review_data, report_review_status, review_programming, section_result
from .assessment_parts import part_scores, session_for
from .assessment_views import AssessmentResponseSerializer
from .models import AssessmentSection, ExperimentTask, ProgrammingSubmission
from .views import IDEMPOTENCY_KEY, IF_MATCH, _body, _idempotent, _response


class AssessmentReviewWriteSerializer(serializers.Serializer):
    submission_version = serializers.IntegerField(min_value=1)
    scores = serializers.DictField(child=serializers.CharField(), required=False, default=dict)
    feedback = serializers.CharField(allow_blank=True, required=False, default="")
    return_until = serializers.DateTimeField(required=False, allow_null=True)
    retry_judge = serializers.BooleanField(required=False, default=False)


class ReportSuggestionWriteSerializer(serializers.Serializer):
    submission_version = serializers.IntegerField(min_value=1)


class AssessmentReportSuggestionView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        request=ReportSuggestionWriteSerializer,
        responses=AssessmentResponseSerializer,
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: HttpRequest, course_id: str, task_id: str) -> Response:
        from apps.agents.rubric_agent import assess_submission

        serializer = ReportSuggestionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        course = teaching_course(actor=request.user, course_id=course_id)

        def operation() -> StoredResponse:
            try:
                section = AssessmentSection.objects.select_related(
                    "current_submission__report_version",
                    "task__publication__rubric_version",
                ).get(task__public_id=task_id, task__course=course, kind="PROGRAMMING")
            except AssessmentSection.DoesNotExist as exc:
                raise ResourceNotFound() from exc
            submission = section.current_submission
            if (
                not submission
                or submission.version_no != serializer.validated_data["submission_version"]
                or not submission.report_version_id
                or not section.task.publication.rubric_version_id
            ):
                raise StateConflict(detail={"submission": "report_or_current_version_required"})
            rubric = [
                {
                    "criterion_id": item.public_id,
                    "title": item.title,
                    "max_score": str(item.max_score),
                }
                for item in section.task.publication.rubric_version.criteria.filter(is_active=True)
            ]
            try:
                suggestion = assess_submission(
                    report=submission.report_version.body_markdown,
                    rubric=rubric,
                )
                maximum = {item["criterion_id"]: item["max_score"] for item in rubric}
                from decimal import Decimal

                if (
                    len(suggestion.criteria) != len(maximum)
                    or {item.criterion_id for item in suggestion.criteria} != set(maximum)
                    or any(
                        item.score > Decimal(maximum[item.criterion_id])
                        for item in suggestion.criteria
                    )
                ):
                    raise ValueError("invalid suggested scores")
            except Exception as exc:
                raise StateConflict(detail={"ai_report": "suggestion_unavailable"}) from exc
            return StoredResponse(
                200,
                _body(
                    request,
                    {
                        "submission_version": submission.version_no,
                        "criteria": suggestion.model_dump(mode="json")["criteria"],
                    },
                ),
                {},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


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
        report = (
            programming.current_submission.report_version
            if (programming and programming.current_submission_id)
            else None
        )
        sources = []
        if programming and programming.current_submission_id:
            from .assessment_workers import _read_source

            sources = [
                {
                    "question_id": answer.question.public_id,
                    "language": answer.language,
                    "files": _read_source(answer.code_snapshot),
                }
                for answer in programming.current_submission.answers.select_related(
                    "question",
                    "code_snapshot__asset",
                )
                if answer.code_snapshot_id
            ]
        choice = next((s for s in sections if s.kind == "CHOICE"), None)
        choice_answers = choice_review_data(choice) if choice else []
        parts = part_scores(task) if session_for(task) else []
        section_rows = [section_result(section, student=False) for section in sections]
        program_part = next((part for part in parts if part["kind"] == "PROGRAMMING"), None)
        if program_part:
            from .assessment_workers import _read_source

            submissions = ProgrammingSubmission.objects.filter(task=task).select_related(
                "question__publication_chapter", "code_snapshot__asset",
            ).order_by("question__publication_chapter__sort_order", "question__sort_order")
            program_questions = []
            for submission in submissions:
                question = submission.question
                sources.append({
                    "question_id": question.public_id,
                    "language": submission.code_snapshot.language,
                    "files": _read_source(submission.code_snapshot),
                })
                program_questions.append({
                    "id": question.public_id, "title": question.title,
                    "description": question.description, "instructions": question.instructions,
                    "language": submission.code_snapshot.language,
                    "samples": question.question_spec.get("samples", [])[:2],
                })
            section_rows.append({
                **program_part, "questions": program_questions,
                "grading_status": "COMPLETED" if program_part["status"] == "SUBMITTED"
                else "NOT_SUBMITTED",
                "submission_version": None, "row_version": 1,
            })
        history = [
            {
                "kind": section.kind,
                "versions": [
                    {
                        "version_no": submission.version_no,
                        "submitted_at": submission.submitted_at,
                    }
                    for submission in section.sectionsubmission_set.order_by("version_no")
                ],
            }
            for section in sections
        ]
        return _response(
            request,
            {
                "task_id": task.public_id,
                "student_name": task.student.display_name,
                "sections": section_rows,
                "parts": parts,
                "choice_answers": choice_answers,
                "report": {"body_markdown": report.body_markdown, "version_no": report.version_no}
                if report
                else None,
                "report_criteria": [
                    {
                        "id": criterion.public_id,
                        "title": criterion.title,
                        "max_score": str(criterion.max_score),
                    }
                    for criterion in task.publication.rubric_version.criteria.all()
                ]
                if task.publication.rubric_version_id and task.publication.report_required
                else [],
                "history": history,
                "sources": sources,
            },
        )

    @extend_schema(
        request=AssessmentReviewWriteSerializer,
        responses=AssessmentResponseSerializer,
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
    )
    def post(self, request: HttpRequest, course_id: str, task_id: str) -> Response:
        serializer = AssessmentReviewWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            data = review_programming(
                actor=request.user,
                course_id=course_id,
                task_id=task_id,
                expected_version=parse_if_match(request.headers.get("If-Match")),
                trace_id=str(getattr(request, "trace_id", "")),
                **serializer.validated_data,
            )
            return StoredResponse(200, _body(request, data), {})

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class AssessmentReviewListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = teaching_course(actor=request.user, course_id=course_id)
        sections = (
            AssessmentSection.objects.filter(
                task__course=course,
                current_submission__isnull=False,
            )
            .select_related(
                "task__student",
                "task__publication__rubric_version",
                "task__assessmentsession",
                "current_submission__report_grade",
            )
            .order_by("-updated_at")
        )
        if request.query_params.get("publication_id"):
            sections = sections.filter(
                task__publication__public_id=request.query_params["publication_id"]
            )
        programs = ProgrammingSubmission.objects.filter(task__course=course)
        if publication_id := request.query_params.get("publication_id"):
            programs = programs.filter(task__publication__public_id=publication_id)
        programs = programs.values(
            "task__public_id", "task__student__display_name", "task__publication__title",
        ).annotate(last=Max("created_at")).order_by("-last")
        program_rows = [{
            "task_id": item["task__public_id"],
            "student_name": item["task__student__display_name"],
            "title": item["task__publication__title"],
            "kind": "PROGRAMMING", "status": "SUBMITTED", "review_status": "NOT_REQUIRED",
            "version_no": 1, "workspace_flow": True,
        } for item in programs[:500]]
        return _response(
            request,
            {
                "rows": program_rows + [
                    {
                        "task_id": section.task.public_id,
                        "student_name": section.task.student.display_name,
                        "title": section.task.publication.title,
                        "kind": section.kind,
                        "status": section.status,
                        "review_status": report_review_status(section),
                        "version_no": section.current_submission.version_no,
                        "workspace_flow": hasattr(section.task, "assessmentsession"),
                    }
                    for section in sections[:500]
                ]
            },
        )
