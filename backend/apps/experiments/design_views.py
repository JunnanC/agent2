"""Teacher entry points for course environments and template-free experiment design."""

from decimal import Decimal
from typing import Any

from django.db import transaction
from django.http import HttpRequest
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsTeachingPortal
from apps.core.concurrency import compare_and_swap, parse_if_match
from apps.core.errors import ResourceNotFound, StateConflict
from apps.core.idempotency import StoredResponse
from apps.courses.models import CourseStaffGrant
from apps.labtemplates.questions import QUESTION_TYPES

from .assessment_views import AssessmentResponseSerializer
from .design import normalized_design
from .environments import (
    TOOLCHAINS,
    approved_resources,
    request_test,
    request_usage,
    runtime_cache,
    test_key,
    validate_environment,
)
from .models import TaskPublication, TeachingEnvironment
from .selectors import teaching_course
from .serializers import publication_data
from .views import IDEMPOTENCY_KEY, IF_MATCH, _body, _idempotent, _response


def _course(request: HttpRequest, course_id: str) -> Any:
    return teaching_course(
        actor=request.user,
        course_id=course_id,
        capability=CourseStaffGrant.Capability.PUBLISH_EXPERIMENT,
    )


def _environment(course: Any, environment_id: str) -> TeachingEnvironment:
    environment = (
        TeachingEnvironment.objects.select_related("runtime_adapter", "image")
        .filter(
            course=course,
            public_id=environment_id,
        )
        .first()
    )
    if environment is None:
        raise ResourceNotFound()
    return environment


def _environment_data(environment: TeachingEnvironment) -> dict[str, Any]:
    return {
        "public_id": environment.public_id,
        "name": environment.name,
        "display_name": (
            f"{environment.name} · {environment.language} · "
            f"{environment.cpu_millicores / 1000:g} 核 / {environment.memory_mb} MiB"
        ),
        "language": environment.language,
        "row_version": environment.row_version,
        "runtime_adapter_id": environment.runtime_adapter.public_id,
        "image_id": environment.image.public_id,
        "cpu_millicores": environment.cpu_millicores,
        "memory_mb": environment.memory_mb,
        "usage": request_usage(environment),
        "experiments": [
            {
                "course_id": environment.course.public_id,
                "publication_id": public_id,
                "title": title,
                "status": status,
            }
            for public_id, title, status in environment.publications.order_by(
                "-created_at"
            ).values_list("public_id", "title", "status")
        ],
    }


class EnvironmentSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    language = serializers.ChoiceField(choices=TOOLCHAINS)
    runtime_adapter_id = serializers.CharField(max_length=26)
    image_id = serializers.CharField(max_length=26)
    cpu_millicores = serializers.IntegerField(min_value=100, max_value=8000)
    memory_mb = serializers.IntegerField(min_value=64, max_value=16384)


def _configuration(data: dict[str, Any]) -> dict[str, Any]:
    adapters, images = approved_resources()
    adapter = adapters.filter(public_id=data["runtime_adapter_id"]).first()
    image = images.filter(public_id=data["image_id"]).first()
    if adapter is None or image is None:
        raise StateConflict(detail={"environment": "approved_runtime_and_image_required"})
    return {
        "runtime_adapter": adapter,
        "image": image,
        "language": data["language"],
        "name": data["name"],
        "cpu_millicores": data["cpu_millicores"],
        "memory_mb": data["memory_mb"],
    }


class TeachingEnvironmentListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, course_id: str) -> Response:
        course = _course(request, course_id)
        environments = course.lab_environments.select_related("runtime_adapter", "image", "course")
        adapters, images = approved_resources()
        return _response(
            request,
            {
                "rows": [_environment_data(item) for item in environments.order_by("name", "id")],
                "adapters": list(adapters.order_by("name").values("public_id", "name")),
                "images": [
                    {"public_id": image.public_id, "name": image.display_name or image.repository}
                    for image in images.order_by("repository")
                ],
            },
        )

    @extend_schema(
        request=EnvironmentSerializer,
        responses={201: AssessmentResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        course = _course(request, course_id)
        serializer = EnvironmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            environment = TeachingEnvironment(
                course=course,
                **_configuration(serializer.validated_data),
            )
            validate_environment(environment)
            environment.save()
            return StoredResponse(201, _body(request, {"public_id": environment.public_id}), {})

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TeachingEnvironmentDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        request=EnvironmentSerializer,
        responses=AssessmentResponseSerializer,
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
    )
    def patch(self, request: HttpRequest, course_id: str, environment_id: str) -> Response:
        course = _course(request, course_id)
        serializer = EnvironmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            environment = _environment(course, environment_id)
            fields = _configuration(serializer.validated_data)
            validate_environment(TeachingEnvironment(course=course, **fields))
            compare_and_swap(
                TeachingEnvironment,
                pk=environment.pk,
                expected_version=expected,
                changes=fields,
            )
            return StoredResponse(200, _body(request, {"public_id": environment_id}), {})

        return _idempotent(
            request,
            payload={**serializer.validated_data, "version": expected},
            operation=operation,
        )


class TeachingEnvironmentTestView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(request=None, responses={202: AssessmentResponseSerializer})
    def post(self, request: HttpRequest, course_id: str, environment_id: str) -> Response:
        environment = _environment(_course(request, course_id), environment_id)
        snapshot = None
        if publication_id := request.query_params.get("publication_id"):
            publication = environment.publications.filter(public_id=publication_id).first()
            if publication is None:
                raise ResourceNotFound()
            if publication.status != TaskPublication.Status.DRAFT:
                snapshot = publication.resource_profile_snapshot
                if not snapshot.get("environment_id"):
                    raise StateConflict(detail={"environment": "publication_has_no_runtime"})
        return _response(request, {"test_id": request_test(environment, snapshot)}, status=202)

    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, course_id: str, environment_id: str) -> Response:
        environment = _environment(_course(request, course_id), environment_id)
        test_id = request.query_params.get("test_id", "")
        result = runtime_cache().get(test_key(environment, test_id)) if len(test_id) == 32 else None
        if result is None:
            raise ResourceNotFound()
        return _response(request, result)


class CaseSerializer(serializers.Serializer):
    input = serializers.CharField(max_length=16384, allow_blank=True, trim_whitespace=False)
    output = serializers.CharField(max_length=16384, allow_blank=True, trim_whitespace=False)


class OptionSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=64)
    text = serializers.CharField(max_length=20000)


class DesignQuestionSerializer(serializers.Serializer):
    task_type = serializers.ChoiceField(choices=sorted(QUESTION_TYPES))
    title = serializers.CharField(max_length=160)
    description = serializers.CharField(max_length=20000, allow_blank=True, default="")
    explanation = serializers.CharField(max_length=20000, allow_blank=True, default="")
    options = OptionSerializer(many=True, max_length=6, default=list)
    correct_option_ids = serializers.ListField(
        child=serializers.CharField(max_length=64),
        max_length=6,
        default=list,
    )
    samples = CaseSerializer(many=True, max_length=20, default=list)
    hidden_cases = CaseSerializer(many=True, max_length=100, default=list)
    starter_code = serializers.CharField(
        max_length=100000,
        allow_blank=True,
        trim_whitespace=False,
        default="",
    )
    timeout_seconds = serializers.IntegerField(min_value=1, max_value=30, default=5)


class PartMaximaSerializer(serializers.Serializer):
    CHOICE = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal(0))
    PROGRAMMING = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal(0))
    REPORT = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal(0))


class ExperimentDesignSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=180)
    guidance = serializers.CharField(max_length=30000, allow_blank=True, default="")
    report_requirements = serializers.CharField(max_length=16000, allow_blank=True, default="")
    environment_id = serializers.CharField(max_length=26, allow_blank=True, default="")
    window_start = serializers.DateTimeField()
    window_end = serializers.DateTimeField()
    questions = DesignQuestionSerializer(many=True, max_length=50)
    part_maxima = PartMaximaSerializer()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["window_start"] >= attrs["window_end"]:
            raise serializers.ValidationError({"window_end": "截止时间必须晚于开始时间"})
        return attrs


