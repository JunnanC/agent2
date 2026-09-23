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


class CheckpointStateConflict(CoreError):
    code = "CHECKPOINT_STATE_CONFLICT"
    message = "检查点当前状态不允许该操作"
    status_code = 409


class WorkspaceOperationDenied(CoreError):
    code = "WORKSPACE_OPERATION_DENIED"
    message = "工作区操作不被允许"
    status_code = 403
