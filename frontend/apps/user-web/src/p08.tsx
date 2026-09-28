import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { FileText, Flag, History, Play, Save, Send } from 'lucide-react'
import {
  ApiError,
  RequestIntent,
  apiRequestWithMetadata,
  clearWorkspaceToken,
  completeTask,
  createWorkspaceSession,
  createWorkspaceCheckpoint,
  enterWorkspace,
  getTaskWorkbench,
  getWorkspaceExecutionRun,
  getWorkspaceCheckpoints,
  restoreWorkspaceCheckpoint,
  renewWorkspaceSession,
  runWorkspaceOperation,
  saveWorkspaceSnapshot,
  submitTaskReport,
  type ProvisioningJob,
  type ProvisioningStageEvent,
  type TaskData,
  type ApiResult,
  type WorkspaceCheckpointData,
  type WorkspaceCheckpointListData,
  type WorkspaceEnvelope,
  type WorkspaceOperationData,
  type WorkspaceSessionData,
} from '@edu/api-client'
import { PortalEventClient } from '@edu/event-client'
import { experimentKeys, workspaceKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge } from '@edu/ui'
import { AgentOrb } from './p12'

type QueuedDraft = { clientSeq: number; baseVersion: number; content: string }
type WorkspaceSessionResult = ApiResult<WorkspaceEnvelope<WorkspaceSessionData>>

const stageLabels: Record<string, string> = {
  QUOTA_CHECK: '配额检查',
  IMAGE_PREPARE: '准备镜像',
  CREATE: '创建环境',
  NETWORK_ATTACH: '连接网络',
  BOOT_PROBE: '启动探测',
  WORKSPACE_READY: '工作区就绪',
}

const iframeRenewWindowMs = 5 * 60 * 1000
const runningExecutionStatuses = new Set(['QUEUED', 'RUNNING'])

const executionStatusMessages: Record<string, string> = {
  QUEUED: '测试已排队，等待执行。',
  RUNNING: '正在执行公开测试。',
  PASSED: '测试通过。',
  FAILED: '测试未通过，请根据公开摘要检查实现。',
  TIMEOUT: '测试超时，请检查算法复杂度或阻塞操作。',
  RESOURCE_EXCEEDED: '测试超出资源限制，请降低资源占用。',
  REJECTED: '测试请求被拒绝，请保存最新快照后重试。',
}

const submissionBlockMessages: Record<string, string> = {
  TASK_STATE: '当前任务状态不允许提交。',
  TASK_BLOCKED: '任务仍有阻断条件。',
  WORKSPACE_SNAPSHOT_REQUIRED: '请先保存工作区快照。',
  REPORT_DRAFT_REQUIRED: '请先填写并保存报告草稿。',
  REPORT_DRAFT_STALE: '工作区已更新，请重新保存报告草稿。',
  REPORT_ATTACHMENTS_SCANNING: '报告附件仍在安全扫描。',
  REPORT_ATTACHMENTS_NOT_READY: '报告附件尚未通过安全扫描。',
  TEST_NOT_FINISHED: '请先完成当前快照的测试。',
  TEST_SNAPSHOT_STALE: '测试结果不是基于当前快照，请重新运行测试。',
}

function etagVersion(etag: string | null, fallback: number): number {
  const parsed = Number(etag?.replaceAll('"', ''))
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback
}

function latestProvisioningStages(stages: ProvisioningStageEvent[]): ProvisioningStageEvent[] {
  return Array.from(new Map(stages.map((stage) => [stage.stage, stage])).values())
}

function cacheWorkspaceVersion(
  queryClient: QueryClient,
  taskId: string,
  currentVersion: number,
  latestClientSeq: number,
  rowVersion: number,
): void {
  queryClient.setQueryData<WorkspaceSessionResult>(workspaceKeys.session(taskId), (current) => {
    if (!current) return current
    return {
      ...current,
      payload: {
        ...current.payload,
        data: {
          ...current.payload.data,
          current_version: currentVersion,
          latest_client_seq: latestClientSeq,
          row_version: rowVersion,
        },
      },
    }
  })
}

function openQueue(taskId: string): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(`p08-workspace-drafts-${taskId}`, 1)
    request.onupgradeneeded = () => request.result.createObjectStore('queue', { keyPath: 'clientSeq' })
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

async function queueDraft(taskId: string, draft: QueuedDraft): Promise<void> {
  try {
    const db = await openQueue(taskId)
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction('queue', 'readwrite')
      tx.objectStore('queue').put(draft)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
    })
    db.close()
  } catch { /* IndexedDB is optional; the visible draft remains in React state. */ }
}

async function queuedDrafts(taskId: string): Promise<QueuedDraft[]> {
  try {
    const db = await openQueue(taskId)
    const values = await new Promise<QueuedDraft[]>((resolve, reject) => {
      const tx = db.transaction('queue', 'readonly')
      const request = tx.objectStore('queue').getAll()
      request.onsuccess = () => resolve(request.result as QueuedDraft[])
      request.onerror = () => reject(request.error)
    })
    db.close()
    return values.sort((left, right) => left.clientSeq - right.clientSeq)
  } catch { return [] }
}

async function removeQueuedDraft(taskId: string, clientSeq: number): Promise<void> {
  try {
    const db = await openQueue(taskId)
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction('queue', 'readwrite')
      tx.objectStore('queue').delete(clientSeq)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
    })
    db.close()
  } catch { /* IndexedDB is optional. */ }
}

