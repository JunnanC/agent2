from apps.core.errors import CoreError


class GovernanceValidationError(CoreError):
    code = "GOVERNANCE_VALIDATION_ERROR"
    message = "治理配置无效"
    status_code = 422


class GovernanceStateConflict(CoreError):
    code = "GOVERNANCE_STATE_CONFLICT"
    message = "治理资源当前状态不允许此操作"
    status_code = 409


class ImageNotApproved(CoreError):
    code = "IMAGE_NOT_APPROVED"
    message = "镜像尚未通过扫描和批准"
    status_code = 409


class QuotaNotConfigured(CoreError):
    code = "QUOTA_NOT_CONFIGURED"
    message = "平台配额尚未配置"
    status_code = 409


class QuotaExceeded(CoreError):
    code = "QUOTA_EXCEEDED"
    message = "资源请求超过可用配额"
    status_code = 409


class BudgetExceeded(CoreError):
    code = "BUDGET_EXCEEDED"
    message = "资源请求超过预算护栏"
    status_code = 409


class ScalingCooldownActive(CoreError):
    code = "SCALING_COOLDOWN_ACTIVE"
    message = "扩缩容策略仍处于冷却期"
    status_code = 409


class RecentAuthenticationRequired(CoreError):
    code = "RECENT_AUTHENTICATION_REQUIRED"
    message = "该操作需要近期认证"
    status_code = 403
