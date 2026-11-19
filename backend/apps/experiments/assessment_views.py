from typing import Any

from django.http import HttpRequest
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsUserPortal
from apps.core.concurrency import parse_if_match
from apps.core.idempotency import StoredResponse

from .assessment import (
    assessment_data,
    read_draft,
    report_draft,
    request_run,
    save_draft,
    submission_history,
    submit_choices,
    submit_programming,
)
from .models import AssessmentRun
from .selectors import task_for_user
from .views import IDEMPOTENCY_KEY, IF_MATCH, _body, _idempotent, _response


class AssessmentResponseSerializer(serializers.Serializer):
    data = serializers.DictField()
    meta = serializers.DictField()


class DraftWriteSerializer(serializers.Serializer):
    selected_option_ids = serializers.ListField(child=serializers.CharField(), required=False)
    files = serializers.DictField(
        child=serializers.CharField(allow_blank=True, trim_whitespace=False), required=False,
    )


class ChoiceSubmitSerializer(serializers.Serializer):
    versions = serializers.DictField(child=serializers.IntegerField(min_value=1))


class CodeVersionSerializer(serializers.Serializer):
    language = serializers.ChoiceField(choices=("python", "c", "cpp", "java", "go"))
    row_version = serializers.IntegerField(min_value=1)


class ProgrammingSubmitSerializer(serializers.Serializer):
    versions = serializers.DictField(child=CodeVersionSerializer())
    report_version = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class AssessmentReportWriteSerializer(serializers.Serializer):
    body_markdown = serializers.CharField(allow_blank=True, trim_whitespace=False)


class AssessmentRunWriteSerializer(CodeVersionSerializer):
    stdin = serializers.CharField(allow_blank=True, trim_whitespace=False, max_length=1048576)


class WorkspaceAttemptWriteSerializer(CodeVersionSerializer):
    stdin = serializers.CharField(
        allow_blank=True, trim_whitespace=False, max_length=1048576, default="",
    )


def run_data(run: AssessmentRun) -> dict[str, Any]:
    return {
        "id": run.pk, "status": run.status, "result_status": run.result_status,
        "stdout": run.stdout, "stderr": run.stderr, "language": run.snapshot.language,
        "snapshot_digest": run.snapshot.digest_sha256,
    }


class AssessmentView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, task_id: str) -> Response:
        return _response(request, assessment_data(actor=request.user, task_id=task_id))


class AssessmentHistoryView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, task_id: str) -> Response:
        return _response(request, submission_history(actor=request.user, task_id=task_id))


class AssessmentDraftView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(
        self, request: HttpRequest, task_id: str, question_id: str, language: str = "",
    ) -> Response:
        data = read_draft(
            actor=request.user, task_id=task_id, question_id=question_id, language=language,
        )
        return _response(request, data, etag=data["row_version"])

    @extend_schema(
        request=DraftWriteSerializer, responses=AssessmentResponseSerializer, parameters=[IF_MATCH],
    )
    def put(
        self, request: HttpRequest, task_id: str, question_id: str, language: str = "",
    ) -> Response:
        serializer = DraftWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = save_draft(
            actor=request.user, task_id=task_id, question_id=question_id, language=language,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            data=serializer.validated_data,
        )
        return _response(request, data, etag=data["row_version"])


class ChoiceSubmitView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        request=ChoiceSubmitSerializer, responses={201: AssessmentResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: HttpRequest, task_id: str) -> Response:
        serializer = ChoiceSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            submission = submit_choices(
                actor=request.user, task_id=task_id, versions=serializer.validated_data["versions"],
                trace_id=str(getattr(request, "trace_id", "")),
            )
            data: dict[str, Any] = {
                "version_no": submission.version_no, "submitted_at": submission.submitted_at,
            }
            from .assessment_parts import part_scores, session_for

            if session_for(submission.section.task):
                data["part"] = next(
                    row for row in part_scores(submission.section.task) if row["kind"] == "CHOICE"
                )
            return StoredResponse(201, _body(request, data), {})

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class ProgrammingSubmitView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        request=ProgrammingSubmitSerializer, responses={201: AssessmentResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: HttpRequest, task_id: str) -> Response:
        serializer = ProgrammingSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            submission = submit_programming(
                actor=request.user, task_id=task_id, versions=serializer.validated_data["versions"],
                report_version=serializer.validated_data.get("report_version"),
                trace_id=str(getattr(request, "trace_id", "")),
            )
            return StoredResponse(201, _body(request, {
                "version_no": submission.version_no, "submitted_at": submission.submitted_at,
            }), {})

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class AssessmentReportDraftView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, task_id: str) -> Response:
        data = report_draft(actor=request.user, task_id=task_id)
        return _response(request, data, etag=data["row_version"])

    @extend_schema(
        request=AssessmentReportWriteSerializer, responses=AssessmentResponseSerializer,
        parameters=[IF_MATCH],
    )
    def put(self, request: HttpRequest, task_id: str) -> Response:
        serializer = AssessmentReportWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = report_draft(
            actor=request.user, task_id=task_id,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            body_markdown=serializer.validated_data["body_markdown"],
        )
        return _response(request, data, etag=data["row_version"])


