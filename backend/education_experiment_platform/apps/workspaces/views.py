from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import IsPlatformPortal, IsTeachingPortal, IsUserPortal
from apps.accounts.security import client_ip
from apps.core.concurrency import etag_for_version, parse_if_match
from apps.core.idempotency import PrincipalScope, StoredResponse, execute_idempotent
from apps.core.pagination import decode_cursor, encode_cursor
from apps.courses.services import ActorContext
from apps.experiments.serializers import task_data
from apps.experiments.services import allowed_actions

from .models import WorkspaceExecutionRun, WorkspaceSession, WorkspaceStorageJob
from .permissions import require_workspace_session
from .selectors import (
    active_session_for_user,
    checkpoints_for_user,
    execution_run_for_user,
    execution_runs_for_user,
    replay_for_teaching,
    replay_for_user,
    sessions_for_platform,
    snapshots_for_teaching,
    storage_job_for_user,
    task_for_teaching,
    task_for_user,
)
from .serializers import (
    CheckpointWriteSerializer,
    ExecutionRunCreateSerializer,
    OperationEventSerializer,
    WorkbenchSerializer,
    WorkspaceCheckpointListSerializer,
    WorkspaceCheckpointSerializer,
    WorkspaceEnterSerializer,
    WorkspaceExecutionRunListSerializer,
    WorkspaceExecutionRunSerializer,
    WorkspaceSessionSerializer,
    WorkspaceSnapshotSerializer,
    WorkspaceStorageJobSerializer,
    WorkspaceStorageJobWriteSerializer,
    checkpoint_data,
    execution_run_data,
    operation_data,
    session_data,
    snapshot_data,
    storage_job_data,
)
from .services import (
    create_checkpoint,
    create_storage_job,
    enter_task,
    issue_session,
    renew_session,
    request_execution_run,
    restore_checkpoint,
    revoke_session,
    save_snapshot,
)
from .workbench import workbench_data

IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)
IDEMPOTENCY_KEY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)
WORKSPACE_TOKEN = OpenApiParameter("X-Workspace-Token", str, OpenApiParameter.HEADER, required=True)


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


def _context(request: HttpRequest) -> ActorContext:
    user: User = request.user  # type: ignore[assignment]
    return ActorContext(
        actor_ref=user.public_id,
        portal=str(getattr(request, "portal", "")),
        trace_id=str(getattr(request, "trace_id", "")),
        client_ip=client_ip(request),
        user_agent=request.headers.get("User-Agent", ""),
    )


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


def _workspace_token(request: HttpRequest) -> str:
    return str(request.headers.get("X-Workspace-Token", ""))


def _set_workspace_cookie(
    response: Response, *, session_id: str, token: str, max_age: int
) -> Response:
    response.set_cookie(
        key=str(getattr(settings, "WORKSPACE_COOKIE_NAME", "workspace_ticket")),
        value=token,
        max_age=max(1, max_age),
        path=f"/workspace/{session_id}/",
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=True,
        samesite="Strict",
    )
    return response


def _delete_workspace_cookie(response: Response, *, session_id: str) -> Response:
    response.delete_cookie(
        key=str(getattr(settings, "WORKSPACE_COOKIE_NAME", "workspace_ticket")),
        path=f"/workspace/{session_id}/",
        samesite="Strict",
    )
    return response


class UserTaskWorkbenchView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="tasks_workbench_retrieve",
        responses={200: WorkbenchSerializer},
        tags=["workspaces"],
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest, task_id: str) -> Response:
        return _response(request, workbench_data(actor=request.user, task_id=task_id))


