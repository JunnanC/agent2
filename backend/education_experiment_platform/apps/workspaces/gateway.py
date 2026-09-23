import json

from django.http import JsonResponse
from django.views import View

from .models import WorkspaceSession
from .permissions import require_workspace_session
from .selectors import session_by_public_id
from .serializers import operation_data, session_data, snapshot_data
from .services import record_operation


class WorkspaceGatewayView(View):
    def dispatch(self, request, *args, **kwargs):  # type: ignore[no-untyped-def]
        if request.headers.get("X-Portal") != "USER":
            return JsonResponse(
                {"error": {"code": "WORKSPACE_PORTAL_DENIED", "message": "工作区入口仅允许用户端"}},
                status=403,
            )
        return super().dispatch(request, *args, **kwargs)

    def _session(self, session_id: str) -> WorkspaceSession:
        session = session_by_public_id(session_id)
        return require_workspace_session(
            session=session,
            token=self.request.headers.get("X-Workspace-Token", ""),
            task_id=session.task.public_id,
        )

    def get(self, request, session_id: str, action: str):  # type: ignore[no-untyped-def]
        session = self._session(session_id)
        if action != "state":
            return JsonResponse(
                {"error": {"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"}}, status=404
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

    def post(self, request, session_id: str, action: str):  # type: ignore[no-untyped-def]
        session = self._session(session_id)
        if action != "operations":
            return JsonResponse(
                {"error": {"code": "RESOURCE_NOT_FOUND", "message": "资源不存在"}}, status=404
            )
        try:
            body = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return JsonResponse(
                {"error": {"code": "VALIDATION_ERROR", "message": "请求格式无效"}}, status=400
            )
        event = record_operation(
            session=session,
            token=request.headers.get("X-Workspace-Token", ""),
            actor=session.student,
            operation=str(body.get("operation", "")),
            arguments=body.get("arguments") if isinstance(body.get("arguments"), dict) else {},
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
            {"data": operation_data(event), "meta": {"trace_id": getattr(request, "trace_id", "")}},
            status=201,
        )
