from typing import Any


class CoreError(Exception):
    code = "REQUEST_FAILED"
    message = "请求无法处理"
    status_code = 400
    retryable = False

    def __init__(
        self,
        *,
        detail: dict[str, Any] | None = None,
        message: str | None = None,
    ) -> None:
        super().__init__(message or self.message)
        self.detail = detail or {}
        self.response_message = message or self.message


class ImmutableRecordError(CoreError):
    code = "IMMUTABLE_VERSION"
    message = "不可变事实不能修改或删除"
    status_code = 422


class IdempotencyKeyRequired(CoreError):
    code = "IDEMPOTENCY_KEY_REQUIRED"
    message = "该操作必须提供 Idempotency-Key"
    status_code = 428


class IdempotencyKeyReused(CoreError):
    code = "IDEMPOTENCY_KEY_REUSED"
    message = "幂等键已用于不同请求"
    status_code = 422


class IdempotencyRequestInProgress(CoreError):
    code = "IDEMPOTENCY_REQUEST_IN_PROGRESS"
    message = "相同请求正在处理中"
    status_code = 409
    retryable = True


class PreconditionRequired(CoreError):
    code = "PRECONDITION_REQUIRED"
    message = "该操作必须提供 If-Match"
    status_code = 428


class RowVersionConflict(CoreError):
    code = "ROW_VERSION_CONFLICT"
    message = "资源已被其他请求修改"
    status_code = 412


class InvalidPrecondition(CoreError):
    code = "INVALID_PRECONDITION"
    message = "If-Match 格式无效"
    status_code = 400


class StateConflict(CoreError):
    code = "STATE_CONFLICT"
    message = "资源当前状态不允许该操作"
    status_code = 409


class ResourceNotFound(CoreError):
    code = "RESOURCE_NOT_FOUND"
    message = "资源不存在"
    status_code = 404


class DownloadGrantInvalid(CoreError):
    code = "DOWNLOAD_GRANT_INVALID"
    message = "下载授权无效或已过期"
    status_code = 404


class DownloadScopeDenied(CoreError):
    code = "DOWNLOAD_SCOPE_DENIED"
    message = "当前账号不能下载该文件"
    status_code = 404
