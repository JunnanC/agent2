from apps.core.errors import CoreError


class InvalidCredentials(CoreError):
    code = "INVALID_CREDENTIALS"
    message = "账号或密码错误"
    status_code = 401


class AuthRequired(CoreError):
    code = "AUTH_REQUIRED"
    message = "请先登录"
    status_code = 401


class SessionPortalMismatch(CoreError):
    code = "SESSION_PORTAL_MISMATCH"
    message = "当前会话不属于此门户"
    status_code = 401


class SessionExpired(CoreError):
    code = "SESSION_EXPIRED"
    message = "会话已失效，请重新登录"
    status_code = 401


class PortalAccessDenied(CoreError):
    code = "PORTAL_ACCESS_DENIED"
    message = "当前门户不允许此操作"
    status_code = 403


class TeacherQualificationRequired(CoreError):
    code = "TEACHER_QUALIFICATION_REQUIRED"
    message = "需要有效教师资格"
    status_code = 403


class PlatformAccessRequired(CoreError):
    code = "PLATFORM_ACCESS_REQUIRED"
    message = "需要有效平台管理员资格"
    status_code = 403


class CsrfFailed(CoreError):
    code = "CSRF_FAILED"
    message = "CSRF 校验失败"
    status_code = 403


class AccountStateConflict(CoreError):
    code = "ACCOUNT_STATE_CONFLICT"
    message = "账号当前状态不允许此操作"
    status_code = 409


class QualificationStateConflict(CoreError):
    code = "QUALIFICATION_STATE_CONFLICT"
    message = "资格当前状态不允许此操作"
    status_code = 409


class VerificationStateConflict(CoreError):
    code = "VERIFICATION_STATE_CONFLICT"
    message = "身份资料当前状态不允许此操作"
    status_code = 409


class LastPlatformAdminProtected(CoreError):
    code = "LAST_PLATFORM_ADMIN_PROTECTED"
    message = "不能撤销最后一名平台管理员"
    status_code = 409


class RateLimited(CoreError):
    code = "RATE_LIMITED"
    message = "登录尝试过于频繁，请稍后再试"
    status_code = 429
    retryable = True


class AccountAlreadyExists(CoreError):
    code = "ACCOUNT_ALREADY_EXISTS"
    message = "账号标识已被使用"
    status_code = 409


class PasswordInvalid(CoreError):
    code = "PASSWORD_INVALID"
    message = "密码不符合安全要求"
    status_code = 400


class AuthenticationServiceUnavailable(CoreError):
    code = "AUTH_SERVICE_UNAVAILABLE"
    message = "认证服务暂时不可用"
    status_code = 503
    retryable = True
