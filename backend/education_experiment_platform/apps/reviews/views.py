from collections.abc import Callable
from typing import Any

from django.http import HttpRequest
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsTeachingPortal
from apps.accounts.security import client_ip
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.courses.services import ActorContext

from .selectors import rubric_for_course, rubrics_for_course, version_for_course
from .serializers import (
    RubricListResponseSerializer,
    RubricResponseSerializer,
    RubricVersionCreateSerializer,
    RubricVersionListResponseSerializer,
    RubricVersionResponseSerializer,
    RubricVersionWriteSerializer,
    RubricWriteSerializer,
    rubric_data,
    version_data,
)
from .services import (
    clone_rubric_version,
    create_rubric,
    create_rubric_version,
    publish_rubric_version,
    update_rubric_version,
)

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


class RubricListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_rubrics_list",
        responses={200: RubricListResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str) -> Response:
        return _response(
            request,
            [
                rubric_data(item)
                for item in rubrics_for_course(actor=request.user, course_id=course_id)
            ],
        )

    @extend_schema(
        operation_id="teaching_rubrics_create",
        request=RubricWriteSerializer,
        responses={201: RubricResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str) -> Response:
        serializer = RubricWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            values = serializer.validated_data
            item = create_rubric(
                course_id=course_id,
                actor=request.user,
                context=_context(request),
                name=values["name"],
                description=values.get("description", ""),
            )
            return StoredResponse(
                201,
                _body(request, rubric_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class RubricVersionListView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_rubric_versions_list",
        responses={200: RubricVersionListResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, rubric_id: str) -> Response:
        rubric = rubric_for_course(actor=request.user, course_id=course_id, rubric_id=rubric_id)
        versions = (
            rubric.versions.select_related("rubric")
            .prefetch_related("criteria")
            .order_by("-version_no")
        )
        return _response(request, [version_data(item) for item in versions])

    @extend_schema(
        operation_id="teaching_rubric_versions_create",
        request=RubricVersionCreateSerializer,
        responses={201: RubricVersionResponseSerializer},
        parameters=[IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, rubric_id: str) -> Response:
        serializer = RubricVersionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            values = serializer.validated_data
            source_version_id = values.get("source_version_id")
            if source_version_id:
                item = clone_rubric_version(
                    course_id=course_id,
                    rubric_id=rubric_id,
                    source_version_id=source_version_id,
                    actor=request.user,
                    context=_context(request),
                )
            else:
                item = create_rubric_version(
                    course_id=course_id,
                    rubric_id=rubric_id,
                    actor=request.user,
                    title=values["title"],
                    description=values.get("description", ""),
                    total_score=values["total_score"],
                    criteria=values["criteria"],
                    context=_context(request),
                )
            item = version_for_course(
                actor=request.user, course_id=course_id, version_id=item.public_id
            )
            return StoredResponse(
                201,
                _body(request, version_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class RubricVersionDetailView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_rubric_versions_retrieve",
        responses={200: RubricVersionResponseSerializer},
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        item = version_for_course(actor=request.user, course_id=course_id, version_id=version_id)
        return _response(request, version_data(item), etag=item.row_version)

    @extend_schema(
        operation_id="teaching_rubric_versions_update",
        request=RubricVersionWriteSerializer,
        responses={200: RubricVersionResponseSerializer},
        parameters=[IF_MATCH],
        extensions={"x-portals": ["TEACHING"]},
    )
    def patch(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        serializer = RubricVersionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        item = update_rubric_version(
            course_id=course_id,
            version_id=version_id,
            actor=request.user,
            expected_version=parse_if_match(request.headers.get("If-Match")),
            title=values["title"],
            description=values.get("description", ""),
            total_score=values["total_score"],
            criteria=values["criteria"],
            context=_context(request),
        )
        item = version_for_course(
            actor=request.user, course_id=course_id, version_id=item.public_id
        )
        return _response(request, version_data(item), etag=item.row_version)


class RubricVersionPublishView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        operation_id="teaching_rubric_versions_publish",
        request=None,
        responses={200: RubricVersionResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        extensions={"x-portals": ["TEACHING"]},
    )
    def post(self, request: HttpRequest, course_id: str, version_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            item = publish_rubric_version(
                course_id=course_id,
                version_id=version_id,
                actor=request.user,
                expected_version=expected,
                context=_context(request),
            )
            item = version_for_course(
                actor=request.user, course_id=course_id, version_id=item.public_id
            )
            return StoredResponse(
                200,
                _body(request, version_data(item)),
                {"ETag": etag_for_version(item.row_version)},
            )

        return _idempotent(request, payload={}, operation=operation)
