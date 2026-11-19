import time
from collections.abc import Callable, Iterable
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import SESSION_AUTH_TIME
from apps.accounts.models import User
from apps.accounts.permissions import IsPlatformPortal, IsTeachingPortal, IsUserPortal
from apps.accounts.security import client_ip
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.errors import ResourceNotFound, RowVersionConflict
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.core.pagination import PageSpec

from .errors import GovernanceStateConflict, RecentAuthenticationRequired
from .models import (
    ImageAsset,
    NetworkAllowlist,
    Quota,
    ResourceProfile,
    RuntimeAdapter,
    SecurityPolicy,
)
from .selectors import (
    allowlist_entries,
    images,
    platform_alert_summaries,
    platform_usage_summary,
    policies,
    quotas,
    resource_profiles,
    runtime_adapters,
    student_resource_summary,
    teacher_governance_summary,
)
from .serializers import (
    AlertListResponseSerializer,
    AllowlistCreateSerializer,
    AllowlistListResponseSerializer,
    AllowlistResponseSerializer,
    GovernanceReasonSerializer,
    ImageCreateSerializer,
    ImageDecisionSerializer,
    ImageListResponseSerializer,
    ImageReResolveSerializer,
    ImageResolveSerializer,
    ImageResponseSerializer,
    ImageRenameSerializer,
    ImageScanSerializer,
    PolicyListResponseSerializer,
    PolicyPutSerializer,
    PolicyResponseSerializer,
    QuotaListResponseSerializer,
    QuotaResponseSerializer,
    QuotaWriteSerializer,
    ResourceProfileCreateSerializer,
    ResourceProfileListResponseSerializer,
    ResourceProfileResponseSerializer,
    ResourceProfileUpdateSerializer,
    ResourceSummaryResponseSerializer,
    RuntimeAdapterCreateSerializer,
    RuntimeAdapterListResponseSerializer,
    RuntimeAdapterResponseSerializer,
    RuntimeAdapterUpdateSerializer,
    UsageResponseSerializer,
    allowlist_data,
    image_data,
    policy_data,
    quota_data,
    resource_profile_data,
    runtime_adapter_data,
)
from .services import (
    ActorContext,
    active_container_adapter,
    create_allowlist_entry,
    create_image,
    create_quota,
    create_resource_profile,
    create_runtime_adapter,
    decide_image,
    put_policy,
    rename_image,
    revoke_allowlist_entry,
    transition_resource_profile,
    update_image_scan,
    update_quota,
    update_resource_profile,
    update_runtime_adapter,
)
from .tasks import reresolve_image_digest_task, resolve_image_digest_task

IF_MATCH = OpenApiParameter(
    name="If-Match",
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description="Quoted row version ETag.",
)
IDEMPOTENCY_KEY = OpenApiParameter(
    name="Idempotency-Key",
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description="Stable key for one user intent.",
)
IF_MATCH_OPTIONAL = OpenApiParameter(
    name="If-Match",
    type=str,
    location=OpenApiParameter.HEADER,
    required=False,
    description="Required when replacing an existing policy.",
)


def _context(request: HttpRequest) -> ActorContext:
    user: User = request.user  # type: ignore[assignment]
    return ActorContext(
        actor_ref=user.public_id,
        portal=str(getattr(request, "portal", "")),
        trace_id=str(getattr(request, "trace_id", "")),
        client_ip=client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
    )


def _meta(request: HttpRequest) -> dict[str, str]:
    return {"trace_id": str(getattr(request, "trace_id", ""))}


def _body(request: HttpRequest, data: Any) -> dict[str, object]:
    return {"data": data, "meta": _meta(request)}


def _response(
    request: HttpRequest,
    data: Any,
    *,
    status: int = 200,
    etag: str | None = None,
) -> Response:
    response = Response(_body(request, data), status=status)
    response["Cache-Control"] = "private, no-store"
    if etag:
        response["ETag"] = etag
    return response


def _page_spec(request: HttpRequest) -> PageSpec:
    return PageSpec.parse(request.GET.get("page", 1), request.GET.get("page_size", 20))


