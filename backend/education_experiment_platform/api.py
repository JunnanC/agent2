import logging
from typing import Any

from django.http import HttpRequest, JsonResponse
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from apps.core.errors import CoreError

logger = logging.getLogger(__name__)


def _payload(
    *,
    code: str,
    message: str,
    detail: object,
    trace_id: str,
    retryable: bool,
) -> dict[str, object]:
    return {
        "error": {
            "code": code,
            "message": message,
            "detail": detail,
            "trace_id": trace_id,
            "retryable": retryable,
        }
    }


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    request = context.get("request")
    trace_id = getattr(request, "trace_id", "")
    if isinstance(exc, CoreError):
        return Response(
            _payload(
                code=exc.code,
                message=exc.response_message,
                detail=exc.detail,
                trace_id=trace_id,
                retryable=exc.retryable,
            ),
            status=exc.status_code,
        )
    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception(
            "unhandled api exception",
            exc_info=exc,
            extra={
                "action": "api.exception",
                "result": "FAILED",
                "error_code": "INTERNAL_ERROR",
                "trace_id": trace_id,
            },
        )
        return Response(
            _payload(
                code="INTERNAL_ERROR",
                message="服务暂时无法处理请求",
                detail={},
                trace_id=trace_id,
                retryable=True,
            ),
            status=500,
        )
    detail = response.data
    codes = {
        400: "VALIDATION_ERROR",
        401: "AUTH_REQUIRED",
        403: "PORTAL_ACCESS_DENIED",
        404: "RESOURCE_NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        429: "RATE_LIMITED",
    }
    if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
        code = "AUTH_REQUIRED"
    elif isinstance(exc, PermissionDenied):
        code = "PORTAL_ACCESS_DENIED"
    else:
        code = codes.get(response.status_code, "REQUEST_FAILED")
    response.data = _payload(
        code=code,
        message="请求无法处理",
        detail=detail,
        trace_id=trace_id,
        retryable=response.status_code in {429, 503},
    )
    return response


def api_not_found(request: HttpRequest, _path: str = "") -> JsonResponse:
    return JsonResponse(
        _payload(
            code="RESOURCE_NOT_FOUND",
            message="资源不存在",
            detail={},
            trace_id=getattr(request, "trace_id", ""),
            retryable=False,
        ),
        status=404,
    )
