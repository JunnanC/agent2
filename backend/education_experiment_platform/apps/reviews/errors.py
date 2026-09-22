from apps.core.errors import CoreError


class RubricStateConflict(CoreError):
    code = "RUBRIC_STATE_CONFLICT"
    message = "Rubric 当前状态不允许此操作"
    status_code = 409


class RubricValidationError(CoreError):
    code = "RUBRIC_VALIDATION_ERROR"
    message = "Rubric 评分约束无效"
    status_code = 422