class UserWorkspaceStorageJobCreateView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="tasks_workspace_storage_jobs_create",
        parameters=[IF_MATCH, IDEMPOTENCY_KEY, WORKSPACE_TOKEN],
        request=WorkspaceStorageJobWriteSerializer,
        responses={202: WorkspaceStorageJobSerializer},
        tags=["workspaces"],
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, task_id: str) -> Response:
        serializer = WorkspaceStorageJobWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        expected = parse_if_match(request.headers.get("If-Match"))
        values = dict(serializer.validated_data)
        key = str(getattr(request, "idempotency_key", ""))

        def operation() -> StoredResponse:
            session, job = create_storage_job(
                task_id=task_id,
                actor=request.user,
                token=_workspace_token(request),
                expected_version=expected,
                kind=str(values["kind"]),
                client_seq=values.get("client_seq"),
                base_version=values.get("base_version"),
                snapshot_id=values.get("snapshot_id"),
                idempotency_key=key,
                request_payload=values,
                context=_context(request),
            )
            return StoredResponse(
                202,
                _body(request, storage_job_data(job)),
                {
                    "ETag": etag_for_version(session.row_version),
                    "Location": f"/api/v2/workspace-storage-jobs/{job.public_id}",
                },
            )

        return _idempotent(request, payload=values, operation=operation)


class UserWorkspaceStorageJobDetailView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        operation_id="workspace_storage_jobs_retrieve",
        responses=WorkspaceStorageJobSerializer,
        tags=["workspaces"],
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest, job_id: str) -> Response:
        job = storage_job_for_user(actor=request.user, job_id=job_id)
        return _response(request, storage_job_data(job), etag=job.row_version)


class UserTaskEnterView(APIView):
    permission_classes = [IsUserPortal]
    serializer_class = WorkspaceSessionSerializer

    @extend_schema(
        parameters=[IF_MATCH, IDEMPOTENCY_KEY],
        tags=["workspaces"],
        responses={200: WorkspaceEnterSerializer},
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, task_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            task, session, token = enter_task(
                task_id=task_id,
                actor=request.user,
                expected_version=expected,
                context=_context(request),
            )
            task = task_for_user(actor=request.user, task_id=task.public_id)
            payload = _body(
                request,
                {
                    "task": task_data(task, actions=allowed_actions(task, actor=request.user)),
                    "session": session_data(session, token=token),
                },
            )
            return StoredResponse(200, payload, {"ETag": etag_for_version(task.row_version)})

        response = _idempotent(request, payload={}, operation=operation)
        session_payload = response.data["data"]["session"]
        return _set_workspace_cookie(
            response,
            session_id=str(session_payload["public_id"]),
            token=str(session_payload["workspace_token"]),
            max_age=int(getattr(settings, "WORKSPACE_SESSION_TTL_SECONDS", 900)),
        )


class UserWorkspaceSessionCreateView(APIView):
    permission_classes = [IsUserPortal]
    serializer_class = WorkspaceSessionSerializer

    @extend_schema(
        parameters=[IDEMPOTENCY_KEY],
        tags=["workspaces"],
        responses={201: WorkspaceSessionSerializer},
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, task_id: str) -> Response:
        def operation() -> StoredResponse:
            task = task_for_user(actor=request.user, task_id=task_id)
            if task.status not in {"IN_PROGRESS", "REPORT_DRAFT"}:
                from apps.core.errors import StateConflict

                raise StateConflict(detail={"status": task.status})
            task, session, token = issue_session(
                task=task, actor=request.user, context=_context(request)
            )
            return StoredResponse(
                201,
                _body(request, session_data(session, token=token)),
                {"ETag": etag_for_version(session.row_version)},
            )

        response = _idempotent(request, payload={}, operation=operation)
        session_payload = response.data["data"]
        return _set_workspace_cookie(
            response,
            session_id=str(session_payload["public_id"]),
            token=str(session_payload["workspace_token"]),
            max_age=int(getattr(settings, "WORKSPACE_SESSION_TTL_SECONDS", 900)),
        )


class WorkspaceSessionRenewView(APIView):
    permission_classes = [IsUserPortal]
    serializer_class = WorkspaceSessionSerializer

    @extend_schema(
        parameters=[WORKSPACE_TOKEN, IDEMPOTENCY_KEY],
        tags=["workspaces"],
        responses={200: WorkspaceSessionSerializer},
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, session_id: str) -> Response:
        session = (
            WorkspaceSession.objects.select_related("student")
            .filter(public_id=session_id, student=request.user)
            .first()
        )
        if session is None:
            from apps.core.errors import ResourceNotFound

            raise ResourceNotFound()

        def operation() -> StoredResponse:
            changed, token = renew_session(
                session=session,
                token=_workspace_token(request),
                actor=request.user,
                context=_context(request),
            )
            return StoredResponse(
                200,
                _body(request, session_data(changed, token=token)),
                {"ETag": etag_for_version(changed.row_version)},
            )

        response = _idempotent(request, payload={}, operation=operation)
        session_payload = response.data["data"]
        return _set_workspace_cookie(
            response,
            session_id=str(session_payload["public_id"]),
            token=str(session_payload["workspace_token"]),
            max_age=int(getattr(settings, "WORKSPACE_SESSION_TTL_SECONDS", 900)),
        )


class WorkspaceSessionRevokeView(APIView):
    permission_classes = [IsUserPortal]
    serializer_class = WorkspaceSessionSerializer

    @extend_schema(
        parameters=[IF_MATCH, IDEMPOTENCY_KEY, WORKSPACE_TOKEN],
        tags=["workspaces"],
        responses={200: WorkspaceSessionSerializer},
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, session_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))
        session = (
            WorkspaceSession.objects.select_related("student")
            .filter(public_id=session_id, student=request.user)
            .first()
        )
        if session is None:
            from apps.core.errors import ResourceNotFound

            raise ResourceNotFound()

        def operation() -> StoredResponse:
            changed = revoke_session(
                session=session,
                token=_workspace_token(request),
                actor=request.user,
                expected_version=expected,
                context=_context(request),
            )
            return StoredResponse(
                200,
                _body(request, session_data(changed)),
                {"ETag": etag_for_version(changed.row_version)},
            )

        return _delete_workspace_cookie(
            _idempotent(request, payload={}, operation=operation), session_id=session_id
        )


