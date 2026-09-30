import { useEffect, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import {
  ApiError,
  RequestIntent,
  apiRequestWithMetadata,
  type DashboardData,
  type ExtensionData,
  type ListEnvelope,
  type ProvisioningJob,
  type ProvisioningStageEvent,
  type TaskData,
  type TransitionData,
} from '@edu/api-client'
import { PortalEventClient } from '@edu/event-client'
import { experimentKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge, TextField } from '@edu/ui'

type Envelope<T> = { data: T; meta: Record<string, unknown> }

const provisioningStageLabels: Record<string, string> = {
  QUOTA_CHECK: '配额检查',
  IMAGE_PREPARE: '准备镜像',
  CREATE: '创建环境',
  NETWORK_ATTACH: '连接网络',
  BOOT_PROBE: '启动探测',
  WORKSPACE_READY: '工作区就绪',
}

function latestProvisioningStages(stages: ProvisioningStageEvent[]): ProvisioningStageEvent[] {
  return Array.from(new Map(stages.map((stage) => [stage.stage, stage])).values())
}

function messageFor(error: unknown): string {
  if (!(error instanceof ApiError)) return '请求未完成，请稍后重试。'
  if (error.status === 403) return '当前账号无权执行此操作。'
  if (error.status === 409) return '任务状态已变化，或当前条件不允许此操作。'
  if (error.status === 412) return '任务已在其他页面更新，请刷新后重试。'
  if (error.status === 429) return '资源配额暂时不足，请稍后重试。'
  if (error.status === 503) return '环境运行时暂时不可用，请稍后重试。'
  if (error.status === 401) return '当前登录会话已失效，请重新登录。'
  return error.payload.error.message
}

function TaskTable({ tasks }: { tasks: TaskData[] }) {
  if (!tasks.length) return <RequestStateView state="empty" />
  return <div className="data-table-wrap"><table className="data-table"><thead><tr><th>实验</th><th>运行环境</th><th>状态</th><th>个人截止时间</th><th>操作</th></tr></thead><tbody>{tasks.map((task) => <tr key={task.public_id}><td data-wrap><strong>{task.title}</strong><br /><small>{task.course_id}</small></td><td>{task.template_name}<br /><small>{task.runtime_type}</small></td><td><StatusBadge status={task.status} /></td><td>{task.effective_deadline ? new Date(task.effective_deadline).toLocaleString() : '-'}</td><td><a className="text-button" href={`/tasks/${task.public_id}`}>查看</a></td></tr>)}</tbody></table></div>
}

export function ExperimentDashboardPage() {
  const query = useQuery({ queryKey: experimentKeys.dashboard(), queryFn: () => apiRequestWithMetadata<Envelope<DashboardData>>('/api/v2/me/dashboard') })
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state={query.error instanceof ApiError && query.error.status === 403 ? 'forbidden' : 'error'} message={messageFor(query.error)} onRetry={() => void query.refetch()} />
  const dashboard = query.data?.payload.data
  const counts = (dashboard?.counts ?? {}) as Record<string, number>
  return <section className="workspace-page"><PageHeader eyebrow="MY LAB" title="实验工作台" description="个人任务、有效窗口和可执行操作。" /><div className="summary-grid"><div className="summary-item"><span>待开始</span><strong>{counts.ASSIGNED ?? 0}</strong></div><div className="summary-item"><span>进行中</span><strong>{(counts.PROVISIONING ?? 0) + (counts.READY ?? 0) + (counts.IN_PROGRESS ?? 0) + (counts.REPORT_DRAFT ?? 0)}</strong></div><div className="summary-item"><span>已完成</span><strong>{counts.COMPLETED ?? 0}</strong></div></div><section className="section-block"><h2>最近任务</h2><TaskTable tasks={dashboard?.next_tasks ?? []} /></section></section>
}

export function ExperimentTaskListPage() {
  const [status, setStatus] = useState('')
  const query = useQuery({ queryKey: experimentKeys.myTasks({ status }), queryFn: () => apiRequestWithMetadata<ListEnvelope<TaskData>>(`/api/v2/tasks${status ? `?status=${status}` : ''}`) })
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state={query.error instanceof ApiError && query.error.status === 403 ? 'forbidden' : 'error'} message={messageFor(query.error)} onRetry={() => void query.refetch()} />
  return <section className="workspace-page"><PageHeader eyebrow="TASKS" title="我的实验" description="仅显示当前账号的个人任务。" /><label className="field"><span>任务状态</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部状态</option><option value="ASSIGNED">待开始</option><option value="PROVISIONING">装载中</option><option value="READY">可进入</option><option value="IN_PROGRESS">进行中</option><option value="REPORT_DRAFT">报告草稿</option><option value="FAILED">失败</option><option value="COMPLETED">已完成</option></select></label><TaskTable tasks={query.data?.payload.data ?? []} /></section>
}

export function ExperimentTaskDetailPage() {
  const { taskId = '' } = useParams(); const queryClient = useQueryClient(); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState('')
  const [streamState, setStreamState] = useState<'live' | 'polling'>('polling')
  const task = useQuery({
    queryKey: experimentKeys.task(taskId),
    queryFn: () => apiRequestWithMetadata<Envelope<TaskData>>(`/api/v2/tasks/${taskId}`),
    refetchInterval: (query) => {
      const status = query.state.data?.payload.data.status
      return streamState === 'polling' && status === 'PROVISIONING' ? 3000 : false
    },
  })
  const provisioning = useQuery({
    queryKey: experimentKeys.provisioningJob(taskId),
    queryFn: () => apiRequestWithMetadata<Envelope<ProvisioningJob>>(`/api/v2/tasks/${taskId}/provisioning-job`),
    refetchInterval: (query) => {
      if (streamState !== 'polling') return false
      const status = query.state.data?.payload.data.status
      return status === 'QUEUED' || status === 'RUNNING' || status === 'RETRY' ? 3000 : false
    },
  })
  const transitions = useQuery({ queryKey: experimentKeys.transitions(taskId), queryFn: () => apiRequestWithMetadata<Envelope<TransitionData[]>>(`/api/v2/tasks/${taskId}/transitions`) })
  const extensions = useQuery({ queryKey: experimentKeys.extensions(taskId), queryFn: () => apiRequestWithMetadata<Envelope<ExtensionData[]>>(`/api/v2/tasks/${taskId}/extensions`) })
  useEffect(() => {
    if (!taskId) return undefined
    const client = new PortalEventClient({
      url: `/api/v2/events/stream?channel=task:${encodeURIComponent(taskId)}`,
      onEvent: () => {
        void queryClient.invalidateQueries({ queryKey: experimentKeys.task(taskId) })
        void queryClient.invalidateQueries({ queryKey: experimentKeys.provisioningJob(taskId) })
        void queryClient.invalidateQueries({ queryKey: experimentKeys.transitions(taskId) })
      },
      onStateChange: (state) => setStreamState(state === 'live' ? 'live' : 'polling'),
      poll: async () => {
        await Promise.all([
          queryClient.refetchQueries({ queryKey: experimentKeys.task(taskId), type: 'active' }),
          queryClient.refetchQueries({ queryKey: experimentKeys.provisioningJob(taskId), type: 'active' }),
          queryClient.refetchQueries({ queryKey: experimentKeys.transitions(taskId), type: 'active' }),
        ])
        return []
      },
    })
    client.start()
    return () => client.stop()
  }, [queryClient, taskId])
  const item = task.data?.payload.data
  const start = async () => {
    if (!item) return; setBusy(true); setError(''); setNotice('')
    try {
      await apiRequestWithMetadata(`/api/v2/tasks/${taskId}/start`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', ifMatch: `"${item.row_version}"`, intent: new RequestIntent() })
      setNotice('装载请求已受理，正在等待 FakeRuntime 阶段结果。'); await Promise.all([task.refetch(), provisioning.refetch(), transitions.refetch()])
    } catch (reason) { setError(messageFor(reason)) } finally { setBusy(false) }
  }
  const jobAction = async (action: 'cancel' | 'retry') => {
    if (!item) return
    setBusy(true); setError(''); setNotice('')
    try {
      const path = action === 'retry' ? `/api/v2/tasks/${taskId}/retry` : `/api/v2/tasks/${taskId}/provisioning-job/cancel`
      await apiRequestWithMetadata(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', ifMatch: `"${item.row_version}"`, intent: new RequestIntent() })
      setNotice(action === 'retry' ? '重试请求已受理。' : '排队装载已取消。')
      await Promise.all([task.refetch(), provisioning.refetch(), transitions.refetch()])
    } catch (reason) { setError(messageFor(reason)) } finally { setBusy(false) }
  }
  const requestExtension = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError(''); setNotice(''); const form = new FormData(event.currentTarget)
    try {
      await apiRequestWithMetadata(`/api/v2/tasks/${taskId}/extension-requests`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ requested_deadline: new Date(String(form.get('requested_deadline'))).toISOString(), reason: form.get('reason') }), intent: new RequestIntent() })
      event.currentTarget.reset(); setNotice('延期申请已提交。'); await extensions.refetch(); await queryClient.invalidateQueries({ queryKey: experimentKeys.dashboard() })
    } catch (reason) { setError(messageFor(reason)) } finally { setBusy(false) }
  }
  const completeNonReport = async () => {
    if (!item) return
    setBusy(true); setError(''); setNotice('')
    try {
      await apiRequestWithMetadata(`/api/v2/tasks/${taskId}/complete`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
        ifMatch: `"${item.row_version}"`, intent: new RequestIntent(),
      })
      setNotice('系统已登记当前工作区快照为成果。')
      await Promise.all([task.refetch(), transitions.refetch()])
    } catch (reason) { setError(messageFor(reason)) } finally { setBusy(false) }
  }
  if (task.isPending) return <RequestStateView state="loading" />
  if (task.isError || !item) return <RequestStateView state={task.error instanceof ApiError && task.error.status === 403 ? 'forbidden' : 'error'} message={messageFor(task.error)} onRetry={() => void task.refetch()} />
  const blockers = item.blockers ?? []; const history = transitions.data?.payload.data ?? []; const extensionItems = extensions.data?.payload.data ?? []; const job = provisioning.data?.payload.data
  return <section className="workspace-page">
    <PageHeader eyebrow="EXPERIMENT TASK" title={item.title} description={`${item.template_name} · ${item.runtime_type}`} actions={<a className="text-button" href="/tasks">返回列表</a>} />
    {notice ? <p className="notice" role="status">{notice}</p> : null}{error ? <p className="form-error" role="alert">{error}</p> : null}
    <div className="summary-grid"><div className="summary-item"><span>任务状态</span><strong><StatusBadge status={item.status} /></strong></div><div className="summary-item"><span>有效窗口</span><strong>{new Date(item.window_start).toLocaleString()}</strong><small>至 {item.effective_deadline ? new Date(item.effective_deadline).toLocaleString() : new Date(item.window_end).toLocaleString()}</small></div><div className="summary-item"><span>冻结版本</span><strong>{item.template_version_id}</strong><small className="digest">{item.template_spec_digest ?? '-'}</small></div></div>
    {blockers.length ? <section className="section-block"><h2>先修阻断</h2><div className="constraint-strip">{blockers.map((blocker, index) => <span key={index}>{String(blocker.type)} · {String(blocker.reason)}</span>)}</div></section> : null}
    <section className="section-block"><h2>可执行操作</h2><div className="toolbar">{item.allowed_actions.includes('START') ? <button className="primary-button" disabled={busy || blockers.length > 0} onClick={() => void start()}>开始装载</button> : null}{job?.status === 'QUEUED' ? <button className="text-button text-button--danger" disabled={busy} onClick={() => void jobAction('cancel')}>取消排队</button> : null}{item.status === 'FAILED' && job?.retryable ? <button className="primary-button" disabled={busy} onClick={() => void jobAction('retry')}>重试装载</button> : null}{item.status === 'READY' || item.status === 'IN_PROGRESS' || item.status === 'REPORT_DRAFT' ? <a className="primary-button" href={`/tasks/${taskId}/lab`}>进入工作区</a> : null}{item.status === 'READY' || item.status === 'IN_PROGRESS' || item.status === 'REPORT_DRAFT' ? <a className="text-button" href={`/tasks/${taskId}/agent`}>任务 Agent</a> : null}{item.report_required && ['IN_PROGRESS', 'REPORT_DRAFT'].includes(item.status) ? <a className="text-button" href={`/tasks/${taskId}/report`}>编辑报告</a> : null}{!item.report_required && item.status === 'IN_PROGRESS' ? <button className="primary-button" disabled={busy} onClick={() => void completeNonReport()}>提交工作区成果</button> : null}{!item.allowed_actions.length && !job && !['IN_PROGRESS', 'REPORT_DRAFT'].includes(item.status) ? <span>当前无可执行操作</span> : null}</div></section>
    <section className="section-block"><h2>装载作业</h2>{provisioning.isPending ? <RequestStateView state="loading" /> : provisioning.isError && !(provisioning.error instanceof ApiError && provisioning.error.status === 404) ? <RequestStateView state={provisioning.error instanceof ApiError && provisioning.error.status === 403 ? 'forbidden' : 'error'} message={messageFor(provisioning.error)} onRetry={() => void provisioning.refetch()} /> : job ? <><div className="summary-grid"><div className="summary-item"><span>作业状态</span><strong><StatusBadge status={job.status} /></strong></div><div className="summary-item"><span>当前阶段</span><strong>{(provisioningStageLabels[job.current_stage] ?? job.current_stage) || '-'}</strong><small>{latestProvisioningStages(job.stages).filter((stage) => stage.status === 'PASSED' || stage.status === 'SKIPPED').length} / {Object.keys(provisioningStageLabels).length} 阶段 · {streamState === 'live' ? 'SSE 实时' : '轮询降级'}</small></div><div className="summary-item"><span>Trace</span><strong>{job.trace_id}</strong><button className="text-button" onClick={() => void navigator.clipboard?.writeText(job.trace_id)}>复制</button></div></div>{job.failure ? <p className="form-error">{String(job.failure.error_code ?? 'PROVISIONING_FAILED')} · 可重试：{String(job.retryable)}</p> : null}<div className="data-table-wrap"><table className="data-table"><thead><tr><th>阶段</th><th>状态</th><th>尝试</th><th>错误</th></tr></thead><tbody>{latestProvisioningStages(job.stages).map((stage) => <tr key={stage.public_id}><td>{provisioningStageLabels[stage.stage] ?? stage.stage}</td><td><StatusBadge status={stage.status} /></td><td>{stage.attempt_no}</td><td>{stage.error_code || '-'}</td></tr>)}</tbody></table></div></> : <RequestStateView state="empty" />}</section>
    {item.allowed_actions.includes('REQUEST_EXTENSION') ? <section className="section-block"><h2>申请延期或补交</h2><form className="form-grid" onSubmit={requestExtension}><TextField label="申请截止时间" name="requested_deadline" type="datetime-local" required /><TextField label="申请原因" name="reason" required /><div className="form-actions"><button className="primary-button" disabled={busy}>提交申请</button></div></form></section> : null}
    <section className="section-block"><h2>延期记录</h2>{extensions.isPending ? <RequestStateView state="loading" /> : extensions.isError ? <RequestStateView state="error" onRetry={() => void extensions.refetch()} /> : extensionItems.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>申请时间窗</th><th>原因</th><th>状态</th><th>决定历史</th></tr></thead><tbody>{extensionItems.map((extension) => <tr key={extension.public_id}><td>{new Date(extension.requested_deadline).toLocaleString()}</td><td data-wrap>{extension.reason}</td><td><StatusBadge status={extension.status} /></td><td>{extension.decisions.length}</td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}</section>
    <section className="section-block"><h2>状态流水</h2>{transitions.isPending ? <RequestStateView state="loading" /> : transitions.isError ? <RequestStateView state="error" onRetry={() => void transitions.refetch()} /> : history.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>时间</th><th>状态变化</th><th>触发方式</th><th>原因</th></tr></thead><tbody>{history.map((row) => <tr key={row.public_id}><td>{new Date(row.created_at).toLocaleString()}</td><td>{row.from_status || '-'} → {row.to_status}</td><td>{row.trigger}</td><td data-wrap>{row.reason}</td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}</section>
  </section>
}
