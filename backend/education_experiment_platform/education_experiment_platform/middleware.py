import ipaddress
import re
import secrets
import time
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

from .logging import portal_var, trace_id_var

TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$")
PORTALS = {"USER", "TEACHING", "PLATFORM"}
INTEGRATION_PREFIXES = (
    "/api/v2/integrations/oauth/token",
    "/api/v2/integrations/open/",
)
IDEMPOTENCY_EXEMPT_POST_PATHS = frozenset({
    "/api/v2/auth/login",
    "/api/v2/auth/logout",
    "/api/v2/auth/logout-all",
    "/api/v2/integrations/oauth/token",
    "/api/v2/course-invitations/resolve",
})


def _error(code: str, message: str, trace_id: str, status: int) -> JsonResponse:
    return JsonResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "detail": {},
                "trace_id": trace_id,
                "retryable": False,
            }
        },
        status=status,
    )


class TraceContextMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        started = time.monotonic()
        incoming = request.headers.get("traceparent", "").lower()
        match = TRACEPARENT_RE.match(incoming)
        trace_id = match.group(1) if match else secrets.token_hex(16)
        token = trace_id_var.set(trace_id)
        request.trace_id = trace_id
        try:
            response = self.get_response(request)
        finally:
            trace_id_var.reset(token)
        response["X-Request-ID"] = trace_id
        response["traceparent"] = f"00-{trace_id}-{secrets.token_hex(8)}-01"
        response["Server-Timing"] = f"app;dur={(time.monotonic() - started) * 1000:.2f}"
        return response


class PortalContextMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.networks = [ipaddress.ip_network(item) for item in settings.TRUSTED_PROXY_CIDRS]

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not request.path.startswith("/api/v2/"):
            return self.get_response(request)

        # Direct health checks are allowed for container orchestration only.
        if request.path in {"/api/v2/health", "/api/v2/health/ready"} and not request.headers.get(
            "X-Portal"
        ):
            return self.get_response(request)

        remote = request.META.get("REMOTE_ADDR", "")
        try:
            trusted_source = any(
                ipaddress.ip_address(remote) in network for network in self.networks
            )
        except ValueError:
            trusted_source = False
        if not trusted_source or request.headers.get("X-Proxy-Context") != "ingress-v1":
            return _error("PROXY_CONTEXT_UNTRUSTED", "请求入口不受信任", request.trace_id, 400)

        portal = request.headers.get("X-Portal", "")
        auth_context = request.headers.get("X-Auth-Context", "")
        integration_route = any(request.path.startswith(prefix) for prefix in INTEGRATION_PREFIXES)
        if integration_route:
            if auth_context != "INTEGRATION" or portal:
                return _error("AUTH_CONTEXT_INVALID", "机器 API 上下文无效", request.trace_id, 400)
        elif portal not in PORTALS or auth_context:
            return _error("PORTAL_UNKNOWN", "门户上下文无效", request.trace_id, 400)

        request.portal = portal or None
        request.auth_context = auth_context or None
        portal_token = portal_var.set(portal or auth_context)
        try:
            return self.get_response(request)
        finally:
            portal_var.reset(portal_token)


class FilePortalContextMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith("/files/"):
            portal = request.session.get("account_portal")
            if portal in {"USER", "TEACHING", "PLATFORM"}:
                request.portal = portal
                portal_token = portal_var.set(portal)
                try:
                    return self.get_response(request)
                finally:
                    portal_var.reset(portal_token)
        return self.get_response(request)


class IdempotencyKeyMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        normalized_path = request.path.rstrip("/") or "/"
        report_draft_put = (
            request.method == "PUT"
            and re.fullmatch(r"/api/v2/tasks/[^/]+/report-draft", normalized_path) is not None
        )
        if (
            (request.method == "POST" or report_draft_put)
            and request.path.startswith("/api/v2/")
            and normalized_path not in IDEMPOTENCY_EXEMPT_POST_PATHS
        ):
            key = request.headers.get("Idempotency-Key", "")
            if not key or len(key) > 128:
                return _error(
                    "IDEMPOTENCY_KEY_REQUIRED",
                    "该操作必须提供 Idempotency-Key",
                    request.trace_id,
                    428,
                )
            request.idempotency_key = key
        return self.get_response(request)