function messageFor(error: unknown): string {
  if (!(error instanceof ApiError)) return '工作区暂时不可用，请稍后重试。'
  const code = error.payload.error.code
  if (code === 'WORKSPACE_SESSION_EXPIRED') return '工作区会话已过期，请重新进入实验。'
  if (code === 'WORKSPACE_SESSION_REVOKED' || code === 'WORKSPACE_SESSION_INVALID') return '工作区会话已失效，请重新进入实验。'
  if (code === 'ROW_VERSION_CONFLICT') return '任务版本已变化，请刷新后重新确认提交。'
  if (code === 'AUTOSAVE_CONFLICT' || error.status === 412) return '服务端版本冲突：可保留服务端、保留本地，或创建新版本。'
  if (code === 'AUTOSAVE_SEQ_STALE') return '本地保存序号已过期，请刷新后继续。'
  if (code === 'REPORT_ATTACHMENT_NOT_READY') return '报告附件尚未通过安全扫描，请刷新状态后重试。'
  if (code === 'REPORT_EXECUTION_NOT_READY') return '请先完成当前工作区快照的测试。'
  if (code === 'REPORT_EXECUTION_CONFLICT') return '测试结果与当前工作区快照不一致，请刷新并重新运行测试。'
  if (code === 'REPORT_SNAPSHOT_CONFLICT') return '工作区内容已变化，请刷新并重新保存报告草稿。'
  if (code === 'WORKSPACE_CAPABILITY_DENIED') return '当前工作区未启用此操作能力，请联系课程教师。'
  if (error.status === 409) return '工作区状态已变化，请刷新后重试。'
  if (error.status === 429) return '工作区请求过于频繁，请稍后重试。'
  if (error.status === 503) return '工作区服务暂时不可用，请稍后重试。'
  if (error.status === 401) return '当前登录或工作区会话已失效，请重新进入实验。'
  if (error.status === 403) return '当前账号无权访问该工作区。'
  return error.payload.error.message
}

const runtimeTabLabels: Record<string, string> = {
  webide: 'WebIDE',
  notebook: 'Notebook',
  terminal: 'Terminal',
  preview: 'Preview',
}

type ContentTab = 'content' | 'template' | 'tests'

function publicText(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (!value || typeof value !== 'object') return ''
  const record = value as Record<string, unknown>
  for (const key of ['title', 'label', 'name', 'description', 'text', 'summary']) {
    if (typeof record[key] === 'string' && record[key]) return record[key] as string
  }
  try { return JSON.stringify(value) } catch { return '' }
}

function executionMessage(value: { status: string; result_summary?: string; error_code?: string }): string {
  const statusMessage = executionStatusMessages[value.status] || '测试状态已更新。'
  const detail = value.result_summary || value.error_code || ''
  return detail && !statusMessage.includes(detail) ? `${statusMessage} ${detail}` : statusMessage
}

function submissionBlockMessage(value: unknown): string {
  if (!value || typeof value !== 'object') return ''
  const code = String((value as Record<string, unknown>).code ?? '')
  return submissionBlockMessages[code] ?? '当前条件不允许提交，请刷新任务状态。'
}

function PublicList({ items, empty = '暂无公开内容。' }: { items: unknown[]; empty?: string }) {
  const values = items.map(publicText).filter(Boolean)
  return values.length ? <ul>{values.map((value, index) => <li key={`${value}-${index}`}>{value}</li>)}</ul> : <p className="muted">{empty}</p>
}

