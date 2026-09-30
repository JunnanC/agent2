import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, LoaderCircle, Send, ThumbsDown, ThumbsUp, X } from 'lucide-react'
import {
  ApiError,
  RequestIntent,
  apiRequestWithMetadata,
  createAgentSession,
  createTaskAgentSession,
  decideAgentToolCall,
  getAgentMessages,
  getAgentSession,
  requestAgentTool,
  sendAgentMessage,
  submitAgentFeedback,
  type AgentMessageData,
  type AgentMode,
  type AgentProfileResponse,
  type AgentSessionData,
  type AgentToolCallData,
} from '@edu/api-client'
import { PortalEventClient } from '@edu/event-client'
import { agentKeys, reportKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge, TextField } from '@edu/ui'

const modes: AgentMode[] = ['KNOWLEDGE_QA', 'SOCRATIC_HINT', 'DEBUG_ASSIST', 'REPORT_COACH', 'WORKSPACE_ASSIST']

function errorText(error: unknown): string {
  if (error instanceof ApiError) return `${error.payload.error.message}（trace: ${error.traceId || 'n/a'}）`
  return 'Agent 请求未完成，请稍后重试。'
}

function drawerErrorText(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Agent 暂时不可用，请稍后重试。'
  if (error.status === 401) return '登录状态已失效，请重新登录。'
  if (error.status === 403) return '当前任务不允许使用 Agent。'
  if (error.status === 409 || error.status === 412) return '任务或审批状态已变化，请刷新后重试。'
  if (error.status === 429) return '请求过于频繁，请稍后再试。'
  return error.payload.error.message
}

const quickPrompts = [
  '解释当前步骤',
  '分析最近一次测试失败',
  '查看当前草稿问题',
  '给出下一步排查建议',
]

const activeToolStatuses = new Set(['QUEUED', 'RUNNING'])

function hasPendingReply(items: AgentMessageData[]): boolean {
  const latest = items.at(-1)
  return latest?.role === 'USER' || items.some((item) => item.tool_calls?.some((call) => activeToolStatuses.has(call.state?.status ?? '')))
}

type TaskAgentDrawerProps = {
  taskId: string
  open: boolean
  workspaceAvailable: boolean
  onClose: () => void
  onActivityChange?: (activity: { unread: number; processing: boolean }) => void
}

