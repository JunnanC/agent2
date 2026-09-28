import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  RequestIntent,
  apiRequestWithMetadata,
  createAgentSession,
  createTaskAgentSession,
  requestAgentTool,
  sendAgentMessage,
  type AgentMessageData,
  type AgentMode,
  type AgentProfileResponse,
  type AgentSessionData,
  type AgentToolCallData,
} from '@edu/api-client'
import { agentKeys, reportKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge, TextField } from '@edu/ui'

const modes: AgentMode[] = ['KNOWLEDGE_QA', 'SOCRATIC_HINT', 'DEBUG_ASSIST', 'REPORT_COACH', 'WORKSPACE_ASSIST']

function errorText(error: unknown): string {
  if (error instanceof ApiError) return `${error.payload.error.message}（trace: ${error.traceId || 'n/a'}）`
  return 'Agent 请求未完成，请稍后重试。'
}

export function UserAgentPage({ taskId, courseId }: { taskId?: string; courseId?: string }) {
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<AgentMode>('KNOWLEDGE_QA')
  const [session, setSession] = useState<AgentSessionData | null>(null)
  const [body, setBody] = useState('')
  const [toolName, setToolName] = useState('workspace_draft')
  const [toolArguments, setToolArguments] = useState('{"path":"draft.md"}')
  const [toolCall, setToolCall] = useState<AgentToolCallData | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const resolvedCourseId = courseId ?? ''
  const profile = useQuery({
    queryKey: agentKeys.profile(resolvedCourseId),
    queryFn: () => apiRequestWithMetadata<AgentProfileResponse>(`/api/v2/courses/${resolvedCourseId}/agent-profile`),
    enabled: Boolean(resolvedCourseId),
  })
  const messages = useQuery({
    queryKey: agentKeys.messages(session?.public_id ?? ''),
    queryFn: () => apiRequestWithMetadata<{ data: AgentMessageData[] }>(`/api/v2/agent-sessions/${session?.public_id}/messages`),
    enabled: Boolean(session),
    refetchInterval: session ? 2000 : false,
  })
  const profileData = profile.data?.payload.data
  const latestAssistant = useMemo(() => [...(messages.data?.payload.data ?? [])].reverse().find((item) => item.role === 'ASSISTANT'), [messages.data])

  const start = async () => {
    setError(''); setNotice(''); setToolCall(null)
    try {
      const result = taskId ? await createTaskAgentSession(taskId, mode) : await createAgentSession(resolvedCourseId, mode)
      setSession(result.payload.data); setNotice('会话已创建，profile、提示词和知识版本已冻结。')
      await queryClient.invalidateQueries({ queryKey: agentKeys.profile(resolvedCourseId) })
    } catch (cause) { setError(errorText(cause)) }
  }

  const send = async () => {
    if (!session || !body.trim()) return
    setError('')
    try { await sendAgentMessage(session.public_id, body.trim()); setBody(''); setNotice('消息已进入受控推理队列；页面会自动刷新异步结果。'); await messages.refetch() } catch (cause) { setError(errorText(cause)) }
  }

  const submitFeedback = async (message: AgentMessageData, rating: 'USEFUL' | 'NOT_USEFUL') => {
    setError('')
    try {
      await apiRequestWithMetadata(`/api/v2/agent-messages/${message.public_id}/feedback`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rating }), intent: new RequestIntent() })
      setNotice('反馈已进入待分析队列，不会自动成为训练数据。')
    } catch (cause) { setError(errorText(cause)) }
  }

  const requestTool = async () => {
    if (!session) return
    setError('')
    try {
      const parsed = JSON.parse(toolArguments) as Record<string, unknown>
      const result = await requestAgentTool(session.public_id, toolName, parsed)
      const value = result.payload.data
      setToolCall('tool_call' in value ? null : value)
      setNotice('工具请求已提交；HIGH/MEDIUM 风险必须逐次审批。')
    } catch (cause) { setError(cause instanceof SyntaxError ? '工具参数必须是 JSON 对象。' : errorText(cause)) }
  }

  const decideTool = async (decision: 'APPROVED' | 'REJECTED') => {
    if (!toolCall?.state) return
    setError('')
    try {
      const result = await apiRequestWithMetadata<{ data: { status: string; row_version: number } }>(`/api/v2/agent-tool-calls/${toolCall.public_id}/decide`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, reason: decision === 'APPROVED' ? 'student confirmed' : 'student rejected' }), ifMatch: `"${toolCall.state.row_version}"`, intent: new RequestIntent() })
      setToolCall({ ...toolCall, state: { ...toolCall.state, status: result.payload.data.status, row_version: result.payload.data.row_version } })
      setNotice(decision === 'APPROVED' ? '工具已获本次调用授权。' : '工具调用已拒绝。')
    } catch (cause) { setError(errorText(cause)) }
  }

  const confirmReportSuggestion = async () => {
    if (!taskId || !latestAssistant) return
    setError('')
    try {
      const draft = await apiRequestWithMetadata<{ data: { body_markdown: string; row_version: number } }>(`/api/v2/tasks/${taskId}/report-draft`)
      await apiRequestWithMetadata(`/api/v2/tasks/${taskId}/report-draft`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ body_markdown: `${draft.payload.data.body_markdown}\n\n### Agent 建议\n${latestAssistant.body}` }), ifMatch: draft.etag ?? `"${draft.payload.data.row_version}"`, intent: new RequestIntent() })
      await queryClient.invalidateQueries({ queryKey: reportKeys.draft(taskId) })
      setNotice('建议已由学生确认并写入报告草稿；不会自动提交报告。')
    } catch (cause) { setError(errorText(cause)) }
  }

  if (!taskId && profile.isPending) return <RequestStateView state="loading" />
  if (!taskId && profile.isError) return <RequestStateView state="error" message={errorText(profile.error)} onRetry={() => void profile.refetch()} />
  return <section className="workspace-page">
    <PageHeader eyebrow="CONTROLLED AGENT" title={taskId ? '任务 Agent' : '课程 Agent'} description="回答仅使用当前课程范围内的版本化资料；高风险工具不会自动执行。" />
    {error ? <p className="form-error" role="alert">{error}</p> : null}{notice ? <p className="notice" role="status">{notice}</p> : null}
    <section className="section-block"><h2>模式与会话</h2><label className="field"><span>模式</span><select value={mode} onChange={(event) => setMode(event.target.value as AgentMode)}>{(profileData?.profile.modes ?? modes).map((value) => <option value={value} key={value}>{value}</option>)}</select></label><button className="primary-button" onClick={() => void start()} disabled={!taskId && !profileData}>创建会话</button>{session ? <p>会话 <strong>{session.public_id}</strong> · <StatusBadge status={session.status} /> · profile v{session.profile_version}</p> : null}</section>
    {session ? <>
      <section className="section-block"><h2>消息</h2><div className="agent-thread">{messages.isPending ? <RequestStateView state="loading" /> : messages.isError ? <RequestStateView state="error" onRetry={() => void messages.refetch()} /> : (messages.data?.payload.data ?? []).map((item) => <article className="summary-item" key={item.public_id}><span>{item.role} · {item.status} · {item.citation_status}</span><p>{item.body}</p>{item.citations.map((citation) => <small key={citation.public_id}>[{citation.title}] {citation.snippet}</small>)}{item.role === 'ASSISTANT' ? <div className="toolbar"><button className="text-button" onClick={() => void submitFeedback(item, 'USEFUL')}>有帮助</button><button className="text-button" onClick={() => void submitFeedback(item, 'NOT_USEFUL')}>需改进</button>{taskId && mode === 'REPORT_COACH' ? <button className="text-button" onClick={() => void confirmReportSuggestion()}>确认写入草稿</button> : null}</div> : null}</article>)}</div><TextField label="发送消息" value={body} onChange={(event) => setBody(event.target.value)} /><button className="primary-button" onClick={() => void send()} disabled={!body.trim()}>提交推理</button></section>
      {mode === 'WORKSPACE_ASSIST' ? <section className="section-block"><h2>受控工具</h2><TextField label="工具名称" value={toolName} onChange={(event) => setToolName(event.target.value)} /><TextField label="参数 JSON" value={toolArguments} onChange={(event) => setToolArguments(event.target.value)} /><button className="text-button" onClick={() => void requestTool()}>请求工具</button>{toolCall ? <p>调用 {toolCall.tool_name} · <StatusBadge status={toolCall.state?.status ?? 'UNKNOWN'} />{toolCall.state?.status === 'PENDING_APPROVAL' ? <span className="toolbar"><button className="text-button" onClick={() => void decideTool('APPROVED')}>批准本次</button><button className="text-button text-button--danger" onClick={() => void decideTool('REJECTED')}>拒绝</button></span> : null}</p> : null}</section> : null}
    </> : null}
  </section>
}

export function UserCourseAgentRoute() { const { courseId = '' } = useParams(); return <UserAgentPage courseId={courseId} /> }
export function UserTaskAgentRoute() { const { taskId = '' } = useParams(); return <UserAgentPage taskId={taskId} /> }
