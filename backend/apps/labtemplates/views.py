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
from apps.core.errors import ResourceNotFound
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.courses.models import CourseStaffGrant
from apps.courses.services import ActorContext

from .assets import asset_for_course, assets_for_version, complete_asset_upload, create_asset_upload
from .image_services import (
    build_args_digest,
    create_experiment_image,
    retire_experiment_image,
    validate_prepare_build_args,
)
from .models import ExperimentImage, TemplateChapter
from .selectors import (
    options_for_course,
    platform_precheck_summary,
    teaching_course,
    template_for_course,
    templates_for_course,
    version_for_course,
)
from .serializers import (
    ExperimentImageCreateSerializer,
    ExperimentImageEventsResponseSerializer,
    ExperimentImageListResponseSerializer,
    ExperimentImagePrepareSerializer,
    ExperimentImageResponseSerializer,
    PlatformPrecheckSummaryResponseSerializer,
    PrecheckRunListResponseSerializer,
    PrecheckRunResponseSerializer,
    ReorderWriteSerializer,
    TemplateAssetCreateSerializer,
    TemplateAssetListResponseSerializer,
    TemplateAssetResponseSerializer,
    TemplateAssetUploadResponseSerializer,
    TemplateChapterListResponseSerializer,
    TemplateChapterResponseSerializer,
    TemplateChapterWriteSerializer,
    TemplateListResponseSerializer,
    TemplateOptionsResponseSerializer,
    TemplatePatchSerializer,
    TemplateResponseSerializer,
    TemplateTaskListResponseSerializer,
    TemplateTaskResponseSerializer,
    TemplateTaskWriteSerializer,
    TemplateVersionListResponseSerializer,
    TemplateVersionResponseSerializer,
    TemplateVersionWriteSerializer,
    TemplateWriteSerializer,
    asset_data,
    chapter_data,
    experiment_image_data,
    precheck_data,
    task_data,
    template_data,
    version_data,
)
from .services import (
    clone_version,
    create_chapter,
    create_task,
    create_template,
    create_version,
    delete_template,
    publish_version,
    reorder_chapters,
    reorder_tasks,
    request_precheck,
    update_chapter,
    update_task,
    update_template,
    update_version,
    withdraw_version,
)
from .tasks import prepare_experiment_image_task, run_template_precheck, scan_template_asset

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