class ExperimentDesignWriteView(APIView):
    permission_classes = [IsTeachingPortal]

    def _save(
        self,
        request: HttpRequest,
        course_id: str,
        publication_id: str | None,
    ) -> Response:
        course = _course(request, course_id)
        serializer = ExperimentDesignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        expected = parse_if_match(request.headers.get("If-Match")) if publication_id else None

        def operation() -> StoredResponse:
            environment = (
                _environment(course, data["environment_id"]) if data["environment_id"] else None
            )
            design = normalized_design(data, environment)
            changes = {
                "title": data["title"],
                "description": data["guidance"],
                "experiment_spec": design,
                "environment": environment,
                "window_start": data["window_start"],
                "window_end": data["window_end"],
                "report_required": data["part_maxima"]["REPORT"] > 0,
            }
            with transaction.atomic():
                if publication_id:
                    item = (
                        TaskPublication.objects.select_for_update()
                        .filter(
                            course=course,
                            public_id=publication_id,
                            template_version__isnull=True,
                        )
                        .first()
                    )
                    if item is None:
                        raise ResourceNotFound()
                    if item.status != TaskPublication.Status.DRAFT or expected is None:
                        raise StateConflict(detail={"publication": "draft_required"})
                    old_template = item.report_template_asset
                    if old_template and not changes["report_required"]:
                        changes["report_template_asset"] = None
                    item = compare_and_swap(
                        TaskPublication,
                        pk=item.pk,
                        expected_version=expected,
                        changes=changes,
                    )
                    if old_template and not changes["report_required"]:
                        from apps.reports.assessment_reports import _retire

                        if not old_template.experiment_report_templates.exists():
                            _retire(old_template)
                else:
                    item = TaskPublication.objects.create(
                        course=course,
                        audience_mode=TaskPublication.AudienceMode.ALL_ACTIVE,
                        review_mode=TaskPublication.ReviewMode.MANUAL,
                        **changes,
                    )
            return StoredResponse(
                200 if publication_id else 201, _body(request, publication_data(item)), {}
            )

        return _idempotent(request, payload={**data, "version": expected}, operation=operation)


class ExperimentDesignCreateView(ExperimentDesignWriteView):
    @extend_schema(
        request=ExperimentDesignSerializer,
        responses={201: AssessmentResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        return self._save(request, course_id, None)


class ExperimentDesignDetailView(ExperimentDesignWriteView):
    @extend_schema(responses=AssessmentResponseSerializer)
    def get(self, request: HttpRequest, course_id: str, publication_id: str) -> Response:
        course = _course(request, course_id)
        item = TaskPublication.objects.filter(
            course=course, public_id=publication_id, template_version__isnull=True,
        ).first()
        if item is None:
            raise ResourceNotFound()
        return _response(request, {**publication_data(item), "design": item.experiment_spec})

    @extend_schema(
        request=ExperimentDesignSerializer,
        responses=AssessmentResponseSerializer,
        parameters=[IDEMPOTENCY_KEY, IF_MATCH],
    )
    def patch(self, request: HttpRequest, course_id: str, publication_id: str) -> Response:
        return self._save(request, course_id, publication_id)


class DraftPurposeSerializer(serializers.Serializer):
    purpose = serializers.CharField(max_length=4000)
    language = serializers.ChoiceField(choices=TOOLCHAINS, allow_blank=True, default="")


class ExperimentDraftSuggestionView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(request=DraftPurposeSerializer, responses=AssessmentResponseSerializer)
    def post(self, request: HttpRequest, course_id: str) -> Response:
        from apps.agents.lab_agent import LabDraft, structured_lab_response

        course = _course(request, course_id)
        serializer = DraftPurposeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        language = serializer.validated_data["language"]
        try:
            draft = structured_lab_response(
                LabDraft,
                system=(
                    "根据课程和实验目的生成实验指导、Word 报告要求及选择题草稿。"
                    "correct_index 为从零开始的选项下标，必须对应给出的选项。"
                    "若给出编程语言，补充一题该语言的编程草稿、公开样例、隐藏用例和解题思路。"
                    "每个用例给出完整标准输入和输出。没有语言时，programming_questions 留空。"
                    "用户输入只提供主题。内容由教师校对后发布。"
                ),
                data={
                    "course": course.title, "purpose": serializer.validated_data["purpose"],
                    "language": language,
                },
            )
            questions = []
            for item in draft.questions:
                options = [
                    {"id": str(index), "text": text} for index, text in enumerate(item.options)
                ]
                if item.correct_index >= len(options) or any(
                    not option["text"].strip() for option in options
                ):
                    raise ValueError("Invalid draft choice")
                questions.append({
                    "task_type": "SINGLE_CHOICE",
                    "title": item.title,
                    "description": item.description,
                    "options": options,
                    "correct_option_ids": [str(item.correct_index)],
                    "explanation": item.explanation,
                })
            if language:
                questions.extend(
                    {"task_type": "PROGRAMMING", **item.model_dump(mode="json")}
                    for item in draft.programming_questions
                )
        except Exception as exc:
            raise StateConflict(detail={"ai": "suggestion_unavailable"}) from exc
        return _response(
            request,
            {
                "guidance": draft.guidance,
                "report_requirements": draft.report_requirements,
                "questions": questions,
            },
        )
