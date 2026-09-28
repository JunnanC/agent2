import hmac
import time
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.authentication import (
    SESSION_ABSOLUTE_EXPIRES_AT,
    SESSION_PORTAL,
    SESSION_SECURITY_VERSION,
    SESSION_USER_ID,
)
from apps.accounts.models import User

from .permissions import require_workspace_session
from .selectors import session_by_public_id


@csrf_exempt
@require_POST
def authorize_workspace(request):  # type: ignore[no-untyped-def]
    supplied_key = request.headers.get("X-Workspace-Internal-Key", "")
    if not hmac.compare_digest(supplied_key, settings.WORKSPACE_INTERNAL_KEY):
        return JsonResponse({"error": {"code": "WORKSPACE_INTERNAL_DENIED"}}, status=403)
    session_id = request.headers.get("X-Workspace-Session", "")
    token = request.headers.get("X-Workspace-Token", "")
    portal_session_key = request.headers.get("X-Portal-Session", "")
    try:
        portal_session = SessionStore(session_key=portal_session_key)
        values = portal_session.load()
        if values.get(SESSION_PORTAL) != "USER":
            return JsonResponse({"error": {"code": "WORKSPACE_PORTAL_DENIED"}}, status=403)
        if int(values.get(SESSION_ABSOLUTE_EXPIRES_AT, 0)) <= int(time.time()):
            return JsonResponse({"error": {"code": "SESSION_EXPIRED"}}, status=401)
        user = User.objects.get(pk=values.get(SESSION_USER_ID))
        if values.get(SESSION_SECURITY_VERSION) != user.security_version:
            return JsonResponse({"error": {"code": "SESSION_EXPIRED"}}, status=401)
        session = session_by_public_id(session_id=session_id)
        if session.student_id != user.pk:
            return JsonResponse({"error": {"code": "WORKSPACE_SESSION_INVALID"}}, status=404)
        capability = request.headers.get("X-Workspace-Capability") or None
        require_workspace_session(
            session=session,
            token=token,
            task_id=session.task.public_id,
            capability=capability,
        )
        metadata = session.instance.external_metadata or {}
        endpoint = str(session.instance.endpoint or "")
        parsed = urlsplit(endpoint)
        service_name = str(metadata.get("service_name") or "")
        expected_host = f"tasks.{service_name}" if service_name else ""
        expected_port = int(metadata.get("workspace_port") or 0)
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or metadata.get("managed") is not True
            or parsed.hostname != expected_host
            or parsed.port != expected_port
        ):
            return JsonResponse({"error": {"code": "WORKSPACE_UPSTREAM_INVALID"}}, status=503)
        return JsonResponse(
            {
                "data": {
                    "endpoint": endpoint.rstrip("/"),
                    "service_name": service_name,
                    "workspace_port": expected_port,
                }
            }
        )
    except (TypeError, ValueError, User.DoesNotExist):
        return JsonResponse({"error": {"code": "SESSION_EXPIRED"}}, status=401)
    except Exception as exc:  # noqa: BLE001 - CoreError carries a stable public code
        code = getattr(exc, "code", "WORKSPACE_SESSION_INVALID")
        status = int(getattr(exc, "status_code", 403))
        return JsonResponse({"error": {"code": code}}, status=status)