function useWorkspace(taskId: string) {
  const [streamState, setStreamState] = useState<'live' | 'polling'>('polling')
  const task = useQuery({
    queryKey: experimentKeys.task(taskId),
    queryFn: () => apiRequestWithMetadata<WorkspaceEnvelope<TaskData>>(`/api/v2/tasks/${encodeURIComponent(taskId)}`),
    refetchInterval: (query) => {
      const status = query.state.data?.payload.data.status
      return streamState === 'polling' && status === 'PROVISIONING' ? 3000 : false
    },
  })
  const queryClient = useQueryClient()
  const session = useQuery<WorkspaceSessionResult>({
    queryKey: workspaceKeys.session(taskId),
    queryFn: () => Promise.reject(new Error('工作区 Session 尚未创建')),
    retry: false,
    enabled: false,
  })
  const intent = useRef<RequestIntent | null>(null)
  const attempted = useRef('')
  const renewing = useRef(false)
  const renewIntent = useRef<RequestIntent | null>(null)
  const blockSession = useCallback((reason: unknown, failedToken?: string) => {
    if (!(reason instanceof ApiError) || (reason.status !== 401 && !reason.payload.error.code.startsWith('WORKSPACE_SESSION_'))) return
    const currentToken = queryClient.getQueryData<WorkspaceSessionResult>(workspaceKeys.session(taskId))?.payload.data.workspace_token
    if (failedToken && currentToken && failedToken !== currentToken) return
    clearWorkspaceToken()
    queryClient.setQueryData<WorkspaceSessionResult>(workspaceKeys.session(taskId), (current) => current ? {
      ...current,
      payload: { ...current.payload, data: { ...current.payload.data, status: reason.payload.error.code === 'WORKSPACE_SESSION_REVOKED' ? 'REVOKED' : 'EXPIRED', workspace_token: undefined } },
    } : current)
  }, [queryClient, taskId])
  const issue = useMutation({
    mutationFn: async (item: TaskData) => {
      intent.current ??= new RequestIntent()
      if (item.status === 'READY') return enterWorkspace(taskId, `"${item.row_version}"`, intent.current)
      return createWorkspaceSession(taskId, intent.current)
    },
    onSuccess: (result) => {
      const data = 'session' in result.payload.data ? result.payload.data.session : result.payload.data
      queryClient.setQueryData<WorkspaceSessionResult>(workspaceKeys.session(taskId), {
        ...result,
        payload: { ...result.payload, data },
      })
      if ('session' in result.payload.data) {
        queryClient.setQueryData<ApiResult<WorkspaceEnvelope<TaskData>>>(experimentKeys.task(taskId), {
          etag: result.etag,
          traceId: result.traceId,
          payload: { ...result.payload, data: result.payload.data.task },
        })
      }
    },
  })
  const issueMutate = issue.mutate
  const item = task.data?.payload.data
  useEffect(() => {
    if (!item || session.data || issue.isPending) return
    if (!['READY', 'IN_PROGRESS', 'REPORT_DRAFT'].includes(item.status)) return
    const attemptKey = `${item.status}:${item.row_version}`
    if (attempted.current === attemptKey) return
    attempted.current = attemptKey
    issueMutate(item)
  }, [item, issue.isPending, session.data, issueMutate])
  useEffect(() => {
    if (item && !['READY', 'IN_PROGRESS', 'REPORT_DRAFT'].includes(item.status)) clearWorkspaceToken()
  }, [item])
  useEffect(() => {
    if (!session.data) return undefined
    const current = session.data.payload.data
    if (current.status !== 'ACTIVE' || !current.workspace_token) {
      clearWorkspaceToken()
      return undefined
    }
    const ttl = Math.max(1, new Date(current.expires_at).getTime() - Date.now())
    const renewAt = Math.max(1000, Math.min(ttl * 0.6, ttl - 1000))
    const renewWindow = Math.max(60_000, ttl * 0.5)
    let timer: number | undefined
    const renew = () => {
      if (new Date(current.expires_at).getTime() - Date.now() > renewWindow) return
      if (renewing.current) return
      renewing.current = true
      renewIntent.current ??= new RequestIntent()
      void renewWorkspaceSession(current.public_id, current.workspace_token, renewIntent.current).then((result) => {
        renewIntent.current = null
        queryClient.setQueryData<WorkspaceSessionResult>(workspaceKeys.session(taskId), result)
      }).catch((reason) => {
        const sessionFailure = reason instanceof ApiError && (reason.status === 401 || reason.payload.error.code.startsWith('WORKSPACE_SESSION_'))
        blockSession(reason, current.workspace_token)
        if (!sessionFailure) timer = window.setTimeout(renew, 5000)
      }).finally(() => { renewing.current = false })
    }
    timer = window.setTimeout(renew, renewAt)
    window.addEventListener('online', renew)
    window.addEventListener('focus', renew)
    return () => { if (timer) window.clearTimeout(timer); window.removeEventListener('online', renew); window.removeEventListener('focus', renew) }
  }, [blockSession, queryClient, session.data, taskId])
  useEffect(() => {
    if (!taskId) return undefined
    const client = new PortalEventClient({
      url: `/api/v2/events/stream?channel=task:${encodeURIComponent(taskId)}`,
      onEvent: () => {
        void queryClient.invalidateQueries({ queryKey: experimentKeys.task(taskId) })
        void queryClient.invalidateQueries({ queryKey: experimentKeys.provisioningJob(taskId) })
        void queryClient.invalidateQueries({ queryKey: workspaceKeys.session(taskId) })
      },
      onStateChange: (state) => setStreamState(state === 'live' ? 'live' : 'polling'),
      poll: async () => {
        await Promise.all([
          queryClient.refetchQueries({ queryKey: experimentKeys.task(taskId), type: 'active' }),
          queryClient.refetchQueries({ queryKey: experimentKeys.provisioningJob(taskId), type: 'active' }),
        ])
        return []
      },
    })
    client.start()
    return () => client.stop()
  }, [queryClient, taskId])
  const retry = () => {
    if (!item || !['READY', 'IN_PROGRESS', 'REPORT_DRAFT'].includes(item.status)) return
    attempted.current = ''
    issueMutate(item)
  }
  const renewNow = () => {
    const current = session.data?.payload.data
    if (!current || current.status !== 'ACTIVE' || !current.workspace_token || renewing.current) return
    if (new Date(current.expires_at).getTime() - Date.now() > iframeRenewWindowMs) return
    renewing.current = true
    renewIntent.current ??= new RequestIntent()
    void renewWorkspaceSession(current.public_id, current.workspace_token, renewIntent.current).then((result) => {
      renewIntent.current = null
      queryClient.setQueryData<WorkspaceSessionResult>(workspaceKeys.session(taskId), result)
    }).catch((reason) => { blockSession(reason, current.workspace_token) }).finally(() => { renewing.current = false })
  }
  return {
    ...session,
    task,
    issue,
    data: session.data,
    isPending: task.isPending || issue.isPending,
    isError: task.isError || session.isError || issue.isError,
    error: task.error ?? session.error ?? issue.error,
    refetch: () => task.refetch(),
    retry,
    renewNow,
    blockSession,
    streamState,
  }
}

