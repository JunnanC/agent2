from typing import Any

from django.http import HttpRequest
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsUserPortal
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.courses.services import ActorContext

from .selectors import job_for_user
from .serializers import (
    ProvisioningActionResponseSerializer,
    ProvisioningJobSerializer,
    action_data,
    job_data,
)
from .services import cancel_queued_provisioning, retry_provisioning, start_provisioning

IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)
IDEMPOTENCY_KEY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)


def _context(request: HttpRequest) -> ActorContext:
    user = request.user
    return ActorContext(
        actor_ref=user.public_id,
        portal=str(getattr(request, "portal", "")),
        trace_id=str(getattr(request, "trace_id", "")),
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


def _idempotent(request: HttpRequest, *, payload: Any, operation: Any) -> Response:
    result = execute_idempotent(
        principal=PrincipalScope(request.user.public_id, "SESSION", str(request.portal)),
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


class UserTaskStartView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="tasks_start",
        request=None,
        responses={202: ProvisioningActionResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        tags=["tasks"],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, task_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            task, job = start_provisioning(
                task_id=task_id,
                actor=request.user,
                expected_version=expected,
                context=_context(request),
            )
            body = _body(request, action_data(job))
            return StoredResponse(
                202,
                body,
                {
                    "ETag": etag_for_version(task.row_version),
                    "Location": f"/api/v2/tasks/{task.public_id}/provisioning-job",
                },
            )

        return _idempotent(request, payload={}, operation=operation)


class UserTaskRetryView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="tasks_retry",
        request=None,
        responses={202: ProvisioningActionResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        tags=["tasks"],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, task_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            task, job = retry_provisioning(
                task_id=task_id,
                actor=request.user,
                expected_version=expected,
                context=_context(request),
            )
            return StoredResponse(
                202,
                _body(request, action_data(job)),
                {
                    "ETag": etag_for_version(task.row_version),
                    "Location": f"/api/v2/tasks/{task.public_id}/provisioning-job",
                },
            )

        return _idempotent(request, payload={}, operation=operation)


class UserTaskProvisioningCancelView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="tasks_provisioning_cancel",
        request=None,
        responses={202: ProvisioningActionResponseSerializer},
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        tags=["tasks"],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, task_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            task, job = cancel_queued_provisioning(
                task_id=task_id,
                actor=request.user,
                expected_version=expected,
                context=_context(request),
            )
            return StoredResponse(
                202,
                _body(request, action_data(job)),
                {"ETag": etag_for_version(task.row_version)},
            )

        return _idempotent(request, payload={}, operation=operation)


class UserTaskProvisioningJobView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="tasks_provisioning_job_retrieve",
        responses=ProvisioningJobSerializer,
        tags=["tasks"],
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest, task_id: str) -> Response:
        job = job_for_user(actor=request.user, task_id=task_id)
        return _response(request, job_data(job), etag=job.row_version)