class ExperimentImageCollectionView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_experiment_images_list",
        responses={200: ExperimentImageListResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        teaching_course(
            actor=request.user,
            course_id=course_id,
            capability=CourseStaffGrant.Capability.MANAGE_TEMPLATE,
        )
        images = (
            ExperimentImage.objects.filter(template_version__template__course__public_id=course_id)
            .select_related("template_version", "image_asset", "build_context_asset")
            .order_by("-created_at")
        )
        return _response(request, [experiment_image_data(item) for item in images])

    @extend_schema(
        operation_id="teaching_experiment_images_create",
        request=ExperimentImageCreateSerializer,
        responses={201: ExperimentImageResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = ExperimentImageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        teaching_course(
            actor=request.user,
            course_id=course_id,
            capability=CourseStaffGrant.Capability.MANAGE_TEMPLATE,
        )

        def operation() -> StoredResponse:
            values = serializer.validated_data
            version = version_for_course(
                actor=request.user, course_id=course_id, version_id=values["template_version_id"]
            )
            image = create_experiment_image(
                template_version=version, actor=request.user, context=_ctx(request), **values
            )
            return StoredResponse(
                201,
                _body(request, experiment_image_data(image)),
                {"ETag": etag_for_version(image.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class ExperimentImageDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_experiment_images_retrieve",
        responses={200: ExperimentImageResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, image_id: str) -> Response:
        try:
            image = ExperimentImage.objects.get(public_id=image_id)
        except ExperimentImage.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        version = version_for_course(
            actor=request.user, course_id=course_id, version_id=image.template_version.public_id
        )
        item = ExperimentImage.objects.select_related(
            "template_version", "image_asset", "build_context_asset"
        ).get(public_id=image_id, template_version=version)
        return _response(request, experiment_image_data(item), etag=item.row_version)


class ExperimentImagePrepareView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_experiment_images_prepare",
        request=ExperimentImagePrepareSerializer,
        responses={202: ExperimentImageResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, image_id: str) -> Response:
        try:
            item = ExperimentImage.objects.select_related("template_version").get(
                public_id=image_id
            )
        except ExperimentImage.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        version_for_course(
            actor=request.user, course_id=course_id, version_id=item.template_version.public_id
        )
        serializer = ExperimentImagePrepareSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        trace_id = str(getattr(request, "trace_id", ""))
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            current = ExperimentImage.objects.get(pk=item.pk)
            if current.row_version != expected:
                from apps.core.errors import RowVersionConflict

                raise RowVersionConflict(
                    detail={
                        "expected_row_version": expected,
                        "actual_row_version": current.row_version,
                    }
                )
            if "build_args" in serializer.validated_data:
                validate_prepare_build_args(
                    image=current, build_args=serializer.validated_data["build_args"]
                )
            transaction.on_commit(
                lambda: prepare_experiment_image_task.delay(
                    image_id, trace_id
                ),
                robust=True,
            )
            return StoredResponse(
                202,
                _body(request, experiment_image_data(current)),
                {"ETag": etag_for_version(current.row_version)},
            )

        prepare_payload = {
            "build_args_digest": build_args_digest(
                serializer.validated_data.get("build_args", {})
            )
        }
        return _idempotent(
            request,
            payload=prepare_payload,
            operation=operation,
        )


class ExperimentImageRetireView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_experiment_images_retire",
        request=None,
        responses={200: ExperimentImageResponseSerializer},
        parameters=[IF_MATCH],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, image_id: str) -> Response:
        try:
            item = ExperimentImage.objects.select_related("template_version").get(
                public_id=image_id
            )
        except ExperimentImage.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        version_for_course(
            actor=request.user, course_id=course_id, version_id=item.template_version.public_id
        )
        item = retire_experiment_image(
            image_id=image_id,
            context=_ctx(request),
            expected_version=parse_if_match(request.headers.get("If-Match")),
        )
        return _response(request, experiment_image_data(item), etag=item.row_version)


class ExperimentImageEventsView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_experiment_images_events",
        responses={200: ExperimentImageEventsResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, image_id: str) -> Response:
        from apps.core.models import OutboxEvent

        try:
            item = ExperimentImage.objects.select_related("template_version").get(
                public_id=image_id
            )
        except ExperimentImage.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        version_for_course(
            actor=request.user, course_id=course_id, version_id=item.template_version.public_id
        )
        events_data = list(
            OutboxEvent.objects.filter(aggregate_type="experiment_image", aggregate_ref=image_id)
            .order_by("created_at")
            .values("event_type", "payload", "trace_id", "created_at")
        )
        return _response(request, events_data)


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

    @extend_schema(
        operation_id="teaching_templates_delete",
        responses={200: TemplateResponseSerializer},
        parameters=[IF_MATCH],
        extensions={"x-portals": ["TEACHING"]},
    )
    def delete(self, request: HttpRequest, course_id: str, template_id: str) -> Response:
        item = delete_template(
            course_id=course_id,
            template_id=template_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
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
        operation_id="teaching_template_assets_list",
        responses={200: TemplateAssetListResponseSerializer},
        parameters=[OpenApiParameter("version_id", str, required=True)],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, template_id: str) -> Response:
        version, assets = assets_for_version(
            actor=request.user,
            course_id=course_id,
            template_id=template_id,
            version_id=str(request.query_params.get("version_id", "")),
        )
        return _response(request, [asset_data(asset, version) for asset in assets])

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


class TemplateChapterCollectionView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_template_chapters_list",
        responses={200: TemplateChapterListResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        version = version_for_course(actor=request.user, course_id=course_id, version_id=version_id)
        return _response(request, version_data(version)["chapters"], etag=version.row_version)

    @extend_schema(
        operation_id="teaching_template_chapters_create",
        request=TemplateChapterWriteSerializer,
        responses={201: TemplateChapterResponseSerializer},
        parameters=[IF_MATCH],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        serializer = TemplateChapterWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chapter = create_chapter(
            course_id=course_id,
            version_id=version_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            data=serializer.validated_data,
            context=_ctx(request),
        )
        version = version_for_course(actor=request.user, course_id=course_id, version_id=version_id)
        return _response(
            request, chapter_data(chapter, version), status=201, etag=version.row_version
        )


class TemplateChapterDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_template_chapters_update",
        request=TemplateChapterWriteSerializer,
        responses={200: TemplateChapterResponseSerializer},
        parameters=[IF_MATCH],
        extensions={"x-portals": ["TEACHING"]},
    )
    def patch(self, request: HttpRequest, course_id: str, chapter_id: str) -> Response:
        serializer = TemplateChapterWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chapter = update_chapter(
            course_id=course_id,
            chapter_id=chapter_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            changes=serializer.validated_data,
            context=_ctx(request),
        )
        version = version_for_course(
            actor=request.user, course_id=course_id, version_id=chapter.template_version.public_id
        )
        return _response(request, chapter_data(chapter, version), etag=version.row_version)


class TemplateChapterReorderView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_template_chapters_reorder",
        request=ReorderWriteSerializer,
        responses={200: TemplateVersionResponseSerializer},
        parameters=[IF_MATCH],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        serializer = ReorderWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        version = reorder_chapters(
            course_id=course_id,
            version_id=version_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            chapter_ids=serializer.validated_data["ids"],
            context=_ctx(request),
        )
        return _response(request, version_data(version), etag=version.row_version)


class TemplateTaskCollectionView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_template_tasks_list",
        responses={200: TemplateTaskListResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, chapter_id: str) -> Response:
        try:
            chapter = TemplateChapter.objects.select_related("template_version").get(
                public_id=chapter_id
            )
        except TemplateChapter.DoesNotExist as exc:
            from apps.core.errors import ResourceNotFound

            raise ResourceNotFound() from exc
        version = version_for_course(
            actor=request.user, course_id=course_id, version_id=chapter.template_version.public_id
        )
        return _response(
            request,
            [task_data(task, version)
             for task in chapter.tasks.filter(active=True).order_by("sort_order")],
        )

    @extend_schema(
        operation_id="teaching_template_tasks_create",
        request=TemplateTaskWriteSerializer,
        responses={201: TemplateTaskResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, chapter_id: str) -> Response:
        if not TemplateChapter.objects.filter(
            public_id=chapter_id, template_version__template__course__public_id=course_id
        ).exists():
            raise ResourceNotFound()
        serializer = TemplateTaskWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = create_task(
            course_id=course_id,
            chapter_id=chapter_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            data=serializer.validated_data,
            context=_ctx(request),
        )
        version = version_for_course(
            actor=request.user,
            course_id=course_id,
            version_id=task.chapter.template_version.public_id,
        )
        return _response(request, task_data(task, version), status=201, etag=version.row_version)


class TemplateTaskDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(responses={200: TemplateTaskResponseSerializer}, parameters=[IF_MATCH])
    def delete(self, request: HttpRequest, course_id: str, task_id: str) -> Response:
        task = update_task(
            course_id=course_id, task_id=task_id, actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            changes={"active": False}, context=_ctx(request),
        )
        return _response(request, {"public_id": task.public_id, "deleted": True})

    @extend_schema(
        operation_id="teaching_template_tasks_update",
        request=TemplateTaskWriteSerializer,
        responses={200: TemplateTaskResponseSerializer},
        parameters=[IF_MATCH],
        extensions={"x-portals": ["TEACHING"]},
    )
    def patch(self, request: HttpRequest, course_id: str, task_id: str) -> Response:
        serializer = TemplateTaskWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = update_task(
            course_id=course_id,
            task_id=task_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            changes=serializer.validated_data,
            context=_ctx(request),
        )
        version = version_for_course(
            actor=request.user,
            course_id=course_id,
            version_id=task.chapter.template_version.public_id,
        )
        return _response(request, task_data(task, version), etag=version.row_version)


class TemplateTaskReorderView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_template_tasks_reorder",
        request=ReorderWriteSerializer,
        responses={200: TemplateVersionResponseSerializer},
        parameters=[IF_MATCH],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, chapter_id: str) -> Response:
        serializer = ReorderWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        version = reorder_tasks(
            course_id=course_id,
            chapter_id=chapter_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            task_ids=serializer.validated_data["ids"],
            context=_ctx(request),
        )
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
