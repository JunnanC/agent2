from collections.abc import Callable
from typing import Any

from django.db import transaction
from django.http import HttpRequest
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsPlatformPortal, IsUserPortal
from apps.accounts.security import client_ip
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.courses.services import ActorContext

from .serializers import (
    GenericReportResponseSerializer,
    ReportAttachmentCreateSerializer,
    ReportAttachmentResponseSerializer,
    ReportAttachmentUploadResponseSerializer,
    attachment_data,
)
from .services import (
    attachment_for_user,
    create_attachment_upload,
    request_attachment_scan,
    scan_anomaly_summary,
)
from .tasks import scan_report_asset

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


class UserReportAttachmentCreateView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="tasks_report_attachments_create",
        request=ReportAttachmentCreateSerializer,
        responses={201: ReportAttachmentUploadResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
        tags=["reports"],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, task_id: str) -> Response:
        serializer = ReportAttachmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            asset, upload = create_attachment_upload(
                task_id=task_id,
                actor=request.user,
                file_name=serializer.validated_data["file_name"],
                media_type=serializer.validated_data["media_type"],
                size_bytes=serializer.validated_data["size_bytes"],
                digest_sha256=serializer.validated_data["digest_sha256"],
                context=_context(request),
            )
            return StoredResponse(
                201,
                _body(request, {"asset": attachment_data(asset, attached=False), "upload": upload}),
                {"ETag": etag_for_version(asset.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class UserReportAttachmentCompleteView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="tasks_report_attachments_complete",
        request=None,
        responses={202: ReportAttachmentResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        tags=["reports"],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, task_id: str, asset_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            asset = request_attachment_scan(
                task_id=task_id,
                asset_id=asset_id,
                actor=request.user,
                expected_version=expected,
                context=_context(request),
            )
            transaction.on_commit(
                lambda: scan_report_asset.delay(
                    asset.public_id, str(getattr(request, "trace_id", ""))
                ),
                robust=True,
            )
            return StoredResponse(
                202,
                _body(request, attachment_data(asset, attached=False)),
                {"ETag": etag_for_version(asset.row_version)},
            )

        return _idempotent(request, payload={"asset_id": asset_id}, operation=operation)


class UserReportAttachmentStatusView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="tasks_report_attachments_status",
        responses={200: ReportAttachmentResponseSerializer},
        tags=["reports"],
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest, task_id: str, asset_id: str) -> Response:
        asset = attachment_for_user(task_id=task_id, asset_id=asset_id, actor=request.user)
        attached = asset.report_links.exists()
        return _response(request, attachment_data(asset, attached=attached), etag=asset.row_version)


class PlatformReportScanAnomaliesView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        operation_id="platform_report_scan_anomalies",
        responses={200: GenericReportResponseSerializer},
        tags=["reports"],
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        return _response(request, scan_anomaly_summary())
