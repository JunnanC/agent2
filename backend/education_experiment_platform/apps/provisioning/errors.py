from apps.core.errors import CoreError


class ProvisioningStateConflict(CoreError):
    code = "PROVISIONING_STATE_CONFLICT"
    message = "装载作业当前状态不允许此操作"
    status_code = 409


class ProvisioningRuntimeError(CoreError):
    code = "RUNTIME_UNAVAILABLE"
    message = "实验运行时暂时不可用"
    status_code = 503
    retryable = True


class ProvisioningConfigurationError(CoreError):
    code = "PROVISIONING_CONFIGURATION_INVALID"
    message = "实验装载配置无效"
    status_code = 422
