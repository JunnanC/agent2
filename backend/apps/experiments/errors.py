from apps.core.errors import CoreError


class PublicationStateConflict(CoreError):
    code = "PUBLICATION_STATE_CONFLICT"
    message = "实验发布当前状态不允许此操作"
    status_code = 409


class PublicationValidationError(CoreError):
    code = "PUBLICATION_VALIDATION_ERROR"
    message = "实验发布配置无效"
    status_code = 422


class PublicationPrerequisiteBlocked(CoreError):
    code = "PUBLICATION_PREREQUISITE_BLOCKED"
    message = "实验先修条件尚未满足"
    status_code = 409


class TaskStateConflict(CoreError):
    code = "TASK_STATE_CONFLICT"
    message = "实验任务当前状态不允许此操作"
    status_code = 409


class TaskExtensionConflict(CoreError):
    code = "TASK_EXTENSION_CONFLICT"
    message = "延期申请当前状态不允许此操作"
    status_code = 409


class ExperimentScopeDenied(CoreError):
    code = "EXPERIMENT_SCOPE_DENIED"
    message = "无权访问该实验对象"
    status_code = 404