class UserWorkspaceSnapshotView(APIView):
    permission_classes = [IsUserPortal]
    parser_classes = [MultiPartParser]
    serializer_class = WorkspaceSnapshotSerializer

    @extend_schema(
        operation_id="tasks_workspace_snapshot_save",
        parameters=[WORKSPACE_TOKEN, IDEMPOTENCY_KEY],
        tags=["workspaces"],
        responses={200: WorkspaceSnapshotSerializer, 202: WorkspaceStorageJobSerializer},
        extensions={"x-portals": ["USER"]},
    )
    def put(self, request: HttpRequest, task_id: str) -> Response:
        client_seq = int(request.data.get("client_seq", 0))
        base_version = int(request.data.get("base_version", 0))
        upload = (
            request.FILES.get("snapshot")
            or request.FILES.get("object")
            or request.FILES.get("file")
        )
        if client_seq <= 0 or upload is None:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"client_seq": "positive integer and snapshot file are required"})
        session, snapshot, result = save_snapshot(
            task_id=task_id,
            actor=request.user,
            token=_workspace_token(request),
            client_seq=client_seq,
            base_version=base_version,
            upload=upload,
            context=_context(request),
        )
        return _response(
            request,
            {"snapshot": snapshot_data(snapshot), "confirmed_seq": client_seq, "result": result},
            etag=session.row_version,
        )


