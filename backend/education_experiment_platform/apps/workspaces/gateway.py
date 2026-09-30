import hmac
import json

from django.conf import settings
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.core.errors import CoreError

from .models import WorkspaceSession
from .permissions import require_workspace_session
from .selectors import session_by_public_id
from .serializers import WorkspaceOperationSerializer, operation_data, session_data, snapshot_data
from .services import record_operation


def _error_response(request, error: CoreError) -> JsonResponse:  # type: ignore[no-untyped-def]
    return JsonResponse(
        {
            "error": {
                "code": error.code,
                "message": error.response_message,
                "detail": error.detail,
                "trace_id": getattr(request, "trace_id", ""),
                "retryable": error.retryable,
            }
        },
        status=error.status_code,
    )


@method_decorator(csrf_exempt, name="dispatch")
class WorkspaceGatewayView(View):
    def dispatch(self, request, *args, **kwargs):  # type: ignore[no-untyped-def]
        supplied_key = request.headers.get("X-Workspace-Internal-Key", "")
        if not hmac.compare_digest(supplied_key, settings.WORKSPACE_INTERNAL_KEY):
            return JsonResponse(
                {"error": {"code": "WORKSPACE_INTERNAL_DENIED"}}, status=403
            )
        if request.headers.get("X-Portal") != "USER":
            return JsonResponse(
                {"error": {"code": "WORKSPACE_PORTAL_DENIED", "message": "工作区入口仅允许用户端"}},
                status=403,
            )
        return super().dispatch(request, *args, **kwargs)

    def _session(self, session_id: str) -> WorkspaceSession:
        session = session_by_public_id(session_id=session_id)
        return require_workspace_session(
            session=session,
            token=self.request.headers.get("X-Workspace-Token", ""),
            task_id=session.task.public_id,
        )

    def get(self, request, session_id: str, action: str):  # type: ignore[no-untyped-def]
        try:
            session = self._session(session_id)
            if action != "state":
                return JsonResponse(
                    {"error": {"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"}},
                    status=404,
                )
            return JsonResponse({
                "data": {
                    "session": session_data(session),
                    "snapshot": snapshot_data(session.latest_snapshot)
                    if session.latest_snapshot
                    else None,
                },
                "meta": {"trace_id": getattr(request, "trace_id", "")},
            })
        except CoreError as error:
            return _error_response(request, error)

    def post(self, request, session_id: str, action: str):  # type: ignore[no-untyped-def]
        try:
            session = self._session(session_id)
            if action != "operations":
                return JsonResponse(
                    {"error": {"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"}},
                    status=404,
                )
            try:
                body = json.loads(request.body or b"{}")
            except (TypeError, json.JSONDecodeError):
                return JsonResponse(
                    {"error": {"code": "VALIDATION_ERROR", "message": "请求格式无效"}},
                    status=400,
                )
            if not isinstance(body, dict):
                return JsonResponse(
                    {"error": {"code": "VALIDATION_ERROR", "message": "请求格式无效"}},
                    status=400,
                )
            serializer = WorkspaceOperationSerializer(data=body)
            if not serializer.is_valid():
                return JsonResponse(
                    {
                        "error": {
                            "code": "VALIDATION_ERROR",
                            "message": "请求参数无效",
                            "detail": serializer.errors,
                        }
                    },
                    status=400,
                )
            event = record_operation(
                session=session,
                token=request.headers.get("X-Workspace-Token", ""),
                actor=session.student,
                operation=serializer.validated_data["operation"],
                arguments=serializer.validated_data.get("arguments", {}),
                request_key=request.headers.get("Idempotency-Key", ""),
                context=type(
                    "Context",
                    (),
                    {
                        "trace_id": getattr(request, "trace_id", ""),
                        "portal": "USER",
                        "actor_ref": session.student.public_id,
                        "client_ip": "",
                        "user_agent": "",
                    },
                )(),
            )
            return JsonResponse(
                {
                    "data": operation_data(event),
                    "meta": {"trace_id": getattr(request, "trace_id", "")},
                },
                status=201,
            )
        except CoreError as error:
            return _error_response(request, error)
