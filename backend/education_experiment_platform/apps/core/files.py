import base64
import hashlib
import hmac
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import quote

from django.conf import settings
from django.http import HttpRequest, StreamingHttpResponse
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.errors import PortalAccessDenied
from apps.accounts.models import User
from apps.accounts.security import client_ip
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.core.object_storage import iter_chunks, object_storage

from .downloads import (
    consume_download_grant,
    create_download_grant,
    get_download_target,
    revoke_download_grant,
)
from .file_serializers import (
    DownloadGrantResponseSerializer,
    DownloadGrantRevokeResponseSerializer,
)

IDEMPOTENCY_KEY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)


def _body(request: HttpRequest, data: Any) -> dict[str, object]:
    return {"data": data, "meta": {"trace_id": str(getattr(request, "trace_id", ""))}}


def _derived_token(*, actor: User, portal: str, asset_id: str, key: str) -> str:
    message = f"{portal}:{actor.public_id}:{asset_id}:{key}".encode()
    digest = hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _idempotent(
    request: HttpRequest, *, payload: Any, operation: Callable[[], StoredResponse]
) -> StoredResponse:
    user: User = request.user  # type: ignore[assignment]
    return execute_idempotent(
        principal=PrincipalScope(user.public_id, "SESSION", str(request.portal)),
        method=request.method,
        endpoint=request.path,
        key=getattr(request, "idempotency_key", None),
        payload=payload,
        operation=operation,
    )


class IsFilePortal(BasePermission):
    def has_permission(self, request: HttpRequest, view: object) -> bool:
        if getattr(request, "portal", "") not in {"USER", "TEACHING"}:
            raise PortalAccessDenied(detail={"allowed_portals": ["USER", "TEACHING"]})
        return bool(getattr(request, "user", None))


class FileDownloadGrantCreateView(APIView):
    permission_classes = [IsFilePortal]

    @extend_schema(
        operation_id="files_download_grants_create",
        request=None,
        responses={201: DownloadGrantResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
        tags=["reports"],
        extensions={"x-portals": ["USER", "TEACHING"]},
    )
    def post(self, request: HttpRequest, asset_id: str) -> Response:
        token = _derived_token(
            actor=request.user,
            portal=str(request.portal),
            asset_id=asset_id,
            key=str(getattr(request, "idempotency_key", "")),
        )

        def operation() -> StoredResponse:
            grant, _ = create_download_grant(
                asset_id=asset_id,
                actor=request.user,
                portal=str(request.portal),
                trace_id=str(getattr(request, "trace_id", "")),
                token=token,
                client_ip=client_ip(request),
                user_agent=request.headers.get("User-Agent", ""),
            )
            return StoredResponse(
                201,
                _body(
                    request,
                    {
                        "grant_id": grant.public_id,
                        "download_path": "__DOWNLOAD_PATH__",
                        "expires_at": grant.expires_at,
                        "max_downloads": grant.max_downloads,
                    },
                ),
                {"ETag": etag_for_version(grant.row_version)},
            )

        result = _idempotent(request, payload={"asset_id": asset_id}, operation=operation)
        result.body["data"]["download_path"] = f"/files/{token}"
        response = Response(result.body, status=result.status_code, headers=dict(result.headers))
        response["Cache-Control"] = "private, no-store"
        if result.replayed:
            response["X-Idempotent-Replayed"] = "true"
        return response


class FileDownloadGrantRevokeView(APIView):
    permission_classes = [IsFilePortal]

    @extend_schema(
        operation_id="files_download_grants_revoke",
        request=None,
        responses={200: DownloadGrantRevokeResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        tags=["reports"],
        extensions={"x-portals": ["USER", "TEACHING"]},
    )
    def post(self, request: HttpRequest, grant_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            grant = revoke_download_grant(
                grant_id=grant_id,
                actor=request.user,
                portal=str(request.portal),
                expected_version=expected,
                trace_id=str(getattr(request, "trace_id", "")),
                client_ip=client_ip(request),
                user_agent=request.headers.get("User-Agent", ""),
            )
            return StoredResponse(
                200,
                _body(
                    request,
                    {
                        "public_id": grant.public_id,
                        "revoked_at": grant.revoked_at,
                        "row_version": grant.row_version,
                    },
                ),
                {"ETag": etag_for_version(grant.row_version)},
            )

        result = _idempotent(request, payload={"grant_id": grant_id}, operation=operation)
        response = Response(result.body, status=result.status_code, headers=dict(result.headers))
        response["Cache-Control"] = "private, no-store"
        if result.replayed:
            response["X-Idempotent-Replayed"] = "true"
        return response


class FileDownloadView(APIView):
    permission_classes = [IsFilePortal]

    @extend_schema(
        operation_id="files_download",
        responses={200: OpenApiResponse(description="authorized file content")},
        parameters=[],
        tags=["reports"],
        extensions={"x-portals": ["USER", "TEACHING"]},
    )
    def get(self, request: HttpRequest, token: str) -> StreamingHttpResponse:
        grant, asset = get_download_target(
            token=token, actor=request.user, portal=str(request.portal)
        )
        consume_download_grant(
            grant_id=grant.pk,
            actor=request.user,
            portal=str(request.portal),
            trace_id=str(getattr(request, "trace_id", "")),
            client_ip=client_ip(request),
            user_agent=request.headers.get("User-Agent", ""),
        )
        stored = object_storage().open_object(
            bucket=asset.bucket,
            object_key=asset.object_key,
            version_id=asset.object_version,
        )

        def stream() -> Iterator[bytes]:
            try:
                yield from iter_chunks(stored.body)
            finally:
                stored.body.close()

        response = StreamingHttpResponse(
            stream(), content_type=asset.media_type or "application/octet-stream"
        )
        response["Content-Length"] = str(stored.content_length)
        response["Content-Disposition"] = (
            f"attachment; filename*=UTF-8''{quote(asset.original_name or 'download')}"
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