class UserCheckpointListCreateView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        tags=["workspaces"],
        responses=WorkspaceCheckpointListSerializer,
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest, task_id: str) -> Response:
        task_for_user(actor=request.user, task_id=task_id)
        session = (
            WorkspaceSession.objects.filter(
                task__public_id=task_id,
                student=request.user,
                status=WorkspaceSession.Status.ACTIVE,
            )
            .order_by("-created_at")
            .first()
        )
        rows = [
            checkpoint_data(item)
            for item in checkpoints_for_user(actor=request.user, task_id=task_id)
        ]
        return _response(
            request,
            {
                "items": rows,
                "current_version": session.current_version if session else 0,
                "row_version": session.row_version if session else 0,
            },
        )

    @extend_schema(
        parameters=[IDEMPOTENCY_KEY, WORKSPACE_TOKEN],
        request=CheckpointWriteSerializer,
        tags=["workspaces"],
        responses=WorkspaceCheckpointSerializer,
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, task_id: str) -> Response:
        serializer = CheckpointWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            item = create_checkpoint(
                task_id=task_id,
                actor=request.user,
                token=_workspace_token(request),
                name=str(
                    serializer.validated_data.get("name")
                    or serializer.validated_data.get("label")
                    or ""
                ),
                context=_context(request),
            )
            item = (
                WorkspaceSession.objects.get(pk=item.session_id)
                .checkpoints.select_related("snapshot")
                .get(pk=item.pk)
            )
            return StoredResponse(201, _body(request, checkpoint_data(item)), {})

        return _idempotent(request, payload=serializer.validated_data, operation=operation)


class UserCheckpointRestoreView(APIView):
    permission_classes = [IsUserPortal]
    serializer_class = WorkspaceSnapshotSerializer

    @extend_schema(
        parameters=[IF_MATCH, IDEMPOTENCY_KEY, WORKSPACE_TOKEN],
        tags=["workspaces"],
        responses={200: WorkspaceSnapshotSerializer},
        extensions={"x-portals": ["USER"]},
    )
    def post(self, request: HttpRequest, task_id: str, checkpoint_id: str) -> Response:
        expected = parse_if_match(request.headers.get("If-Match"))

        def operation() -> StoredResponse:
            session, snapshot = restore_checkpoint(
                task_id=task_id,
                checkpoint_id=checkpoint_id,
                actor=request.user,
                token=_workspace_token(request),
                expected_version=expected,
                context=_context(request),
                idempotency_key=str(getattr(request, "idempotency_key", "")),
            )
            if isinstance(snapshot, WorkspaceStorageJob):
                return StoredResponse(
                    202,
                    _body(request, storage_job_data(snapshot)),
                    {
                        "ETag": etag_for_version(session.row_version),
                        "Location": f"/api/v2/workspace-storage-jobs/{snapshot.public_id}",
                    },
                )
            return StoredResponse(
                200,
                _body(request, snapshot_data(snapshot)),
                {"ETag": etag_for_version(session.row_version)},
            )

        return _idempotent(request, payload={"checkpoint_id": checkpoint_id}, operation=operation)


def _cursor_page(request: HttpRequest, rows: list[dict[str, object]], *, key: str) -> Response:
    cursor = request.query_params.get("cursor", "")
    limit = min(max(int(request.query_params.get("limit", 50)), 1), 100)
    if cursor:
        values = decode_cursor(cursor)
        marker = str(values.get(key, ""))
        rows = [item for item in rows if str(item.get(key, "")) < marker]
    page = rows[:limit]
    next_cursor = encode_cursor({key: str(page[-1][key])}) if len(rows) > limit and page else None
    return _response(request, {"items": page, "next_cursor": next_cursor})


class UserOperationReplayView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        tags=["workspaces"],
        responses=OperationEventSerializer(many=True),
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest, task_id: str) -> Response:
        task_for_user(actor=request.user, task_id=task_id)
        rows = [
            operation_data(item) for item in replay_for_user(actor=request.user, task_id=task_id)
        ]
        return _cursor_page(request, rows, key="occurred_at")


