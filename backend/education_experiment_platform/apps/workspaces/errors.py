from apps.core.errors import CoreError


class WorkspaceSessionInvalid(CoreError):
    code = "WORKSPACE_SESSION_INVALID"
    message = "工作区会话无效"
    status_code = 401


class WorkspaceSessionExpired(CoreError):
    code = "WORKSPACE_SESSION_EXPIRED"
    message = "工作区会话已过期"
    status_code = 401


class WorkspaceSessionRevoked(CoreError):
    code = "WORKSPACE_SESSION_REVOKED"
    message = "工作区会话已撤销"
    status_code = 401


class WorkspacePortalDenied(CoreError):
    code = "WORKSPACE_PORTAL_DENIED"
    message = "当前门户不能访问学生工作区"
    status_code = 403


class WorkspaceTaskMismatch(CoreError):
    code = "WORKSPACE_TASK_MISMATCH"
    message = "工作区与任务不匹配"
    status_code = 403


class WorkspaceCapabilityDenied(CoreError):
    code = "WORKSPACE_CAPABILITY_DENIED"
    message = "工作区能力未授权"
    status_code = 403


class AutosaveStale(CoreError):
    code = "AUTOSAVE_SEQ_STALE"
    message = "自动保存序号已过期"
    status_code = 409


class AutosaveConflict(CoreError):
    code = "AUTOSAVE_CONFLICT"
    message = "自动保存与服务端版本冲突"
    status_code = 412


class WorkspaceScanUnavailable(CoreError):
    code = "WORKSPACE_SCAN_UNAVAILABLE"
    message = "文件安全扫描暂时不可用"
    status_code = 503
    retryable = True


class CheckpointStateConflict(CoreError):
    code = "CHECKPOINT_STATE_CONFLICT"
    message = "检查点当前状态不允许该操作"
    status_code = 409


class WorkspaceOperationDenied(CoreError):
    code = "WORKSPACE_OPERATION_DENIED"
    message = "工作区操作不被允许"
    status_code = 403


class WorkspaceStorageJobActive(CoreError):
    code = "WORKSPACE_STORAGE_JOB_ACTIVE"
    message = "工作区存储作业正在执行"
    status_code = 409
    retryable = True


class WorkspaceCaptureUnsupported(CoreError):
    code = "WORKSPACE_CAPTURE_UNSUPPORTED"
    message = "当前工作区不支持服务端捕获"
    status_code = 409


class WorkspaceFileMissing(CoreError):
    code = "WORKSPACE_FILE_MISSING"
    message = "工作区入口文件不存在"
    status_code = 409


class WorkspaceFileTooLarge(CoreError):
    code = "WORKSPACE_FILE_TOO_LARGE"
    message = "工作区入口文件超过大小限制"
    status_code = 413


class WorkspaceFileInvalid(CoreError):
    code = "WORKSPACE_FILE_INVALID"
    message = "工作区入口文件格式无效"
    status_code = 422


class WorkspaceCaptureConflict(CoreError):
    code = "WORKSPACE_CAPTURE_CONFLICT"
    message = "工作区捕获版本冲突"
    status_code = 412


class WorkspaceSnapshotNotReady(CoreError):
    code = "WORKSPACE_SNAPSHOT_NOT_READY"
    message = "工作区快照尚未就绪"
    status_code = 409


class WorkspaceCaptureFailed(CoreError):
    code = "WORKSPACE_CAPTURE_FAILED"
    message = "工作区捕获失败"
    status_code = 502
    retryable = True


class WorkspaceRestoreFailed(CoreError):
    code = "WORKSPACE_RESTORE_FAILED"
    message = "工作区恢复失败"
    status_code = 502
    retryable = True


class WorkspaceVolumeUnavailable(CoreError):
    code = "WORKSPACE_VOLUME_UNAVAILABLE"
    message = "工作区存储卷暂不可用"
    status_code = 503
    retryable = True