export function WorkspaceLabPage() {
  const { taskId = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const task = useQuery({ queryKey: experimentKeys.task(taskId), queryFn: () => apiRequestWithMetadata<WorkspaceEnvelope<TaskData>>(`/api/v2/tasks/${encodeURIComponent(taskId)}`) })
  const workbench = useQuery({
    queryKey: workspaceKeys.workbench(taskId),
    queryFn: ({ signal }: { signal: AbortSignal }) => getTaskWorkbench(taskId, signal),
    enabled: Boolean(taskId),
  })
  const workspace = useWorkspace(taskId)
  const provisioning = useQuery({
    queryKey: experimentKeys.provisioningJob(taskId),
    queryFn: () => apiRequestWithMetadata<WorkspaceEnvelope<ProvisioningJob>>(`/api/v2/tasks/${encodeURIComponent(taskId)}/provisioning-job`),
    refetchInterval: (query) => {
      if (workspace.streamState !== 'polling') return false
      const status = query.state.data?.payload.data.status
      return status === 'QUEUED' || status === 'RUNNING' || status === 'RETRY' ? 3000 : false
    },
  })
  const [draftContent, setDraftContent] = useState('// Workspace draft\n')
  const [contentTab, setContentTab] = useState<ContentTab>('content')
  const [runtimeTab, setRuntimeTab] = useState('webide')
  const [saveState, setSaveState] = useState<'saved' | 'dirty' | 'saving' | 'offline' | 'conflict'>('saved')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [seq, setSeq] = useState(0)
  const [version, setVersion] = useState(0)
  const [executionId, setExecutionId] = useState('')
  const [checking, setChecking] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const flushing = useRef(false)
  const runningCheck = useRef(false)
  const submittingRequest = useRef(false)
  const checkIntent = useRef<RequestIntent | null>(null)
  const submitIntent = useRef<RequestIntent | null>(null)
  const latest = useRef({ content: draftContent, seq, version })
  latest.current = { content: draftContent, seq, version }
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (latest.current.content && saveState === 'dirty') void save(false)
    }, 10_000)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saveState])
  const session = workspace.data?.payload.data as unknown as WorkspaceSessionData | undefined
  const blockWorkspaceSession = workspace.blockSession
  const execution = useQuery({
    queryKey: workspaceKeys.execution(taskId, executionId),
    queryFn: () => getWorkspaceExecutionRun(taskId, executionId, session?.workspace_token),
    enabled: Boolean(executionId && session?.workspace_token),
    refetchInterval: (query) => runningExecutionStatuses.has(query.state.data?.payload.data.status ?? '') ? 750 : false,
  })
  useEffect(() => {
    if (!session) return
    setSeq(session.latest_client_seq)
    setVersion(session.current_version)
    const first = Object.keys(session.workspace_urls ?? {}).find((key) => runtimeTabLabels[key])
    if (first && !session.workspace_urls[runtimeTab]) setRuntimeTab(first)
  }, [runtimeTab, session])
  const flushQueue = async () => {
    if (!session || flushing.current || !navigator.onLine) return
    flushing.current = true
    try {
      for (const draft of await queuedDrafts(taskId)) {
        try {
          const result = await saveWorkspaceSnapshot(taskId, { clientSeq: draft.clientSeq, baseVersion: draft.baseVersion, file: new Blob([draft.content], { type: 'text/plain' }) }, session.workspace_token)
          const snapshot = result.payload.data.snapshot
          await removeQueuedDraft(taskId, draft.clientSeq)
          cacheWorkspaceVersion(queryClient, taskId, snapshot.version_no, snapshot.client_seq, etagVersion(result.etag, session.row_version + 1))
          setSeq(snapshot.client_seq); setVersion(snapshot.version_no); setSaveState('saved')
        } catch (reason) {
          workspace.blockSession(reason, session.workspace_token)
          setSaveState(reason instanceof ApiError && reason.status === 412 ? 'conflict' : 'offline')
          setError(messageFor(reason))
          break
        }
      }
    } finally { flushing.current = false }
  }
  useEffect(() => {
    if (!session) return undefined
    const onOnline = () => { void flushQueue() }
    window.addEventListener('online', onOnline)
    void flushQueue()
    return () => window.removeEventListener('online', onOnline)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.public_id, session?.workspace_token, taskId])
  useEffect(() => {
    const run = execution.data?.payload.data
    if (!run || runningExecutionStatuses.has(run.status)) return
    setNotice(executionMessage(run))
    void queryClient.invalidateQueries({ queryKey: workspaceKeys.workbench(taskId) })
  }, [execution.data, queryClient, taskId])
  useEffect(() => {
    if (!execution.isError || !session) return
    blockWorkspaceSession(execution.error, session.workspace_token)
    setError(messageFor(execution.error))
  }, [blockWorkspaceSession, execution.error, execution.isError, session])
  const save = async (manual = true): Promise<boolean> => {
    if (!session) return false
    const nextSeq = latest.current.seq + 1
    setSaveState('saving'); setError('')
    try {
      const result = await saveWorkspaceSnapshot(taskId, { clientSeq: nextSeq, baseVersion: latest.current.version, file: new Blob([latest.current.content], { type: 'text/plain' }) }, session.workspace_token)
      const snapshot = result.payload.data.snapshot
      cacheWorkspaceVersion(queryClient, taskId, snapshot.version_no, snapshot.client_seq, etagVersion(result.etag, session.row_version + 1))
      setSeq(snapshot.client_seq); setVersion(snapshot.version_no); setSaveState('saved')
      if (manual) setNotice('已保存到工作区对象存储。')
      await queryClient.invalidateQueries({ queryKey: workspaceKeys.workbench(taskId) })
      return true
    } catch (reason) {
      workspace.blockSession(reason, session.workspace_token)
      if (!navigator.onLine) { await queueDraft(taskId, { clientSeq: nextSeq, baseVersion: latest.current.version, content: latest.current.content }); setSaveState('offline') }
      else setSaveState(reason instanceof ApiError && reason.status === 412 ? 'conflict' : 'dirty')
      setError(messageFor(reason))
      return false
    }
  }
  const runCheck = async () => {
    if (!session || runningCheck.current) return
    runningCheck.current = true
    setChecking(true)
    setError(''); setNotice('')
    checkIntent.current ??= new RequestIntent()
    try {
      const result = await runWorkspaceOperation(
        session.public_id,
        'RUN_CHECK',
        { source: 'user-web' },
        session.workspace_token,
        checkIntent.current,
      )
      const operationData = result.payload.data
      const nextExecutionId = operationData.execution_run_id ?? operationData.payload.execution_run_id
      if (typeof nextExecutionId !== 'string' || !nextExecutionId) throw new Error('EXECUTION_ID_MISSING')
      checkIntent.current = null
      setExecutionId(nextExecutionId)
      setNotice(operationData.result_summary || executionStatusMessages.QUEUED || '测试已排队，等待执行。')
    } catch (reason) {
      workspace.blockSession(reason, session.workspace_token)
      if (reason instanceof ApiError) checkIntent.current = null
      setError(messageFor(reason))
    } finally {
      runningCheck.current = false
      setChecking(false)
    }
  }
  const item = task.data?.payload.data
  const submitExperiment = async () => {
    if (!item || submitting || submittingRequest.current || saveState !== 'saved') return
    const submission = workbench.data?.payload.data.submission
    if (!submission?.can_submit) return
    const label = item.report_required ? '当前报告和工作区快照' : '当前工作区快照'
    if (!window.confirm(`确认提交${label}？提交后将进入审核流程。`)) return
    submittingRequest.current = true
    setSubmitting(true); setError(''); setNotice('')
    submitIntent.current ??= new RequestIntent()
    const rowVersion = workbench.data?.payload.data.task.row_version ?? item.row_version
    try {
      if (item.report_required) {
        await submitTaskReport(taskId, `"${rowVersion}"`, submitIntent.current)
      } else {
        await completeTask(taskId, `"${rowVersion}"`, submitIntent.current)
      }
      submitIntent.current = null
      setNotice(item.report_required ? '实验报告已提交，任务进入审核流程。' : '工作区成果已提交，任务进入审核流程。')
      await Promise.all([
        task.refetch(),
        workbench.refetch(),
        queryClient.invalidateQueries({ queryKey: experimentKeys.dashboard() }),
        queryClient.invalidateQueries({ queryKey: experimentKeys.myTasks() }),
      ])
    } catch (reason) {
      if (reason instanceof ApiError) submitIntent.current = null
      setError(messageFor(reason))
    } finally {
      submittingRequest.current = false
      setSubmitting(false)
    }
  }
  if (task.isPending) return <RequestStateView state="loading" />
  if (task.isError || !item) return <RequestStateView state={task.error instanceof ApiError && task.error.status === 403 ? 'forbidden' : 'error'} message={messageFor(task.error)} onRetry={() => void task.refetch()} />
  const job = provisioning.data?.payload.data
  if (item.status === 'PROVISIONING') {
    const stages = latestProvisioningStages(job?.stages ?? [])
    const completed = stages.filter((stage) => stage.status === 'PASSED' || stage.status === 'SKIPPED').length
    const progress = job ? Math.round((completed / Object.keys(stageLabels).length) * 100) : item.progress
    return <section className="workspace-page"><PageHeader eyebrow="ENVIRONMENT" title={item.title} description="实验环境正在按运行时阶段装载。" /><RequestStateView state="loading" title="环境加载中" message={`${job?.current_stage ? (stageLabels[job.current_stage] ?? job.current_stage) : '准备中'} · ${progress}% · ${workspace.streamState === 'live' ? '实时事件' : '轮询同步'}`} /><div className="data-table-wrap"><table className="data-table"><thead><tr><th>阶段</th><th>状态</th><th>尝试</th><th>错误</th></tr></thead><tbody>{(stages.length ? stages : Object.keys(stageLabels).map((stage) => ({ stage, status: 'PENDING', attempt_no: null, error_code: '' }))).map((stage) => <tr key={stage.stage}><td>{stageLabels[stage.stage] ?? stage.stage}</td><td><StatusBadge status={stage.status} /></td><td>{stage.attempt_no ?? '-'}</td><td>{stage.error_code || '-'}</td></tr>)}</tbody></table></div></section>
  }
  if (item.status === 'FAILED') {
    const failure = job?.failure ?? item.current_failure
    return <section className="workspace-page"><PageHeader eyebrow="ENVIRONMENT" title={item.title} description="环境装载未完成，当前不会签发工作区票据。" /><RequestStateView state="error" title="环境加载失败" message={String((failure as Record<string, unknown> | null)?.message ?? (failure as Record<string, unknown> | null)?.error_code ?? '请返回任务页面重试。')} traceId={job?.trace_id} onRetry={() => window.location.assign(`/tasks/${taskId}`)} /></section>
  }
  if (!['READY', 'IN_PROGRESS', 'REPORT_DRAFT'].includes(item.status)) {
    return <section className="workspace-page"><PageHeader eyebrow="EXPERIMENT LAB" title={item.title} description="当前任务状态不允许创建新的工作区 Session。" /><RequestStateView state="empty" title={item.status === 'ASSIGNED' ? '请先开始实验' : item.status === 'UNDER_REVIEW' ? '实验已提交' : '工作区已归档'} message={item.status === 'ASSIGNED' ? '返回任务详情页开始环境装载。' : item.status === 'UNDER_REVIEW' ? '当前成果正在审核，工作区已切换为只读结果流程。' : '任务已结束或被取消，当前仅可查看结果。'} onRetry={() => window.location.assign(`/tasks/${taskId}`)} /></section>
  }
  if (workspace.isPending || workspace.issue.isPending) return <RequestStateView state="loading" title="正在进入工作区" message="正在创建或恢复当前任务的唯一有效 Session。" />
  if (workspace.isError || !session) return <RequestStateView state={workspace.error instanceof ApiError && workspace.error.status === 403 ? 'forbidden' : 'error'} message={messageFor(workspace.error)} onRetry={workspace.retry} />
  if (session.status !== 'ACTIVE' || !session.workspace_token) return <RequestStateView state="error" title="工作区会话已失效" message="当前 Session 已过期或被撤销，请重新进入实验。" onRetry={workspace.retry} />
  const runtimeTabs = Object.keys(runtimeTabLabels).filter((key) => session.capabilities[key] !== false && (Boolean(session.workspace_urls?.[key]) || session.capabilities[key] === true))
  const activeUrl = session.workspace_urls?.[runtimeTab]
  const workbenchData = workbench.data?.payload.data
  const recentExecution = execution.data?.payload.data ?? workbenchData?.tests.recent_execution
  const workbenchContent = workbenchData?.content
  const template = workbenchData?.template
  const tests = workbenchData?.tests
  const executionRunning = checking || runningExecutionStatuses.has(recentExecution?.status ?? '')
  const testBlocked = saveState !== 'saved'
    ? '请先保存当前工作区内容。'
    : (version || session.current_version) === 0
      ? '请先创建工作区快照。'
      : ''
  const submissionBlocked = saveState !== 'saved'
    ? '请先保存当前工作区内容。'
    : workbench.isPending
      ? '正在同步提交条件。'
      : workbench.isError
        ? '提交条件暂不可用，请刷新后重试。'
        : submissionBlockMessage(workbenchData?.submission.blocked_reason)
  const canSubmit = !submitting && !submissionBlocked && workbenchData?.submission.can_submit === true
  const contentTabs: Array<{ id: ContentTab; label: string }> = [
    { id: 'content', label: '实验内容' },
    { id: 'template', label: '实验模板' },
    { id: 'tests', label: '测试说明' },
  ]
  const contentPanel = workbench.isPending ? <RequestStateView state="loading" title="正在加载实验资料" /> : workbench.isError ? <RequestStateView state="error" title="实验资料暂不可用" message={messageFor(workbench.error)} onRetry={() => void workbench.refetch()} /> : contentTab === 'content' ? <>
    <h3>实验内容</h3>
    <p>{workbenchContent?.description || workbenchData?.task.description || '暂无实验说明。'}</p>
    <h4>实验目标</h4>
    <PublicList items={workbenchContent?.objectives ?? []} />
    <h4>实验步骤</h4>
    <PublicList items={workbenchContent?.steps ?? []} />
    <h4>约束与交付物</h4>
    <PublicList items={[...(workbenchContent?.constraints ?? []), ...(workbenchContent?.deliverables ?? [])]} />
  </> : contentTab === 'template' ? <>
    <h3>{template?.name || item.template_name}</h3>
    <dl>
      <dt>版本</dt><dd>{template?.version_no ? `v${template.version_no}` : '当前发布版本'}</dd>
      <dt>工作区能力</dt><dd>{Object.entries(template?.workspace_capabilities ?? session.capabilities).filter(([, enabled]) => Boolean(enabled)).map(([key]) => runtimeTabLabels[key] ?? key).join('、') || '未声明'}</dd>
      <dt>依赖</dt><dd>{template?.dependencies?.length ? template.dependencies.map(publicText).filter(Boolean).join('、') : '无额外依赖'}</dd>
      <dt>实验手册</dt><dd>{template?.manual_asset_id ? '已提供，需通过授权下载' : '未提供'}</dd>
      <dt>起始文件</dt><dd>{template?.starter_asset_id ? '已提供，需通过授权下载' : '未提供'}</dd>
    </dl>
    <p className="muted">模板资产不会直接暴露对象存储地址。</p>
  </> : <>
    <h3>公开测试</h3>
    <p>公开用例 {tests?.public_count ?? 0} 个；隐藏测试和判题细节不会在工作台展示。</p>
    {tests?.summary?.length ? <ul>{tests.summary.map((test, index) => { const summary = test.summary && typeof test.summary === 'object' ? test.summary as Record<string, unknown> : {}; const title = publicText(summary.title ?? summary.label ?? `公开用例 ${index + 1}`); const details = [summary.description, summary.input_format, summary.pass_condition].map(publicText).filter(Boolean); return <li key={`${test.position}-${index}`}><strong>{title}</strong>{details.length ? <small>{details.join('；')}</small> : null}</li> })}</ul> : <p className="muted">暂无公开用例说明。</p>}
  </>
  return <section className="workspace-page workspace-page--immersive workspace-lab">
    <PageHeader eyebrow="EXPERIMENT LAB" title={item?.title ?? '工作区'} description="受控实验工作区；快照和操作均可审计回放。" />
    {notice ? <p className="notice" role="status">{notice}</p> : null}{error ? <p className="form-error" role="alert">{error}</p> : null}
    <div className="workspace-lab__layout">
      <aside className="workspace-lab__content-pane" aria-label="实验资料">
        <div className="workspace-lab__pane-header"><h2>实验资料</h2><p>公开内容、模板和测试规则</p></div>
        <div className="workspace-lab__content-tabs" role="tablist" aria-label="实验资料分类">
          {contentTabs.map((tab) => <button key={tab.id} id={`content-tab-${tab.id}`} role="tab" aria-selected={contentTab === tab.id} aria-controls={contentTab === tab.id ? `content-panel-${tab.id}` : undefined} className={contentTab === tab.id ? 'workspace-tab active' : 'workspace-tab'} onClick={() => setContentTab(tab.id)}>{tab.label}</button>)}
        </div>
        <div id={`content-panel-${contentTab}`} className="workspace-lab__content-body" role="tabpanel" aria-labelledby={`content-tab-${contentTab}`}>{contentPanel}</div>
      </aside>
      <main className="workspace-lab__runtime-pane" aria-label="运行工作区">
        <div className="workspace-lab__runtime-tabs" role="tablist" aria-label="工作区能力">
          {runtimeTabs.map((tab) => <button key={tab} id={`runtime-tab-${tab}`} role="tab" aria-selected={runtimeTab === tab} aria-controls={runtimeTab === tab ? `runtime-panel-${tab}` : undefined} className={runtimeTab === tab ? 'workspace-tab active' : 'workspace-tab'} onClick={() => setRuntimeTab(tab)}>{runtimeTabLabels[tab]}</button>)}
        </div>
        <div id={`runtime-panel-${runtimeTab}`} className="workspace-lab__runtime-surface" role="tabpanel" aria-labelledby={`runtime-tab-${runtimeTab}`}>
          <div className="workspace-lab__runtime-heading"><h2>{runtimeTab === 'webide' ? 'IDE / 内容' : runtimeTabLabels[runtimeTab] ?? '工作区'}</h2><span>会话由工作区网关隔离</span></div>
          <div className="workspace-lab__frames">
            {runtimeTabs.map((tab) => session.workspace_urls?.[tab] ? <iframe key={tab} className="workspace-frame" hidden={runtimeTab !== tab} title={`${runtimeTabLabels[tab]} 工作区`} src={session.workspace_urls[tab]} onLoad={workspace.renewNow} allow="clipboard-read; clipboard-write" /> : null)}
            {!activeUrl ? <RequestStateView state="empty" title="能力未就绪" message="当前模板未声明此工作区能力，暂不加载 iframe。" /> : null}
          </div>
          {runtimeTab === 'webide' ? <div className="workspace-lab__draft"><h3>实验草稿</h3><textarea aria-label="实验内容" value={draftContent} onChange={(event) => { setDraftContent(event.target.value); setSaveState('dirty') }} rows={10} /></div> : null}
        </div>
      </main>
    </div>
    <div className="workspace-lab__footer" role="region" aria-label="实验操作">
      <div className="workspace-lab__footer-status">
        <span>连接 <StatusBadge status={session.status} /></span>
        <span>保存 <strong>{saveState === 'saved' ? '已保存' : saveState === 'saving' ? '保存中' : saveState === 'offline' ? '待同步' : saveState === 'conflict' ? '版本冲突' : '有未保存内容'}</strong></span>
        <span>版本 <strong>v{version || session.current_version}</strong> / 序号 <strong>{seq || session.latest_client_seq}</strong></span>
        <span className="workspace-lab__footer-result">测试 {recentExecution ? <><StatusBadge status={recentExecution.status} /><small>{executionMessage(recentExecution)}</small></> : <strong>尚未运行</strong>}<button className="workspace-lab__test-link" onClick={() => setContentTab('tests')}>查看 {tests?.public_count ?? 0} 个公开用例</button></span>
        {saveState === 'conflict' ? <div className="conflict-actions" role="group" aria-label="版本冲突处理"><span>版本冲突：</span><button className="text-button" onClick={() => { setSaveState('saved'); setError(''); setNotice('已保留服务端版本；本地草稿仍保留在当前页面。') }}>保留服务端</button><button className="text-button" onClick={() => { setVersion(session.current_version); setSaveState('dirty'); setError(''); setNotice('已保留本地内容，可再次保存。') }}>保留本地</button></div> : null}
        {submissionBlocked ? <span className="workspace-lab__submission-note">提交条件：{submissionBlocked}</span> : null}
      </div>
      <div className="workspace-lab__footer-actions">
        <button className="icon-button" title="检查点" aria-label="检查点" onClick={() => navigate(`/tasks/${taskId}/checkpoints`)}><Flag size={18} aria-hidden="true" /></button>
        <button className="icon-button" title="回放" aria-label="回放" onClick={() => navigate(`/tasks/${taskId}/replay`)}><History size={18} aria-hidden="true" /></button>
        {item.report_required ? <button className="text-button" onClick={() => navigate(`/tasks/${taskId}/report`)}><FileText size={16} aria-hidden="true" /> 编辑报告</button> : null}
        <button className="text-button" disabled={session.capabilities.run_check === false || executionRunning || Boolean(testBlocked)} title={testBlocked || undefined} onClick={() => void runCheck()}><Play size={16} aria-hidden="true" /> {executionRunning ? '测试中' : '运行测试'}</button>
        <button className="text-button" disabled={saveState === 'saving' || submitting} onClick={() => void save()}><Save size={16} aria-hidden="true" /> {saveState === 'saving' ? '保存中' : '保存'}</button>
        <button className="primary-button" disabled={!canSubmit} title={submissionBlocked || undefined} onClick={() => void submitExperiment()}><Send size={16} aria-hidden="true" /> {submitting ? '提交中' : '提交实验'}</button>
      </div>
    </div>
    <div className="workspace-lab__agent-anchor" data-agent-mount="workspace">
      <AgentOrb taskId={taskId} workspaceAvailable={session.status === 'ACTIVE' && Boolean(session.workspace_token)} />
    </div>
  </section>
}

