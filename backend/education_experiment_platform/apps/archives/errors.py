from apps.core.errors import CoreError


class ArchiveStateConflict(CoreError):
    code = "ARCHIVE_STATE_CONFLICT"
    message = "归档当前状态不允许该操作"
    status_code = 409


class ArchiveVerificationFailed(CoreError):
    code = "ARCHIVE_VERIFICATION_FAILED"
    message = "归档对象校验失败"
    status_code = 409
    retryable = True


class ArchiveExportDenied(CoreError):
    code = "ARCHIVE_EXPORT_DENIED"
    message = "当前账号不能导出该归档"
    status_code = 404


class InstanceDestroyConflict(CoreError):
    code = "INSTANCE_DESTROY_CONFLICT"
    message = "实例当前状态不允许销毁"
    status_code = 409
