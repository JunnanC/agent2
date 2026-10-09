from collections.abc import Callable
from typing import Any

from django.db import transaction
from django.http import HttpRequest
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsPlatformPortal, IsTeachingPortal
from apps.accounts.security import client_ip
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.courses.services import ActorContext

from .assets import asset_for_course, complete_asset_upload, create_asset_upload
from .models import TemplateChapter
from .selectors import (
    options_for_course,
    platform_precheck_summary,
    template_for_course,
    templates_for_course,
    version_for_course,
)
from .serializers import (
    AutoCheckRulesResponseSerializer,
    AutoCheckRulesWriteSerializer,
    PlatformPrecheckSummaryResponseSerializer,
    PrecheckRunListResponseSerializer,
    PrecheckRunResponseSerializer,
    TemplateAssetCreateSerializer,
    TemplateAssetResponseSerializer,
    TemplateAssetUploadResponseSerializer,
    TemplateListResponseSerializer,
    TemplateOptionsResponseSerializer,
    TemplatePatchSerializer,
    TemplateResponseSerializer,
    TemplateVersionListResponseSerializer,
    TemplateVersionResponseSerializer,
    TemplateVersionWriteSerializer,
    TemplateWriteSerializer,
    ReorderWriteSerializer,
    TemplateChapterWriteSerializer,
    TemplateTaskWriteSerializer,
    asset_data,
    precheck_data,
    rule_data,
    template_data,
    version_data,
    chapter_data,
    task_data,
)
from .services import (
    clone_version,
    create_template,
    create_version,
    publish_version,
    replace_rules,
    request_precheck,
    update_template,
    update_version,
    withdraw_version,
    create_chapter,
    update_chapter,
    create_task,
    update_task,
    reorder_chapters,
    reorder_tasks,
)
from .tasks import run_template_precheck, scan_template_asset

IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)
IDEMPOTENCY_KEY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)


def _ctx(request: HttpRequest) -> ActorContext:
    user: User = request.user  # type: ignore[assignment]
    return ActorContext(
        user.public_id,
        str(getattr(request, "portal", "")),
        str(getattr(request, "trace_id", "")),
        client_ip(request),
        request.headers.get("User-Agent", ""),
    )


def _body(request: HttpRequest, data: Any) -> dict[str, object]:
    return {"data": data, "meta": {"trace_id": str(getattr(request, "trace_id", ""))}}


def _response(
    request: HttpRequest, data: Any, *, status: int = 200, etag: int | None = None
) -> Response:
    response = Response(_body(request, data), status=status)
    response["Cache-Control"] = "private, no-store"
    if etag is not None:
        response["ETag"] = etag_for_version(etag)
    return response


def _idempotent(
    request: HttpRequest, *, payload: Any, operation: Callable[[], StoredResponse]
) -> Response:
    user: User = request.user  # type: ignore[assignment]
    result = execute_idempotent(
        principal=PrincipalScope(user.public_id, "SESSION", str(request.portal)),
        method=request.method,
        endpoint=request.path,
        key=getattr(request, "idempotency_key", None),
        payload=payload,
        operation=operation,
    )
    response = Response(result.body, status=result.status_code, headers=dict(result.headers))
    response["Cache-Control"] = "private, no-store"
    if result.replayed:
        response["X-Idempotent-Replayed"] = "true"
    return response


