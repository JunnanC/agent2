from apps.core.errors import CoreError


class RubricStateConflict(CoreError):
    code = "RUBRIC_STATE_CONFLICT"
    message = "Rubric 当前状态不允许此操作"
    status_code = 409


class RubricValidationError(CoreError):
    code = "RUBRIC_VALIDATION_ERROR"
    message = "Rubric 评分约束无效"
    status_code = 422


class ReviewStateConflict(CoreError):
    code = "REVIEW_STATE_CONFLICT"
    message = "审核当前状态不允许此操作"
    status_code = 409


class ReviewValidationError(CoreError):
    code = "REVIEW_VALIDATION_ERROR"
    message = "审核数据不符合约束"
    status_code = 422


class AutoCheckPending(CoreError):
    code = "AUTO_CHECK_PENDING"
    message = "自动检查尚未完成"
    status_code = 409


class SimilarityUnavailable(CoreError):
    code = "SIMILARITY_UNAVAILABLE"
    message = "当前成果不支持相似度分析"
    status_code = 409