export function WorkspaceCheckpointsPage() {
  const { taskId = '' } = useParams(); const [name, setName] = useState(''); const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const queryClient = useQueryClient(); const session = useWorkspace(taskId); const item = session.data?.payload.data as unknown as WorkspaceSessionData | undefined
  const task = session.task.data?.payload.data
  const query = useQuery({ queryKey: workspaceKeys.checkpoints(taskId), queryFn: () => getWorkspaceCheckpoints(taskId), enabled: Boolean(item) })
  const create = async () => { if (!item || item.status !== 'ACTIVE' || !item.workspace_token) return; try { await createWorkspaceCheckpoint(taskId, name, item.workspace_token); setName(''); setNotice('检查点已创建。'); await query.refetch() } catch (reason) { session.blockSession(reason, item.workspace_token); setError(messageFor(reason)) } }
  const restore = async (checkpoint: WorkspaceCheckpointData) => { if (!item || item.status !== 'ACTIVE' || !item.workspace_token || !query.data) return; try { const result = await restoreWorkspaceCheckpoint(taskId, checkpoint.public_id, query.data.payload.data.row_version, item.workspace_token); const snapshot = result.payload.data; cacheWorkspaceVersion(queryClient, taskId, snapshot.version_no, snapshot.client_seq, etagVersion(result.etag, query.data.payload.data.row_version + 1)); setNotice(`已恢复“${checkpoint.name}”并创建 v${snapshot.version_no}。`); setError(''); await query.refetch() } catch (reason) { session.blockSession(reason, item.workspace_token); setError(messageFor(reason)) } }
  if (session.isPending || session.issue.isPending || (task && ['READY', 'IN_PROGRESS', 'REPORT_DRAFT'].includes(task.status) && !item) || (item && query.isPending)) return <RequestStateView state="loading" />
  if (task && !['READY', 'IN_PROGRESS', 'REPORT_DRAFT'].includes(task.status)) return <RequestStateView state="empty" title="当前任务没有可用检查点" message="任务尚未进入或已经离开工作区。" />
  if (session.isError || query.isError || !item) return <RequestStateView state={session.error instanceof ApiError && session.error.status === 403 ? 'forbidden' : 'error'} message={messageFor(query.error ?? session.error)} onRetry={() => void query.refetch()} />
  if (item.status !== 'ACTIVE' || !item.workspace_token) return <RequestStateView state="error" title="工作区会话已失效" message="当前 Session 已过期或被撤销，请返回实验室重新进入。" />
  const data = query.data?.payload.data as WorkspaceCheckpointListData | undefined
  return <section className="workspace-page"><PageHeader eyebrow="CHECKPOINTS" title="命名检查点" description="检查点不可变，恢复会创建新的工作区版本。" actions={<a className="text-button" href={`/tasks/${taskId}/lab`}>返回实验室</a>} />{notice ? <p className="notice" role="status">{notice}</p> : null}{error ? <p className="form-error" role="alert">{error}</p> : null}<div className="toolbar"><input aria-label="检查点名称" value={name} onChange={(event) => setName(event.target.value)} placeholder="检查点名称" /><button className="primary-button" onClick={() => void create()}>创建检查点</button></div><p className="muted">当前工作区版本：v{data?.current_version ?? 0}</p><div className="data-table-wrap"><table className="data-table"><thead><tr><th>名称</th><th>版本</th><th>序号</th><th>时间</th><th>操作</th></tr></thead><tbody>{(data?.items ?? []).map((checkpoint) => <tr key={checkpoint.public_id}><td>{checkpoint.name}</td><td>v{checkpoint.version_no}</td><td>{checkpoint.source_seq}</td><td>{new Date(checkpoint.created_at).toLocaleString()}</td><td><button className="text-button" onClick={() => void restore(checkpoint)}>恢复</button></td></tr>)}</tbody></table></div></section>
}

export function WorkspaceReplayPage() {
  const { taskId = '' } = useParams()
  const query = useQuery({ queryKey: workspaceKeys.replay(taskId), queryFn: () => apiRequestWithMetadata<WorkspaceEnvelope<{ items: WorkspaceOperationData[]; next_cursor: string | null }>>(`/api/v2/tasks/${taskId}/operation-replay`) })
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state={query.error instanceof ApiError && query.error.status === 403 ? 'forbidden' : 'error'} message={messageFor(query.error)} onRetry={() => void query.refetch()} />
  const items = query.data?.payload.data.items ?? []
  return <section className="workspace-page"><PageHeader eyebrow="OPERATION REPLAY" title="工作区回放" description="仅显示当前学生可见的脱敏高层动作与结果摘要。" actions={<a className="text-button" href={`/tasks/${taskId}/lab`}>返回实验室</a>} /><ol className="timeline">{items.map((item) => <li key={item.public_id}><strong>{item.event_type}</strong><span>{item.result_summary}</span><small>{new Date(item.occurred_at).toLocaleString()} · {item.trace_id}</small></li>)}</ol>{items.length === 0 ? <RequestStateView state="empty" /> : null}</section>
}
