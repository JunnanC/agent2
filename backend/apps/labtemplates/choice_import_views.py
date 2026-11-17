import hashlib

from django.http import HttpRequest, HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsTeachingPortal
from apps.core.idempotency import StoredResponse

from .choice_import import confirm_choices, download_template, preview_choices
from .questions import invalid
from .views import IDEMPOTENCY_KEY, _body, _ctx, _idempotent, _response


class ChoiceImportSerializer(serializers.Serializer):
    file = serializers.FileField()
    token = serializers.CharField(required=False)


class ChoiceImportResponseSerializer(serializers.Serializer):
    data = serializers.DictField()
    meta = serializers.DictField()


class ChoiceImportTemplateView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        responses={
            (200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): bytes,
        }
    )
    def get(self, request: HttpRequest) -> HttpResponse:
        response = HttpResponse(
            download_template(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="choice-import-template.xlsx"'
        response["Cache-Control"] = "private, no-store"
        return response


class ChoiceImportPreviewView(APIView):
    permission_classes = [IsTeachingPortal]
    parser_classes = [MultiPartParser]

    @extend_schema(
        request=ChoiceImportSerializer,
        responses=ChoiceImportResponseSerializer,
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: HttpRequest, course_id: str, chapter_id: str) -> Response:
        serializer = ChoiceImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded = serializer.validated_data["file"]
        if (
            not uploaded.name.lower().endswith((".xlsx", ".docx"))
            or uploaded.size > 10 * 1024 * 1024
        ):
            invalid("file", "xlsx_or_docx_required")
        result = preview_choices(
            actor=request.user,
            course_id=course_id,
            chapter_id=chapter_id,
            content=uploaded.read(10 * 1024 * 1024 + 1),
        )
        return _response(request, result)


class ChoiceImportConfirmView(APIView):
    permission_classes = [IsTeachingPortal]
    parser_classes = [MultiPartParser]

    @extend_schema(
        request=ChoiceImportSerializer,
        responses=ChoiceImportResponseSerializer,
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: HttpRequest, course_id: str, chapter_id: str) -> Response:
        serializer = ChoiceImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded = serializer.validated_data["file"]
        if uploaded.size > 10 * 1024 * 1024:
            invalid("file", "xlsx_size_limit")
        content = uploaded.read(10 * 1024 * 1024 + 1)
        token = serializer.validated_data.get("token", "")

        def operation() -> StoredResponse:
            result = confirm_choices(
                actor=request.user,
                course_id=course_id,
                chapter_id=chapter_id,
                content=content,
                token=token,
                context=_ctx(request),
            )
            return StoredResponse(201, _body(request, result), {})

        return _idempotent(
            request,
            payload={"digest": hashlib.sha256(content).hexdigest(), "token": token},
            operation=operation,
        )