export function TaskAgentDrawer({ taskId, open, workspaceAvailable, onClose, onActivityChange }: TaskAgentDrawerProps) {
  const queryClient = useQueryClient()
  const [session, setSession] = useState<AgentSessionData | null>(null)
  const [body, setBody] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [streamState, setStreamState] = useState<'live' | 'polling'>('polling')
  const [seenAssistantCount, setSeenAssistantCount] = useState(0)
  const [feedback, setFeedback] = useState<Record<string, 'USEFUL' | 'NOT_USEFUL'>>({})
  const [pendingToolCall, setPendingToolCall] = useState('')
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const startIntent = useRef(new RequestIntent())
  const startAttempted = useRef(false)

  const start = useMutation({
    mutationFn: () => createTaskAgentSession(taskId, 'WORKSPACE_ASSIST', startIntent.current),
    onSuccess: (result) => {
      const value = result.payload.data
      setSession(value)
      setError('')
      queryClient.setQueryData(agentKeys.session(value.public_id), result)
    },
    onError: (cause) => setError(drawerErrorText(cause)),
  })
  const startSession = start.mutate

  useEffect(() => {
    if (!open || session || start.isPending || startAttempted.current) return
    startAttempted.current = true
    startSession()
  }, [open, session, start.isPending, startSession])

  const sessionQuery = useQuery({
    queryKey: agentKeys.session(session?.public_id ?? ''),
    queryFn: ({ signal }: { signal: AbortSignal }) => getAgentSession(session?.public_id ?? '', signal),
    enabled: Boolean(session),
    refetchInterval: streamState === 'polling' && open ? 5000 : false,
  })
  const effectiveSession = sessionQuery.data?.payload.data ?? session
  const messages = useQuery({
    queryKey: agentKeys.messages(session?.public_id ?? ''),
    queryFn: ({ signal }: { signal: AbortSignal }) => getAgentMessages(session?.public_id ?? '', signal),
    enabled: Boolean(session),
    refetchInterval: (query) => {
      const items = query.state.data?.payload.data ?? []
      return streamState === 'polling' && (open || hasPendingReply(items)) ? 2000 : false
    },
  })
  const messageItems = messages.data?.payload.data ?? []
  const assistantCount = messageItems.filter((item) => item.role === 'ASSISTANT').length
  const processing = start.isPending || hasPendingReply(messageItems)
  const unread = open ? 0 : Math.max(0, assistantCount - seenAssistantCount)

  useEffect(() => {
    if (open) setSeenAssistantCount(assistantCount)
  }, [assistantCount, open])

  useEffect(() => {
    onActivityChange?.({ unread, processing })
  }, [onActivityChange, processing, unread])

  useEffect(() => {
    if (!session) return undefined
    const sessionId = session.public_id
    const client = new PortalEventClient({
      onEvent: () => {
        void queryClient.invalidateQueries({ queryKey: agentKeys.messages(sessionId) })
        void queryClient.invalidateQueries({ queryKey: agentKeys.session(sessionId) })
      },
      onStateChange: (state) => setStreamState(state === 'live' ? 'live' : 'polling'),
      poll: async () => {
        await Promise.all([
          queryClient.refetchQueries({ queryKey: agentKeys.messages(sessionId), type: 'active' }),
          queryClient.refetchQueries({ queryKey: agentKeys.session(sessionId), type: 'active' }),
        ])
        return []
      },
    })
    client.start()
    return () => client.stop()
  }, [queryClient, session])

  useEffect(() => {
    if (!open) return undefined
    closeButtonRef.current?.focus()
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [onClose, open])

  const send = useMutation({
    mutationFn: (prompt: string) => sendAgentMessage(session?.public_id ?? '', prompt, new RequestIntent()),
    onSuccess: async (_result, prompt) => {
      if (body.trim() === prompt) setBody('')
      setError('')
      setNotice('Agent 正在处理。')
      await queryClient.invalidateQueries({ queryKey: agentKeys.messages(session?.public_id ?? '') })
    },
    onError: (cause) => setError(drawerErrorText(cause)),
  })

  const sendPrompt = (prompt: string) => {
    const value = prompt.trim()
    if (!value || send.isPending || effectiveSession?.status !== 'ACTIVE') return
    setError('')
    setNotice('')
    send.mutate(value)
  }

  const rate = async (message: AgentMessageData, rating: 'USEFUL' | 'NOT_USEFUL') => {
    setError('')
    try {
      await submitAgentFeedback(message.public_id, rating, new RequestIntent())
      setFeedback((current) => ({ ...current, [message.public_id]: rating }))
      setNotice('反馈已提交。')
    } catch (cause) {
      setError(drawerErrorText(cause))
    }
  }

  const decideTool = async (call: AgentToolCallData, decision: 'APPROVED' | 'REJECTED') => {
    if (!call.state || pendingToolCall) return
    setPendingToolCall(call.public_id)
    setError('')
    try {
      await decideAgentToolCall(call.public_id, decision, call.state.row_version, new RequestIntent())
      setNotice(decision === 'APPROVED' ? '已批准本次工具调用。' : '已拒绝本次工具调用。')
      await queryClient.invalidateQueries({ queryKey: agentKeys.messages(session?.public_id ?? '') })
    } catch (cause) {
      setError(drawerErrorText(cause))
    } finally {
      setPendingToolCall('')
    }
  }

  const retryStart = () => {
    startAttempted.current = true
    startIntent.current = new RequestIntent()
    setError('')
    startSession()
  }

  const sessionActive = !sessionQuery.isError && effectiveSession?.status === 'ACTIVE'
  return <aside className="task-agent-drawer" role="dialog" aria-modal="false" aria-labelledby="task-agent-title" hidden={!open}>
    <header className="task-agent-drawer__header">
      <div><Bot size={20} aria-hidden="true" /><h2 id="task-agent-title">实验助手</h2>{processing ? <span className="task-agent-drawer__processing"><LoaderCircle size={14} aria-hidden="true" />处理中</span> : null}</div>
      <button ref={closeButtonRef} className="task-agent-icon-button" type="button" aria-label="关闭 Agent 助手" title="关闭" onClick={onClose}><X size={19} aria-hidden="true" /></button>
    </header>
    <div className="task-agent-drawer__body">
      {start.isPending ? <RequestStateView state="loading" title="正在连接实验助手" /> : null}
      {start.isError && !session ? <RequestStateView state="error" title="实验助手暂不可用" message={error} onRetry={retryStart} /> : null}
      {session && sessionQuery.isError ? <RequestStateView state="error" title="Agent 会话状态不可用" message={drawerErrorText(sessionQuery.error)} onRetry={() => void sessionQuery.refetch()} /> : null}
      {effectiveSession && !sessionActive ? <RequestStateView state="empty" title="Agent 会话已结束" message="当前会话不可继续使用。" /> : null}
      {sessionActive ? <>
        <div className="task-agent-quick-prompts" aria-label="快捷问题">
          {quickPrompts.map((prompt) => <button key={prompt} type="button" onClick={() => sendPrompt(prompt)} disabled={send.isPending}>{prompt}</button>)}
        </div>
        <div className="task-agent-thread" aria-live="polite" aria-busy={processing}>
          {messages.isPending ? <RequestStateView state="loading" title="正在加载消息" /> : null}
          {messages.isError ? <RequestStateView state="error" title="消息暂不可用" message={drawerErrorText(messages.error)} onRetry={() => void messages.refetch()} /> : null}
          {!messages.isPending && !messages.isError && messageItems.length === 0 ? <p className="task-agent-thread__empty">暂无消息。</p> : null}
          {messageItems.map((item) => <article className={`task-agent-message task-agent-message--${item.role.toLowerCase()}`} key={item.public_id}>
            <div className="task-agent-message__meta"><strong>{item.role === 'ASSISTANT' ? 'Agent' : '你'}</strong><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></div>
            <p>{item.body}</p>
            {item.citations.filter((citation) => citation.accessible).length ? <div className="task-agent-citations"><strong>引用来源</strong><ul>{item.citations.filter((citation) => citation.accessible).map((citation) => <li key={citation.public_id}><span>{citation.title}</span><small>{citation.snippet}</small></li>)}</ul></div> : null}
            {(item.tool_calls ?? []).map((call) => <div className="task-agent-tool" key={call.public_id}>
              <div><strong>{call.tool_name}</strong><StatusBadge status={call.state?.status ?? 'UNKNOWN'} /></div>
              {call.state?.status === 'PENDING_APPROVAL' ? <div className="task-agent-tool__actions"><button className="text-button" type="button" disabled={!workspaceAvailable || pendingToolCall === call.public_id} onClick={() => void decideTool(call, 'APPROVED')}>批准本次</button><button className="text-button text-button--danger" type="button" disabled={pendingToolCall === call.public_id} onClick={() => void decideTool(call, 'REJECTED')}>拒绝</button></div> : null}
              {call.state?.status === 'PENDING_APPROVAL' && !workspaceAvailable ? <small>工作区会话不可用，不能批准工具调用。</small> : null}
            </div>)}
            {item.role === 'ASSISTANT' ? <div className="task-agent-feedback" aria-label="回答反馈">
              <button type="button" aria-label="有帮助" title="有帮助" className={feedback[item.public_id] === 'USEFUL' ? 'active' : ''} disabled={Boolean(feedback[item.public_id])} onClick={() => void rate(item, 'USEFUL')}><ThumbsUp size={15} aria-hidden="true" /></button>
              <button type="button" aria-label="需改进" title="需改进" className={feedback[item.public_id] === 'NOT_USEFUL' ? 'active' : ''} disabled={Boolean(feedback[item.public_id])} onClick={() => void rate(item, 'NOT_USEFUL')}><ThumbsDown size={15} aria-hidden="true" /></button>
            </div> : null}
          </article>)}
          {hasPendingReply(messageItems) ? <div className="task-agent-thinking" role="status"><LoaderCircle size={16} aria-hidden="true" />Agent 正在处理</div> : null}
        </div>
      </> : null}
    </div>
    {sessionActive ? <form className="task-agent-composer" onSubmit={(event) => { event.preventDefault(); sendPrompt(body) }}>
      <label htmlFor="task-agent-input">询问实验助手</label>
      <div><textarea id="task-agent-input" value={body} onChange={(event) => setBody(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendPrompt(body) } }} placeholder="输入问题" rows={3} /><button className="task-agent-send" type="submit" aria-label="发送消息" title="发送" disabled={!body.trim() || send.isPending}><Send size={18} aria-hidden="true" /></button></div>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {notice ? <p className="task-agent-notice" role="status">{notice}</p> : null}
    </form> : null}
  </aside>
}

