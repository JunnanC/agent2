import hashlib
import hmac
import time
from collections.abc import Callable, Iterable
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import SESSION_AUTH_TIME
from apps.accounts.models import User
from apps.accounts.permissions import IsPlatformPortal, IsTeachingPortal, IsUserPortal
from apps.accounts.security import client_ip
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.core.pagination import PageSpec
from apps.courses.services import ActorContext
from apps.governance.errors import RecentAuthenticationRequired
from apps.provisioning.services import enabled_runtime_inventory

from .selectors import (
    archive_for_course,
    archive_for_user,
    archives_for_course,
    compensation_rows,
    instance_rows,
    teaching_archive_course,
)
from .serializers import (
    ArchiveDestroyReasonSerializer,
    ArchiveExportResponseSerializer,
    ArchiveListResponseSerializer,
    ArchiveResponseSerializer,
    CompensationListResponseSerializer,
    CompensationResponseSerializer,
    CompensationRetrySerializer,
    InstanceListResponseSerializer,
    InstanceResponseSerializer,
    archive_data,
    compensation_data,
    instance_data,
)
from .services import (
    create_archive_export,
    request_instance_destroy_as_admin,
    request_orphan_destroy_as_admin,
    retry_compensation_as_admin,
)


def _metadata_int(value: object) -> int:
    if not isinstance(value, (str, bytes, bytearray, int, float)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)
IDEMPOTENCY_KEY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)


def _context(request: HttpRequest) -> ActorContext:
    user: User = request.user  # type: ignore[assignment]
    return ActorContext(
        actor_ref=user.public_id,
        portal=str(getattr(request, "portal", "")),
        trace_id=str(getattr(request, "trace_id", "")),
        client_ip=client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
    )


def _body(request: HttpRequest, data: Any) -> dict[str, Any]:
    return {"data": data, "meta": {"trace_id": str(getattr(request, "trace_id", ""))}}


def _response(
    request: HttpRequest, data: Any, *, status: int = 200, etag: str | None = None
) -> Response:
    response = Response(_body(request, data), status=status)
    response["Cache-Control"] = "private, no-store"
    if etag:
        response["ETag"] = etag
    return response


def _page_response(
    request: HttpRequest,
    values: Iterable[Any],
    *,
    serializer: Callable[[Any], dict[str, Any]],
) -> Response:
    spec = PageSpec.parse(request.GET.get("page", 1), request.GET.get("page_size", 20))
    all_values = list(values)
    page = all_values[spec.offset : spec.offset + spec.page_size]
    response = Response({
        "data": [serializer(item) for item in page],
        "meta": {
            "page": spec.page,
            "page_size": spec.page_size,
            "total": len(all_values),
            "trace_id": str(getattr(request, "trace_id", "")),
        },
    })
    response["Cache-Control"] = "private, no-store"
    return response


def _idempotent_response(
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


def _require_recent_auth(request: HttpRequest) -> None:
    authenticated_at = int(request.session.get(SESSION_AUTH_TIME, 0))
    if (
        authenticated_at <= 0
        or int(time.time()) - authenticated_at > settings.PLATFORM_RECENT_AUTH_SECONDS
    ):
        raise RecentAuthenticationRequired()


def _export_token(*, actor: User, archive_id: str, key: str) -> str:
    value = f"archive:{actor.public_id}:{archive_id}:{key}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), value, hashlib.sha256).hexdigest()


class UserArchiveView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="tasks_archive_retrieve",
        responses={200: ArchiveResponseSerializer},
        tags=["tasks"],
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest, task_id: str) -> Response:
        job = archive_for_user(actor=request.user, task_id=task_id)
        return _response(request, archive_data(job), etag=etag_for_version(job.row_version))


class TeachingArchiveListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_archives_list",
        responses={200: ArchiveListResponseSerializer},
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        return _page_response(
            request,
            archives_for_course(actor=request.user, course_id=course_id),
            serializer=archive_data,
        )


class TeachingArchiveDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_archives_retrieve",
        responses={200: ArchiveResponseSerializer},
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, archive_id: str) -> Response:
        job = archive_for_course(actor=request.user, course_id=course_id, archive_id=archive_id)
        return _response(request, archive_data(job), etag=etag_for_version(job.row_version))


class TeachingArchiveExportView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_archives_exports_create",
        request=None,
        responses={201: ArchiveExportResponseSerializer},
        parameters=[IDEMPOTENCY_KEY, IF_MATCH],
        tags=["teaching-reviews"],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, archive_id: str) -> Response:
        teaching_archive_course(actor=request.user, course_id=course_id, export=True)
        expected = parse_if_match(request.headers.get("If-Match"))
        token = _export_token(
            actor=request.user,
            archive_id=archive_id,
            key=str(getattr(request, "idempotency_key", "")),
        )

        def operation() -> StoredResponse:
            grant, _ = create_archive_export(
                course_id=course_id,
                archive_id=archive_id,
                actor=request.user,
                expected_version=expected,
                token=token,
                context=_context(request),
            )
            return StoredResponse(
                201,
                _body(
                    request,
                    {
                        "grant_id": grant.public_id,
                        "download_path": f"/files/{token}",
                        "expires_at": grant.expires_at,
                        "max_downloads": grant.max_downloads,
                        "row_version": grant.row_version,
                    },
                ),
                {"ETag": etag_for_version(grant.row_version)},
            )

        return _idempotent_response(
            request,
            payload={"course_id": course_id, "archive_id": archive_id},
            operation=operation,
        )