def _page_response(
    request: HttpRequest,
    values: Iterable[Any],
    *,
    serializer: Callable[[Any], dict[str, Any]],
) -> Response:
    spec = _page_spec(request)
    all_values = list(values)
    page = all_values[spec.offset : spec.offset + spec.page_size]
    response = Response({
        "data": [serializer(item) for item in page],
        "meta": {
            "page": spec.page,
            "page_size": spec.page_size,
            "total": len(all_values),
            **_meta(request),
        },
    })
    response["Cache-Control"] = "private, no-store"
    return response


def _idempotent_response(
    request: HttpRequest,
    *,
    payload: Any,
    operation: Callable[[], StoredResponse],
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


def _require_recent_auth(request: HttpRequest) -> None:
    authenticated_at = int(request.session.get(SESSION_AUTH_TIME, 0))
    if (
        authenticated_at <= 0
        or int(time.time()) - authenticated_at > settings.PLATFORM_RECENT_AUTH_SECONDS
    ):
        raise RecentAuthenticationRequired()


def _get(model: Any, public_id: str) -> Any:
    try:
        return model.objects.get(public_id=public_id)
    except model.DoesNotExist as exc:
        raise ResourceNotFound() from exc


class RuntimeAdapterListView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_runtime_adapters_list",
        responses={200: RuntimeAdapterListResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        return _page_response(request, runtime_adapters(), serializer=runtime_adapter_data)

    @extend_schema(
        operation_id="platform_runtime_adapters_create",
        request=RuntimeAdapterCreateSerializer,
        responses={201: RuntimeAdapterResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest) -> Response:
        _require_recent_auth(request)
        serializer = RuntimeAdapterCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_runtime_adapter(
                actor=request.user,
                context=_context(request),
                **serializer.validated_data,
            )
            return StoredResponse(
                201,
                _body(request, runtime_adapter_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class RuntimeAdapterDetailView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_runtime_adapters_retrieve",
        responses={200: RuntimeAdapterResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest, adapter_id: str) -> Response:
        item = _get(RuntimeAdapter, adapter_id)
        return _response(
            request,
            runtime_adapter_data(item),
            etag=etag_for_version(item.row_version),
        )

    @extend_schema(
        operation_id="platform_runtime_adapters_update",
        request=RuntimeAdapterUpdateSerializer,
        responses={200: RuntimeAdapterResponseSerializer},
        parameters=[IF_MATCH],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def patch(self, request: HttpRequest, adapter_id: str) -> Response:
        _require_recent_auth(request)
        serializer = RuntimeAdapterUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        reason = data.pop("reason")
        item = update_runtime_adapter(
            adapter_id=adapter_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            changes=data,
            reason=reason,
            context=_context(request),
        )
        return _response(
            request,
            runtime_adapter_data(item),
            etag=etag_for_version(item.row_version),
        )


class ImageListView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_images_list",
        responses={200: ImageListResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        return _page_response(request, images(), serializer=image_data)

    @extend_schema(
        operation_id="platform_images_create",
        request=ImageCreateSerializer,
        responses={201: ImageResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest) -> Response:
        _require_recent_auth(request)
        serializer = ImageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_image(
                actor=request.user,
                context=_context(request),
                **serializer.validated_data,
            )
            return StoredResponse(
                201,
                _body(request, image_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class ImageDetailView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_images_retrieve",
        responses={200: ImageResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest, image_id: str) -> Response:
        item = _get(ImageAsset, image_id)
        return _response(request, image_data(item), etag=etag_for_version(item.row_version))

    @extend_schema(
        operation_id="platform_images_update_scan",
        request=ImageScanSerializer,
        responses={200: ImageResponseSerializer},
        parameters=[IF_MATCH],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def patch(self, request: HttpRequest, image_id: str) -> Response:
        _require_recent_auth(request)
        serializer = ImageScanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        item = update_image_scan(
            image_id=image_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            context=_context(request),
            scan_report_ref=data.get("scan_report_ref", ""),
            **{key: value for key, value in data.items() if key != "scan_report_ref"},
        )
        return _response(request, image_data(item), etag=etag_for_version(item.row_version))


class ImageRenameView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_images_rename",
        request=ImageRenameSerializer,
        responses={200: ImageResponseSerializer},
        parameters=[IDEMPOTENCY_KEY, IF_MATCH],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest, image_id: str) -> Response:
        _require_recent_auth(request)
        serializer = ImageRenameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            item = rename_image(
                image_id=image_id,
                actor=request.user,
                expected_version=expected,
                display_name=data["display_name"],
                reason=data.get("reason", ""),
                context=_context(request),
            )
            return StoredResponse(
                200,
                _body(request, image_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent_response(request, payload=data, operation=operation)


class ImageDecisionView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_images_decide",
        request=ImageDecisionSerializer,
        responses={200: ImageResponseSerializer},
        parameters=[IDEMPOTENCY_KEY, IF_MATCH],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest, image_id: str) -> Response:
        _require_recent_auth(request)
        serializer = ImageDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            item = decide_image(
                image_id=image_id,
                actor=request.user,
                expected_version=expected,
                context=_context(request),
                decision=serializer.validated_data["decision"],
                reason=serializer.validated_data.get("reason", ""),
            )
            return StoredResponse(
                200,
                _body(request, image_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class ImageResolveView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_images_resolve",
        request=ImageResolveSerializer,
        responses={202: ImageResponseSerializer},
        parameters=[IDEMPOTENCY_KEY, IF_MATCH],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest, image_id: str) -> Response:
        _require_recent_auth(request)
        serializer = ImageResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))
        try:
            image = ImageAsset.objects.get(public_id=image_id)
        except ImageAsset.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        trace_id = str(getattr(request, "trace_id", ""))

        def operation() -> StoredResponse:
            current = ImageAsset.objects.get(pk=image.pk)
            if current.row_version != expected:
                raise RowVersionConflict(
                    detail={
                        "expected_row_version": expected,
                        "actual_row_version": current.row_version,
                    }
                )
            if current.approval_status == ImageAsset.ApprovalStatus.RETIRED:
                raise GovernanceStateConflict(
                    detail={"approval_status": current.approval_status}
                )
            if current.digest:
                raise GovernanceStateConflict(detail={"digest": "already_resolved"})
            active_container_adapter()
            transaction.on_commit(
                lambda: resolve_image_digest_task.delay(current.public_id, trace_id),
                robust=True,
            )
            return StoredResponse(
                202,
                _body(request, image_data(current)),
                {"ETag": etag_for_version(current.row_version)},
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class ImageReResolveView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_images_reresolve",
        request=ImageReResolveSerializer,
        responses={202: ImageResponseSerializer},
        parameters=[IDEMPOTENCY_KEY, IF_MATCH],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest, image_id: str) -> Response:
        """对已解析摘要的镜像重新向运行时查询当前摘要(如镜像被重建)。"""
        _require_recent_auth(request)
        serializer = ImageReResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))
        try:
            image = ImageAsset.objects.get(public_id=image_id)
        except ImageAsset.DoesNotExist as exc:
            raise ResourceNotFound() from exc
        trace_id = str(getattr(request, "trace_id", ""))

        def operation() -> StoredResponse:
            current = ImageAsset.objects.get(pk=image.pk)
            if current.row_version != expected:
                raise RowVersionConflict(
                    detail={
                        "expected_row_version": expected,
                        "actual_row_version": current.row_version,
                    }
                )
            if current.approval_status == ImageAsset.ApprovalStatus.RETIRED:
                raise GovernanceStateConflict(
                    detail={"approval_status": current.approval_status}
                )
            if not current.digest:
                raise GovernanceStateConflict(detail={"digest": "first_resolution_required"})
            active_container_adapter()
            transaction.on_commit(
                lambda: reresolve_image_digest_task.delay(current.public_id, trace_id),
                robust=True,
            )
            return StoredResponse(
                202,
                _body(request, image_data(current)),
                {"ETag": etag_for_version(current.row_version)},
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class ResourceProfileListView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_resource_profiles_list",
        responses={200: ResourceProfileListResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        return _page_response(request, resource_profiles(), serializer=resource_profile_data)

    @extend_schema(
        operation_id="platform_resource_profiles_create",
        request=ResourceProfileCreateSerializer,
        responses={201: ResourceProfileResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest) -> Response:
        _require_recent_auth(request)
        serializer = ResourceProfileCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_resource_profile(
                actor=request.user,
                context=_context(request),
                **serializer.validated_data,
            )
            return StoredResponse(
                201,
                _body(request, resource_profile_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class ResourceProfileDetailView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_resource_profiles_retrieve",
        responses={200: ResourceProfileResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest, profile_id: str) -> Response:
        item = _get(ResourceProfile, profile_id)
        return _response(
            request, resource_profile_data(item), etag=etag_for_version(item.row_version)
        )

    @extend_schema(
        operation_id="platform_resource_profiles_update",
        request=ResourceProfileUpdateSerializer,
        responses={200: ResourceProfileResponseSerializer},
        parameters=[IF_MATCH],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def patch(self, request: HttpRequest, profile_id: str) -> Response:
        _require_recent_auth(request)
        serializer = ResourceProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        reason = data.pop("reason")
        item = update_resource_profile(
            profile_id=profile_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            changes=data,
            reason=reason,
            context=_context(request),
        )
        return _response(
            request, resource_profile_data(item), etag=etag_for_version(item.row_version)
        )


class ResourceProfileTransitionView(APIView):
    permission_classes = [IsPlatformPortal]
    target_status = ResourceProfile.Status.ACTIVE

    @extend_schema(
        operation_id="platform_resource_profiles_activate",
        request=GovernanceReasonSerializer,
        responses={200: ResourceProfileResponseSerializer},
        parameters=[IDEMPOTENCY_KEY, IF_MATCH],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest, profile_id: str) -> Response:
        _require_recent_auth(request)
        serializer = GovernanceReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            item = transition_resource_profile(
                profile_id=profile_id,
                actor=request.user,
                expected_version=expected,
                target_status=self.target_status,
                reason=serializer.validated_data["reason"],
                context=_context(request),
            )
            return StoredResponse(
                200,
                _body(request, resource_profile_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class ResourceProfileRetireView(ResourceProfileTransitionView):
    target_status = ResourceProfile.Status.RETIRED

    @extend_schema(
        operation_id="platform_resource_profiles_retire",
        request=GovernanceReasonSerializer,
        responses={200: ResourceProfileResponseSerializer},
        parameters=[IDEMPOTENCY_KEY, IF_MATCH],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest, profile_id: str) -> Response:
        return super().post(request, profile_id)


class QuotaListView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_quotas_list",
        responses={200: QuotaListResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        return _page_response(request, quotas(), serializer=quota_data)

    @extend_schema(
        operation_id="platform_quotas_create",
        request=QuotaWriteSerializer,
        responses={201: QuotaResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest) -> Response:
        _require_recent_auth(request)
        serializer = QuotaWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        reason = data.pop("reason")
        scope_type = data.pop("scope_type", "")
        course_id = data.pop("course_id", None) or None
        user_id = data.pop("user_id", None) or None

        def operation() -> StoredResponse:
            item = create_quota(
                actor=request.user,
                scope_type=scope_type,
                course_id=course_id,
                user_id=user_id,
                values=data,
                reason=reason,
                context=_context(request),
            )
            return StoredResponse(
                201,
                _body(request, quota_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class QuotaDetailView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_quotas_retrieve",
        responses={200: QuotaResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest, quota_id: str) -> Response:
        item = _get(Quota, quota_id)
        return _response(request, quota_data(item), etag=etag_for_version(item.row_version))

    @extend_schema(
        operation_id="platform_quotas_update",
        request=QuotaWriteSerializer,
        responses={200: QuotaResponseSerializer},
        parameters=[IF_MATCH],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def patch(self, request: HttpRequest, quota_id: str) -> Response:
        _require_recent_auth(request)
        serializer = QuotaWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        reason = data.pop("reason")
        for key in ("scope_type", "course_id", "user_id"):
            data.pop(key, None)
        item = update_quota(
            quota_id=quota_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            values=data,
            reason=reason,
            context=_context(request),
        )
        return _response(request, quota_data(item), etag=etag_for_version(item.row_version))


class PolicyListView(APIView):
    permission_classes = [IsPlatformPortal]
    policy_kind = SecurityPolicy.PolicyKind.RUNTIME_SECURITY
    operation_prefix = "security_policies"

    @extend_schema(
        operation_id="platform_security_policies_list",
        responses={200: PolicyListResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        return _page_response(request, policies(self.policy_kind), serializer=policy_data)

    @extend_schema(
        operation_id="platform_security_policies_put",
        request=PolicyPutSerializer,
        responses={200: PolicyResponseSerializer, 201: PolicyResponseSerializer},
        parameters=[IDEMPOTENCY_KEY, IF_MATCH_OPTIONAL],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def put(self, request: HttpRequest) -> Response:
        _require_recent_auth(request)
        serializer = PolicyPutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = (
            parse_if_match(request.headers.get("If-Match"))
            if request.headers.get("If-Match")
            else None
        )

        def operation() -> StoredResponse:
            item = put_policy(
                actor=request.user,
                policy_kind=self.policy_kind,
                expected_version=expected,
                context=_context(request),
                **serializer.validated_data,
            )
            status_code = 201 if item.row_version == 1 else 200
            return StoredResponse(
                status_code,
                _body(request, policy_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent_response(
            request,
            payload=serializer.validated_data,
            operation=operation,
        )


class ScalingPolicyListView(PolicyListView):
    policy_kind = SecurityPolicy.PolicyKind.RESOURCE_SCALING

    @extend_schema(
        operation_id="platform_resource_scaling_policies_list",
        responses={200: PolicyListResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        return super().get(request)

    @extend_schema(
        operation_id="platform_resource_scaling_policies_put",
        request=PolicyPutSerializer,
        responses={200: PolicyResponseSerializer, 201: PolicyResponseSerializer},
        parameters=[IDEMPOTENCY_KEY, IF_MATCH_OPTIONAL],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def put(self, request: HttpRequest) -> Response:
        return super().put(request)


class AllowlistListView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_network_allowlists_list",
        responses={200: AllowlistListResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        return _page_response(request, allowlist_entries(), serializer=allowlist_data)

    @extend_schema(
        operation_id="platform_network_allowlists_create",
        request=AllowlistCreateSerializer,
        responses={201: AllowlistResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest) -> Response:
        _require_recent_auth(request)
        serializer = AllowlistCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_allowlist_entry(
                actor=request.user,
                context=_context(request),
                **serializer.validated_data,
            )
            return StoredResponse(
                201,
                _body(request, allowlist_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class AllowlistDetailView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_network_allowlists_retrieve",
        responses={200: AllowlistResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest, entry_id: str) -> Response:
        item = _get(NetworkAllowlist, entry_id)
        return _response(request, allowlist_data(item), etag=etag_for_version(item.row_version))


class AllowlistRevokeView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_network_allowlists_revoke",
        request=GovernanceReasonSerializer,
        responses={200: AllowlistResponseSerializer},
        parameters=[IDEMPOTENCY_KEY, IF_MATCH],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest, entry_id: str) -> Response:
        _require_recent_auth(request)
        serializer = GovernanceReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            item = revoke_allowlist_entry(
                entry_id=entry_id,
                actor=request.user,
                expected_version=expected,
                reason=serializer.validated_data["reason"],
                context=_context(request),
            )
            return StoredResponse(
                200,
                _body(request, allowlist_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)


class PlatformUsageView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_governance_usage",
        responses={200: UsageResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        return _response(request, platform_usage_summary())


class PlatformAlertListView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_governance_alerts",
        responses={200: AlertListResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        return _page_response(
            request,
            platform_alert_summaries(),
            serializer=lambda item: item,
        )


class TeachingGovernanceSummaryView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_course_governance_retrieve",
        responses={200: ResourceSummaryResponseSerializer},
        tags=["teaching-analytics"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        return _response(
            request,
            teacher_governance_summary(actor=request.user, course_id=course_id),
        )


class StudentResourceSummaryView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="me_course_resource_summary_retrieve",
        responses={200: ResourceSummaryResponseSerializer},
        tags=["tasks"],
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        return _response(
            request,
            student_resource_summary(actor=request.user, course_id=course_id),
        )