export function AgentOrb({ taskId, workspaceAvailable }: { taskId: string; workspaceAvailable: boolean }) {
  const [open, setOpen] = useState(false)
  const [activity, setActivity] = useState({ unread: 0, processing: false })
  const orbRef = useRef<HTMLButtonElement>(null)
  const close = useCallback(() => { setOpen(false); orbRef.current?.focus() }, [])
  const updateActivity = useCallback((value: { unread: number; processing: boolean }) => setActivity(value), [])
  return <>
    <button ref={orbRef} className={`task-agent-orb${activity.processing ? ' task-agent-orb--processing' : ''}`} type="button" aria-label={open ? '隐藏 Agent 助手' : '打开 Agent 助手'} aria-expanded={open} aria-controls="task-agent-drawer" title="实验助手" onClick={() => setOpen((value) => !value)}>
      {activity.processing ? <LoaderCircle size={23} aria-hidden="true" /> : <Bot size={24} aria-hidden="true" />}
      {activity.unread ? <span className="task-agent-orb__badge" aria-label={`${activity.unread} 条未读消息`}>{Math.min(activity.unread, 9)}</span> : null}
    </button>
    <div id="task-agent-drawer"><TaskAgentDrawer taskId={taskId} open={open} workspaceAvailable={workspaceAvailable} onClose={close} onActivityChange={updateActivity} /></div>
  </>
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