class PlatformInstanceListView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_instances_list",
        responses={200: InstanceListResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        inventory_items = enabled_runtime_inventory(
            include_unavailable=True,
            trace_id=str(getattr(request, "trace_id", "")),
        )
        unavailable_adapters = {
            str(item.metadata.get("adapter_id", ""))
            for item in inventory_items
            if item.metadata.get("inventory_unavailable")
        }
        inventory = {
            (str(item.metadata.get("adapter_id", "")), item.external_id): item
            for item in inventory_items
            if item.external_id
        }
        rows = list(instance_rows())
        data = [
            instance_data(
                item,
                external_status=(
                    inventory[(item.runtime_adapter.public_id, item.external_id)].status
                    if (item.runtime_adapter.public_id, item.external_id) in inventory
                    else "UNAVAILABLE"
                    if item.runtime_adapter.public_id in unavailable_adapters
                    else "ABSENT"
                ),
                external_metadata=(
                    dict(inventory[(item.runtime_adapter.public_id, item.external_id)].metadata)
                    if (item.runtime_adapter.public_id, item.external_id) in inventory
                    else {}
                ),
            )
            for item in rows
        ]
        known = {
            (item.runtime_adapter.public_id, item.external_id)
            for item in rows
            if item.external_id
        }
        data.extend(
            {
                "public_id": f"external:{adapter_id}:{external_id}",
                "task_id": "",
                "course_id": "",
                "student_id": "",
                "status": "ORPHANED",
                "external_id": external_id,
                "external_status": item.status,
                "runtime_driver": str(item.metadata.get("driver", "")),
                "service_name": str(item.metadata.get("service_name", "")),
                "runtime_task_count": _metadata_int(item.metadata.get("task_count", 0)),
                "runtime_health": str(item.metadata.get("health", item.status)),
                "orphan": True,
                "resource_leak": True,
                "row_version": 1,
                "trace_id": "",
            }
            for (adapter_id, external_id), item in inventory.items()
            if (adapter_id, external_id) not in known
        )
        return _page_response(request, data, serializer=lambda item: item)


class PlatformInstanceDestroyView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_instances_destroy",
        request=ArchiveDestroyReasonSerializer,
        responses={202: InstanceResponseSerializer},
        parameters=[IDEMPOTENCY_KEY, IF_MATCH],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest, instance_id: str) -> Response:
        _require_recent_auth(request)
        serializer = ArchiveDestroyReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            if instance_id.startswith("external:"):
                request_orphan_destroy_as_admin(
                    orphan_ref=instance_id,
                    actor=request.user,
                    expected_version=expected,
                    reason=serializer.validated_data["reason"],
                    context=_context(request),
                )
                return StoredResponse(
                    202,
                    _body(
                        request,
                        {
                            "public_id": instance_id,
                            "task_id": "",
                            "course_id": "",
                            "student_id": "",
                            "status": "DESTROY_PENDING",
                            "external_id": instance_id.rsplit(":", 1)[-1],
                            "external_status": "DESTROY_PENDING",
                            "runtime_driver": "",
                            "service_name": "",
                            "runtime_task_count": 0,
                            "runtime_health": "UNKNOWN",
                            "orphan": True,
                            "resource_leak": True,
                            "row_version": 1,
                            "trace_id": str(getattr(request, "trace_id", "")),
                        },
                    ),
                    {"ETag": etag_for_version(1)},
                )
            instance = request_instance_destroy_as_admin(
                instance_id=instance_id,
                actor=request.user,
                expected_version=expected,
                reason=serializer.validated_data["reason"],
                context=_context(request),
            )
            return StoredResponse(
                202,
                _body(request, instance_data(instance, external_status="DESTROY_PENDING")),
                {"ETag": etag_for_version(instance.row_version)},
            )

        return _idempotent_response(
            request,
            payload={"instance_id": instance_id, **serializer.validated_data},
            operation=operation,
        )


class PlatformCompensationView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_compensations_list",
        responses={200: CompensationListResponseSerializer},
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        return _page_response(
            request,
            compensation_rows(status=request.GET.get("status", "")),
            serializer=compensation_data,
        )

    @extend_schema(
        operation_id="platform_compensations_retry",
        request=CompensationRetrySerializer,
        responses={202: CompensationResponseSerializer},
        parameters=[IDEMPOTENCY_KEY, IF_MATCH],
        tags=["platform-governance"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def post(self, request: HttpRequest) -> Response:
        _require_recent_auth(request)
        serializer = CompensationRetrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            item = retry_compensation_as_admin(
                compensation_id=serializer.validated_data["compensation_id"],
                actor=request.user,
                expected_version=expected,
                reason=serializer.validated_data["reason"],
                context=_context(request),
            )
            return StoredResponse(
                202,
                _body(request, compensation_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent_response(request, payload=serializer.validated_data, operation=operation)