class AssessmentRunView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        request=AssessmentRunWriteSerializer, responses={201: AssessmentResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: HttpRequest, task_id: str, question_id: str) -> Response:
        serializer = AssessmentRunWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            run = request_run(
                actor=request.user, task_id=task_id, question_id=question_id,
                language=serializer.validated_data["language"],
                expected_version=serializer.validated_data["row_version"],
                stdin=serializer.validated_data["stdin"],
                trace_id=str(getattr(request, "trace_id", "")),
            )
            return StoredResponse(201, _body(request, run_data(run)), {})

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class AssessmentRunDetailView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, task_id: str, run_id: int) -> Response:
        task = task_for_user(actor=request.user, task_id=task_id)
        from apps.core.errors import ResourceNotFound

        try:
            run = AssessmentRun.objects.select_related("snapshot").get(task=task, pk=run_id)
        except AssessmentRun.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        return _response(request, run_data(run))


class WorkspaceView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, task_id: str) -> Response:
        from .assessment import _task
        from .workspace_assessment import workspace_data

        return _response(request, workspace_data(_task(request.user, task_id)))

    @extend_schema(
        request=None, responses=AssessmentResponseSerializer, parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: HttpRequest, task_id: str) -> Response:
        from .workspace_assessment import enter_workspace

        return _response(request, enter_workspace(actor=request.user, task_id=task_id))


class WorkspaceQuestionView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(request=None, responses=AssessmentResponseSerializer)
    def put(self, request: HttpRequest, task_id: str, question_id: str) -> Response:
        from .workspace_assessment import select_question

        select_question(actor=request.user, task_id=task_id, question_id=question_id)
        return _response(request, {"current_question_id": question_id})


def attempt_data(run: AssessmentRun) -> dict[str, Any]:
    return {
        **run_data(run), "case_results": run.case_results, "submitted": run.submitted,
        "duration_ms": run.duration_ms,
        "next_question_id": run.next_question.public_id if run.next_question_id else None,
    }


class WorkspaceAttemptView(APIView):
    permission_classes = [IsUserPortal]
    mode = AssessmentRun.Mode.SELF_TEST

    @extend_schema(
        request=WorkspaceAttemptWriteSerializer, responses={201: AssessmentResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: HttpRequest, task_id: str, question_id: str) -> Response:
        from .workspace_assessment import request_attempt

        serializer = WorkspaceAttemptWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            run = request_attempt(
                actor=request.user, task_id=task_id, question_id=question_id,
                language=serializer.validated_data["language"],
                expected_version=serializer.validated_data["row_version"],
                stdin=serializer.validated_data["stdin"] if self.mode == "SELF_TEST" else "",
                mode=self.mode,
            )
            return StoredResponse(201, _body(request, attempt_data(run)), {})

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class WorkspaceAttemptDetailView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(
        self, request: HttpRequest, task_id: str, question_id: str, run_id: int,
    ) -> Response:
        from apps.core.errors import ResourceNotFound

        from .assessment import _task

        task = _task(request.user, task_id)
        run = AssessmentRun.objects.select_related("snapshot", "next_question").exclude(
            mode="LEGACY",
        ).filter(task=task, question__public_id=question_id, pk=run_id).first()
        if run is None:
            raise ResourceNotFound()
        return _response(request, attempt_data(run))