class TemplateOptionsView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_template_options",
        responses={200: TemplateOptionsResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        return _response(request, options_for_course(actor=request.user, course_id=course_id))


class TemplateListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_templates_list",
        responses={200: TemplateListResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        return _response(
            request,
            [
                template_data(item)
                for item in templates_for_course(actor=request.user, course_id=course_id)
            ],
        )

    @extend_schema(
        operation_id="teaching_templates_create",
        request=TemplateWriteSerializer,
        responses={201: TemplateResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = TemplateWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            values = serializer.validated_data
            item = create_template(
                course_id=course_id,
                actor=request.user,
                context=_ctx(request),
                name=values["name"],
                category=values.get("category", ""),
                description=values.get("description", ""),
            )
            return StoredResponse(
                201,
                _body(request, template_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TemplateDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_templates_retrieve",
        responses={200: TemplateResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, template_id: str) -> Response:
        item = template_for_course(actor=request.user, course_id=course_id, template_id=template_id)
        return _response(request, template_data(item), etag=item.row_version)

    @extend_schema(
        operation_id="teaching_templates_update",
        request=TemplatePatchSerializer,
        responses={200: TemplateResponseSerializer},
        parameters=[IF_MATCH],
        extensions={"x-portals": ["TEACHING"]},
    )
    def patch(self, request: HttpRequest, course_id: str, template_id: str) -> Response:
        serializer = TemplatePatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = update_template(
            course_id=course_id,
            template_id=template_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            changes=serializer.validated_data,
            context=_ctx(request),
        )
        return _response(request, template_data(item), etag=item.row_version)


class TemplateVersionListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_template_versions_list",
        responses={200: TemplateVersionListResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, template_id: str) -> Response:
        item = template_for_course(actor=request.user, course_id=course_id, template_id=template_id)
        versions = (
            item.versions.select_related(
                "template",
                "runtime_adapter",
                "image",
                "resource_profile",
                "manual_asset",
                "starter_asset",
                "report_template_asset",
            )
            .prefetch_related("auto_check_rules")
            .order_by("-version_no")
        )
        return _response(request, [version_data(version) for version in versions])

    @extend_schema(
        operation_id="teaching_template_versions_create",
        request=TemplateVersionWriteSerializer,
        responses={201: TemplateVersionResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, template_id: str) -> Response:
        serializer = TemplateVersionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            version = create_version(
                course_id=course_id,
                template_id=template_id,
                actor=request.user,
                data=serializer.validated_data,
                context=_ctx(request),
            )
            return StoredResponse(
                201,
                _body(request, version_data(version)),
                {"ETag": etag_for_version(version.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TemplateVersionDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_template_versions_retrieve",
        responses={200: TemplateVersionResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        item = version_for_course(actor=request.user, course_id=course_id, version_id=version_id)
        return _response(request, version_data(item), etag=item.row_version)

    @extend_schema(
        operation_id="teaching_template_versions_update",
        request=TemplateVersionWriteSerializer,
        responses={200: TemplateVersionResponseSerializer},
        parameters=[IF_MATCH],
        extensions={"x-portals": ["TEACHING"]},
    )
    def patch(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        serializer = TemplateVersionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = update_version(
            course_id=course_id,
            version_id=version_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            changes=serializer.validated_data,
            context=_ctx(request),
        )
        return _response(request, version_data(item), etag=item.row_version)


class TemplateAssetCollectionView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_template_assets_create",
        request=TemplateAssetCreateSerializer,
        responses={201: TemplateAssetUploadResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, template_id: str) -> Response:
        serializer = TemplateAssetCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            asset, upload = create_asset_upload(
                course_id=course_id,
                template_id=template_id,
                actor=request.user,
                expected_version=expected,
                context=_ctx(request),
                **serializer.validated_data,
            )
            version = version_for_course(
                actor=request.user,
                course_id=course_id,
                version_id=serializer.validated_data["version_id"],
            )
            return StoredResponse(
                201,
                _body(request, {"asset": asset_data(asset, version), "upload": upload}),
                {"ETag": etag_for_version(asset.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class TemplateAssetDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_template_assets_retrieve",
        responses={200: TemplateAssetResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(
        self, request: HttpRequest, course_id: str, template_id: str, asset_id: str
    ) -> Response:
        asset, version = asset_for_course(
            actor=request.user,
            course_id=course_id,
            template_id=template_id,
            asset_id=asset_id,
        )
        return _response(request, asset_data(asset, version), etag=asset.row_version)


class TemplateAssetCompleteView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_template_assets_complete",
        request=None,
        responses={202: TemplateAssetResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(
        self, request: HttpRequest, course_id: str, template_id: str, asset_id: str
    ) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            asset = complete_asset_upload(
                actor=request.user,
                course_id=course_id,
                template_id=template_id,
                asset_id=asset_id,
                expected_version=expected,
                context=_ctx(request),
            )
            _asset, version = asset_for_course(
                actor=request.user,
                course_id=course_id,
                template_id=template_id,
                asset_id=asset_id,
            )
            trace_id = str(getattr(request, "trace_id", ""))
            transaction.on_commit(
                lambda: scan_template_asset.delay(asset.public_id, trace_id), robust=True
            )
            return StoredResponse(
                202,
                _body(request, asset_data(asset, version)),
                {"ETag": etag_for_version(asset.row_version)},
            )

        return _idempotent(request, payload={}, operation=operation)


class AutoCheckRuleView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_auto_check_rules_list",
        responses={200: AutoCheckRulesResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        version = version_for_course(actor=request.user, course_id=course_id, version_id=version_id)
        return _response(
            request,
            {
                "rules": [
                    rule_data(item)
                    for item in version.auto_check_rules.filter(is_active=True).order_by("position")
                ]
            },
            etag=version.row_version,
        )

    @extend_schema(
        operation_id="teaching_auto_check_rules_replace",
        request=AutoCheckRulesWriteSerializer,
        responses={200: TemplateVersionResponseSerializer},
        parameters=[IF_MATCH],
        extensions={"x-portals": ["TEACHING"]},
    )
    def put(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        serializer = AutoCheckRulesWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        version = replace_rules(
            course_id=course_id,
            version_id=version_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            rules=serializer.validated_data["rules"],
            context=_ctx(request),
        )
        version = version_for_course(
            actor=request.user, course_id=course_id, version_id=version.public_id
        )
        return _response(request, version_data(version), etag=version.row_version)


class TemplateChapterCollectionView(APIView):
    permission_classes = [IsTeachingPortal]

    def get(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        version = version_for_course(actor=request.user, course_id=course_id, version_id=version_id)
        return _response(request, version_data(version)["chapters"], etag=version.row_version)

    def post(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        serializer = TemplateChapterWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chapter = create_chapter(course_id=course_id, version_id=version_id, actor=request.user, expected_version=parse_if_match(request.headers.get("If-Match")), data=serializer.validated_data, context=_ctx(request))
        version = version_for_course(actor=request.user, course_id=course_id, version_id=version_id)
        return _response(request, chapter_data(chapter, version), status=201, etag=version.row_version)


class TemplateChapterDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    def patch(self, request: HttpRequest, course_id: str, chapter_id: str) -> Response:
        serializer = TemplateChapterWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chapter = update_chapter(course_id=course_id, chapter_id=chapter_id, actor=request.user, expected_version=parse_if_match(request.headers.get("If-Match")), changes=serializer.validated_data, context=_ctx(request))
        version = version_for_course(actor=request.user, course_id=course_id, version_id=chapter.template_version.public_id)
        return _response(request, chapter_data(chapter, version), etag=chapter.row_version)


class TemplateChapterReorderView(APIView):
    permission_classes = [IsTeachingPortal]

    def post(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        serializer = ReorderWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        version = reorder_chapters(course_id=course_id, version_id=version_id, actor=request.user, expected_version=parse_if_match(request.headers.get("If-Match")), chapter_ids=serializer.validated_data["ids"], context=_ctx(request))
        return _response(request, version_data(version), etag=version.row_version)


class TemplateTaskCollectionView(APIView):
    permission_classes = [IsTeachingPortal]

    def get(self, request: HttpRequest, course_id: str, chapter_id: str) -> Response:
        try:
            chapter = TemplateChapter.objects.select_related("template_version").get(public_id=chapter_id)
        except TemplateChapter.DoesNotExist as exc:
            from apps.core.errors import ResourceNotFound
            raise ResourceNotFound() from exc
        version = version_for_course(actor=request.user, course_id=course_id, version_id=chapter.template_version.public_id)
        return _response(request, [task_data(task, version) for task in chapter.tasks.all().order_by("sort_order")])

    def post(self, request: HttpRequest, course_id: str, chapter_id: str) -> Response:
        serializer = TemplateTaskWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chapter = TemplateChapter.objects.select_related("template_version").get(public_id=chapter_id)
        task = create_task(course_id=course_id, chapter_id=chapter_id, actor=request.user, expected_version=parse_if_match(request.headers.get("If-Match")), data=serializer.validated_data, context=_ctx(request))
        version = version_for_course(actor=request.user, course_id=course_id, version_id=task.chapter.template_version.public_id)
        return _response(request, task_data(task, version), status=201, etag=version.row_version)


class TemplateTaskDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    def patch(self, request: HttpRequest, course_id: str, task_id: str) -> Response:
        serializer = TemplateTaskWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = update_task(course_id=course_id, task_id=task_id, actor=request.user, expected_version=parse_if_match(request.headers.get("If-Match")), changes=serializer.validated_data, context=_ctx(request))
        version = version_for_course(actor=request.user, course_id=course_id, version_id=task.chapter.template_version.public_id)
        return _response(request, task_data(task, version), etag=task.row_version)


class TemplateTaskReorderView(APIView):
    permission_classes = [IsTeachingPortal]

    def post(self, request: HttpRequest, course_id: str, chapter_id: str) -> Response:
        serializer = ReorderWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chapter = TemplateChapter.objects.select_related("template_version").get(public_id=chapter_id)
        version = reorder_tasks(course_id=course_id, chapter_id=chapter_id, actor=request.user, expected_version=parse_if_match(request.headers.get("If-Match")), task_ids=serializer.validated_data["ids"], context=_ctx(request))
        return _response(request, version_data(version), etag=version.row_version)


class PrecheckView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_template_precheck_create",
        request=None,
        responses={202: PrecheckRunResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            run = request_precheck(
                course_id=course_id,
                version_id=version_id,
                actor=request.user,
                expected_version=expected,
                context=_ctx(request),
            )
            transaction.on_commit(lambda: run_template_precheck.delay(run.public_id), robust=True)
            return StoredResponse(202, _body(request, precheck_data(run)), {})

        return _idempotent(request, payload={}, operation=operation)


class PrecheckRunListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_template_prechecks_list",
        responses={200: PrecheckRunListResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        version = version_for_course(actor=request.user, course_id=course_id, version_id=version_id)
        runs = version.precheck_runs.select_related("template_version").order_by("-created_at")
        return _response(request, [precheck_data(item) for item in runs])


class VersionActionView(APIView):
    permission_classes = [IsTeachingPortal]
    action = ""

    @extend_schema(
        operation_id="teaching_template_version_action",
        request=None,
        responses={200: TemplateVersionResponseSerializer, 201: TemplateVersionResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            if self.action == "publish":
                item = publish_version(
                    course_id=course_id,
                    version_id=version_id,
                    actor=request.user,
                    expected_version=expected,
                    context=_ctx(request),
                )
                status = 200
            elif self.action == "withdraw":
                item = withdraw_version(
                    course_id=course_id,
                    version_id=version_id,
                    actor=request.user,
                    expected_version=expected,
                    context=_ctx(request),
                )
                status = 200
            else:
                item = clone_version(
                    course_id=course_id,
                    version_id=version_id,
                    actor=request.user,
                    expected_version=expected,
                    context=_ctx(request),
                )
                status = 201
            item = version_for_course(
                actor=request.user, course_id=course_id, version_id=item.public_id
            )
            return StoredResponse(
                status,
                _body(request, version_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload={"action": self.action}, operation=operation)


@extend_schema_view(post=extend_schema(operation_id="teaching_template_versions_publish"))
class PublishVersionView(VersionActionView):
    action = "publish"


@extend_schema_view(post=extend_schema(operation_id="teaching_template_versions_withdraw"))
class WithdrawVersionView(VersionActionView):
    action = "withdraw"


@extend_schema_view(post=extend_schema(operation_id="teaching_template_versions_clone"))
class CloneVersionView(VersionActionView):
    action = "clone"


class PlatformPrecheckSummaryView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_template_prechecks_summary",
        responses={200: PlatformPrecheckSummaryResponseSerializer},
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        return _response(request, platform_precheck_summary())