@extend_schema_view(
    get=extend_schema(
        operation_id="tasks_execution_runs_list",
        parameters=[WORKSPACE_TOKEN],
        responses=WorkspaceExecutionRunListSerializer,
        tags=["workspaces"],
        extensions={"x-portals": ["USER"]},
    ),
    post=extend_schema(
        operation_id="tasks_execution_runs_create",
        parameters=[WORKSPACE_TOKEN, IDEMPOTENCY_KEY],
        request=ExecutionRunCreateSerializer,
        responses={201: WorkspaceExecutionRunSerializer},
        tags=["workspaces"],
        extensions={"x-portals": ["USER"]},
    ),
)
class UserExecutionRunListView(APIView):
    permission_classes = [IsUserPortal]

    def get(self, request: HttpRequest, task_id: str) -> Response:
        task_for_user(actor=request.user, task_id=task_id)
        session = active_session_for_user(actor=request.user, task_id=task_id)
        require_workspace_session(
            session=session, token=_workspace_token(request), task_id=task_id
        )
        rows = [
            execution_run_data(item)
            for item in execution_runs_for_user(actor=request.user, task_id=task_id)[:100]
        ]
        return _response(request, {"items": rows})

    def post(self, request: HttpRequest, task_id: str) -> Response:
        serializer = ExecutionRunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> StoredResponse:
            task_for_user(actor=request.user, task_id=task_id)
            session = active_session_for_user(actor=request.user, task_id=task_id)
            token = _workspace_token(request)
            require_workspace_session(
                session=session, token=token, task_id=task_id
            )
            run = request_execution_run(
                session=session,
                token=token,
                actor=request.user,
                arguments=dict(serializer.validated_data),
                request_key=str(getattr(request, "idempotency_key", "")),
                context=_context(request),
            )
            run = WorkspaceExecutionRun.objects.select_related("snapshot").get(pk=run.pk)
            return StoredResponse(
                201, _body(request, execution_run_data(run)), {}
            )

        return _idempotent(request, payload=dict(serializer.validated_data), operation=operation)


class UserExecutionRunDetailView(APIView):
    permission_classes = [IsUserPortal]

    @extend_schema(
        parameters=[WORKSPACE_TOKEN],
        responses=WorkspaceExecutionRunSerializer,
        tags=["workspaces"],
        extensions={"x-portals": ["USER"]},
    )
    def get(self, request: HttpRequest, task_id: str, execution_id: str) -> Response:
        session = active_session_for_user(actor=request.user, task_id=task_id)
        require_workspace_session(
            session=session, token=_workspace_token(request), task_id=task_id
        )
        run = execution_run_for_user(
            actor=request.user, task_id=task_id, execution_id=execution_id
        )
        return _response(request, execution_run_data(run))


class TeachingWorkspaceView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        tags=["workspaces"],
        responses=OpenApiResponse(description="authorized workspace projection"),
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, task_id: str) -> Response:
        task = task_for_teaching(actor=request.user, course_id=course_id, task_id=task_id)
        snapshots = snapshots_for_teaching(actor=request.user, course_id=course_id, task_id=task_id)
        latest = snapshots.first()
        return _response(
            request,
            {
                "task_id": task.public_id,
                "course_id": course_id,
                "status": task.status,
                "latest_snapshot": snapshot_data(latest) if latest else None,
                "snapshot_count": snapshots.count(),
            },
        )


class TeachingOperationReplayView(APIView):
    permission_classes = [IsTeachingPortal]

    @extend_schema(
        tags=["workspaces"],
        responses=OperationEventSerializer(many=True),
        extensions={"x-portals": ["TEACHING"]},
    )
    def get(self, request: HttpRequest, course_id: str, task_id: str) -> Response:
        rows = [
            operation_data(item)
            for item in replay_for_teaching(
                actor=request.user, course_id=course_id, task_id=task_id
            )
        ]
        return _cursor_page(request, rows, key="occurred_at")


class PlatformWorkspaceSessionsView(APIView):
    permission_classes = [IsPlatformPortal]

    @extend_schema(
        tags=["workspaces"],
        responses=OpenApiResponse(description="workspace session summaries"),
        extensions={"x-portals": ["PLATFORM"]},
    )
    def get(self, request: HttpRequest) -> Response:
        values = []
        for item in sessions_for_platform()[:100]:
            values.append({
                "public_id": item.public_id,
                "task_id": item.task.public_id,
                "course_id": item.course.public_id,
                "student_id": item.student.public_id,
                "status": item.status,
                "expires_at": item.expires_at,
                "revoked_at": item.revoked_at,
                "current_version": item.current_version,
            })
        return _response(request, values)
