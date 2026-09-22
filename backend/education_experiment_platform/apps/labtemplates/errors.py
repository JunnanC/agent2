from apps.core.errors import CoreError


class TemplateStateConflict(CoreError):
    code = "TEMPLATE_STATE_CONFLICT"
    message = "模板或版本当前状态不允许此操作"
    status_code = 409


class TemplateValidationError(CoreError):
    code = "TEMPLATE_VALIDATION_ERROR"
    message = "模板规格无效"
    status_code = 422


class TemplateAssetNotReady(CoreError):
    code = "TEMPLATE_ASSET_NOT_READY"
    message = "模板资产尚未通过安全校验"
    status_code = 409


class TemplateDigestMismatch(CoreError):
    code = "TEMPLATE_DIGEST_MISMATCH"
    message = "模板规格与预检摘要不一致"
    status_code = 409


class TemplatePrecheckFailed(CoreError):
    code = "TEMPLATE_PRECHECK_FAILED"
    message = "模板预检未通过"
    status_code = 422


class TemplateUploadInvalid(CoreError):
    code = "TEMPLATE_UPLOAD_INVALID"
    message = "上传文件不符合安全要求"
    status_code = 422
