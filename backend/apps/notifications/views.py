from typing import Any

from django.http import HttpRequest
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAuthenticatedAccount
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.courses.services import ActorContext

from .models import Notification
from .selectors import preference_for, visible_notifications
from .serializers import (
    P13NotificationResponseSerializer,
    PreferenceSerializer,
    notification_data,
    preference_data,
)
from .services import mark_read, update_preference

IDEMPOTENCY_KEY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)


class P13APIView(APIView):
    serializer_class = P13NotificationResponseSerializer


def _body(request: HttpRequest, data: Any) -> dict[str, Any]:
    return {"data": data, "meta": {"trace_id": str(getattr(request, "trace_id", ""))}}


def _ctx(request: HttpRequest) -> ActorContext:
    return ActorContext(
        actor_ref=request.user.public_id, portal=str(request.portal), trace_id=str(request.trace_id)
    )


class NotificationListView(P13APIView):
    permission_classes = [IsAuthenticatedAccount]

    @extend_schema(
        tags=["notifications"], extensions={"x-portals": ["USER", "TEACHING", "PLATFORM"]}
    )
    def get(self, request: HttpRequest) -> Response:
        return Response(
            _body(
                request,
                [
                    notification_data(item)
                    for item in visible_notifications(
                        actor=request.user, portal=str(request.portal)
                    )
                ],
            )
        )


class NotificationDetailView(P13APIView):
    permission_classes = [IsAuthenticatedAccount]

    @extend_schema(
        parameters=[IDEMPOTENCY_KEY, IF_MATCH],
        tags=["notifications"],
        extensions={"x-portals": ["USER", "TEACHING", "PLATFORM"]},
    )
    def post(self, request: HttpRequest, notification_id: str) -> Response:
        item = Notification.objects.filter(
            public_id=notification_id, account=request.user, portal=str(request.portal)
        ).first()
        if item is None:
            from apps.core.errors import ResourceNotFound

            raise ResourceNotFound()

        def operation() -> StoredResponse:
            updated = mark_read(
                item=item,
                expected_version=parse_if_match(request.headers.get("If-Match")),
                context=_ctx(request),
            )
            return StoredResponse(
                200,
                _body(request, notification_data(updated)),
                {"ETag": etag_for_version(updated.row_version)},
            )

        result = execute_idempotent(
            principal=PrincipalScope(request.user.public_id, "SESSION", str(request.portal)),
            method=request.method,
            endpoint=request.path,
            key=getattr(request, "idempotency_key", request.headers.get("Idempotency-Key")),
            payload={"notification_id": notification_id},
            operation=operation,
        )
        response = Response(result.body, status=result.status_code, headers=dict(result.headers))
        if result.replayed:
            response["X-Idempotent-Replayed"] = "true"
        return response


class NotificationPreferenceView(P13APIView):
    permission_classes = [IsAuthenticatedAccount]

    @extend_schema(
        tags=["notifications"], extensions={"x-portals": ["USER", "TEACHING", "PLATFORM"]}
    )
    def get(self, request: HttpRequest) -> Response:
        item = preference_for(actor=request.user, portal=str(request.portal))
        data = (
            preference_data(item)
            if item
            else {
                "portal": str(request.portal),
                "channels": {"in_app": True},
                "muted_kinds": [],
                "digest_enabled": False,
                "row_version": None,
            }
        )
        return Response(_body(request, data))

    @extend_schema(
        request=PreferenceSerializer,
        parameters=[IDEMPOTENCY_KEY, IF_MATCH],
        tags=["notifications"],
        extensions={"x-portals": ["USER", "TEACHING", "PLATFORM"]},
    )
    def patch(self, request: HttpRequest) -> Response:
        serializer = PreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = update_preference(
            actor=request.user,
            portal=str(request.portal),
            data=serializer.validated_data,
            expected_version=(
                parse_if_match(request.headers.get("If-Match"))
                if request.headers.get("If-Match")
                else None
            ),
        )
        return Response(
            _body(request, preference_data(item)),
            headers={"ETag": etag_for_version(item.row_version)},
        )
