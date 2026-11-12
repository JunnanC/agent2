from django.http import HttpRequest
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsTeachingPortal
from apps.core.concurrency import parse_if_match
from apps.core.errors import ResourceNotFound
from apps.core.idempotency import StoredResponse
from apps.provisioning.assessment_judge import read_private_tests

from .assessment_assets import store_question_tests
from .choice_import_views import ChoiceImportResponseSerializer
from .models import TemplateTask
from .selectors import version_for_course
from .views import IDEMPOTENCY_KEY, IF_MATCH, _body, _ctx, _idempotent, _response


class AssessmentTestsWriteSerializer(serializers.Serializer):
    groups = serializers.ListField(child=serializers.DictField())
    scores = serializers.ListField(child=serializers.DictField())


class AssessmentTestsAssetView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        request=AssessmentTestsWriteSerializer, responses=ChoiceImportResponseSerializer,
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
    )
    def post(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        serializer = AssessmentTestsWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            data = store_question_tests(
                actor=request.user, course_id=course_id, version_id=version_id,
                expected_version=parse_if_match(request.headers.get("If-Match")),
                context=_ctx(request), **serializer.validated_data,
            )
            return StoredResponse(201, _body(request, data), {})

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class AssessmentQuestionTestsView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(responses=ChoiceImportResponseSerializer)
    def get(self, request: HttpRequest, course_id: str, question_id: str) -> Response:
        try:
            question = TemplateTask.objects.select_related("chapter__template_version").get(
                public_id=question_id,
            )
        except TemplateTask.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        version = version_for_course(
            actor=request.user, course_id=course_id,
            version_id=question.chapter.template_version.public_id,
        )
        _, data = read_private_tests(
            asset_id=question.marking_spec.get("tests_asset_id", ""),
            template_version_id=version.public_id,
        )
        return _response(request, data)
