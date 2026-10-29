import { useQuery } from '@tanstack/react-query'
import { ApiError, apiRequestWithMetadata, type PublicationData, type TaskData } from '@edu/api-client'
import { experimentKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge } from '@edu/ui'

type Compensation = {
  public_id: string
  task_type: string
  subject_type: string
  subject_ref: string
  status: string
  attempt_count: number
  max_attempts: number
  trace_id: string
}

type Reconciliation = {
  publication_id: string
  course_id: string
  expected_task_count: number
  actual_task_count: number
  status: string
}

type AnomalyData = {
  failed_tasks: TaskData[]
  failed_publications: PublicationData[]
  compensation_backlog: Compensation[]
  state_anomalies: TaskData[]
  reconciliation_anomalies: Reconciliation[]
}

type Envelope<T> = { data: T; meta: Record<string, unknown> }

export function ExperimentAnomaliesPage() {
  const query = useQuery({ queryKey: experimentKeys.anomalies(), queryFn: () => apiRequestWithMetadata<Envelope<AnomalyData>>('/api/v2/platform/tasks/anomalies'), refetchInterval: 30_000 })
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state={query.error instanceof ApiError && query.error.status === 403 ? 'forbidden' : 'error'} message={query.error instanceof ApiError ? query.error.payload.error.message : '异常摘要暂时不可用。'} onRetry={() => void query.refetch()} />
  const data = query.data?.payload.data
  const failedTasks = data?.failed_tasks ?? []; const failedPublications = data?.failed_publications ?? []; const backlog = data?.compensation_backlog ?? []; const states = data?.state_anomalies ?? []; const reconciliation = data?.reconciliation_anomalies ?? []
  return <section className="workspace-page">
    <PageHeader eyebrow="EXPERIMENT OPERATIONS" title="实验任务异常" description="跨课程只读监控，不提供业务状态修改入口。" />
    <div className="summary-grid"><div className="summary-item"><span>失败任务</span><strong>{failedTasks.length}</strong></div><div className="summary-item"><span>补偿积压</span><strong>{backlog.length}</strong></div><div className="summary-item"><span>对账异常</span><strong>{reconciliation.length + states.length + failedPublications.length}</strong></div></div>
    <section className="section-block"><h2>失败任务</h2>{failedTasks.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>课程 / 实验</th><th>学生</th><th>任务状态</th><th>装载阶段</th><th>错误 / 补偿</th></tr></thead><tbody>{failedTasks.map((task) => { const provisioning = (task.provisioning ?? {}) as Record<string, unknown>; return <tr key={task.public_id}><td>{task.course_id}<br /><small>{task.publication_id}</small></td><td>{task.student_name}</td><td><StatusBadge status={task.status} /></td><td>{String(provisioning.current_stage ?? '-')}<br />{provisioning.status ? <StatusBadge status={String(provisioning.status)} /> : null}</td><td data-wrap>{String(task.current_failure.error_code ?? provisioning.failure_code ?? 'TASK_FAILED')} · retryable={String(task.current_failure.retryable ?? provisioning.retryable ?? false)}<br />补偿：{String(provisioning.compensation_status ?? '-')}</td></tr> })}</tbody></table></div> : <RequestStateView state="empty" />}</section>
    <section className="section-block"><h2>发布失败</h2>{failedPublications.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>课程</th><th>发布</th><th>状态</th><th>错误</th></tr></thead><tbody>{failedPublications.map((item) => <tr key={item.public_id}><td>{item.course_id}</td><td data-wrap>{item.title}<br /><small>{item.public_id}</small></td><td><StatusBadge status={item.status} /></td><td data-wrap>{JSON.stringify(item.publication_error)}</td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}</section>
    <section className="section-block"><h2>补偿积压</h2>{backlog.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>补偿任务</th><th>对象</th><th>状态</th><th>重试</th><th>Trace</th></tr></thead><tbody>{backlog.map((item) => <tr key={item.public_id}><td>{item.task_type}</td><td>{item.subject_type}<br /><small>{item.subject_ref}</small></td><td><StatusBadge status={item.status} /></td><td>{item.attempt_count} / {item.max_attempts}</td><td>{item.trace_id}</td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}</section>
    <section className="section-block"><h2>发布与任务对账</h2>{reconciliation.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>课程</th><th>发布</th><th>状态</th><th>预期 / 实际</th></tr></thead><tbody>{reconciliation.map((item) => <tr key={item.publication_id}><td>{item.course_id}</td><td>{item.publication_id}</td><td><StatusBadge status={item.status} /></td><td>{item.expected_task_count} / {item.actual_task_count}</td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}</section>
    <section className="section-block"><h2>终止状态异常</h2>{states.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>任务</th><th>状态</th><th>终止目标</th></tr></thead><tbody>{states.map((item) => <tr key={item.public_id}><td>{item.public_id}</td><td><StatusBadge status={item.status} /></td><td>{item.terminal_target ?? '-'}</td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}</section>
  </section>
}
