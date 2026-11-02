from apps.core.errors import CoreError, StateConflict


class AgentScopeDenied(CoreError):
    code = "AGENT_SCOPE_DENIED"
    message = "当前账号无权访问该 Agent 资源"
    status_code = 404


class AgentProfileStateConflict(StateConflict):
    code = "AGENT_PROFILE_STATE_CONFLICT"
    message = "Agent profile 当前状态不允许该操作"


class AgentEvaluationRequired(CoreError):
    code = "AGENT_EVALUATION_REQUIRED"
    message = "Agent profile 尚未通过必需评测"
    status_code = 409


class AgentNoReliableSource(CoreError):
    code = "AGENT_NO_RELIABLE_SOURCE"
    message = "没有找到可靠的课程资料来源"
    status_code = 200


class AgentToolApprovalRequired(CoreError):
    code = "AGENT_TOOL_APPROVAL_REQUIRED"
    message = "该工具调用需要人工审批"
    status_code = 409


class AgentToolDenied(CoreError):
    code = "AGENT_TOOL_DENIED"
    message = "工具调用被安全策略拒绝"
    status_code = 403


class AgentQuotaExceeded(CoreError):
    code = "AGENT_QUOTA_EXCEEDED"
    message = "Agent 配额已用尽"
    status_code = 429
    retryable = True


class AgentModelUnavailable(CoreError):
    code = "AGENT_MODEL_UNAVAILABLE"
    message = "当前模型路由不可用"
    status_code = 503
    retryable = True
