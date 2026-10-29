import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw, RotateCcw, Trash2 } from 'lucide-react'
import {
  ApiError,
  RequestIntent,
  apiRequestWithMetadata,
  type CompensationData,
  type CompensationListResponse,
  type InstanceData,
  type InstanceListResponse,
} from './legacy/api-client'
import { PortalEventClient } from '@edu/event-client'
import { archiveKeys } from './legacy/query-keys'
import { PageHeader, RequestStateView, StatusBadge } from './legacy/ui'

function stateFor(error: unknown): 'forbidden' | 'conflict' | 'precondition' | 'error' {
  if (error instanceof ApiError && error.status === 403) return 'forbidden'
  if (error instanceof ApiError && error.status === 409) return 'conflict'
  if (error instanceof ApiError && error.status === 412) return 'precondition'
  return 'error'
}

function usePlatformArchiveEvents(): boolean {
  const queryClient = useQueryClient()
  const [fallbackPolling, setFallbackPolling] = useState(false)
  useEffect(() => {
    let active = true
    const client = new PortalEventClient({
      onEvent: (event) => {
        if (event.type.startsWith('archive.') || event.type.startsWith('runtime.')) {
          void queryClient.invalidateQueries({ queryKey: archiveKeys.all })
        }
      },
      onStateChange: (state) => {
        if (active) setFallbackPolling(state === 'backoff' || state === 'polling')
      },
    })
    client.start()
    return () => { active = false; client.stop() }
  }, [queryClient])
  return fallbackPolling
}

export function PlatformInstancesPage() {
  const queryClient = useQueryClient()
  const fallbackPolling = usePlatformArchiveEvents()
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState('')
  const query = useQuery({
    queryKey: archiveKeys.instances(),
    queryFn: () => apiRequestWithMetadata<InstanceListResponse>('/api/v2/platform/instances'),
    refetchInterval: fallbackPolling ? 3000 : false,
  })
  const destroy = async (item: InstanceData) => {
    const reason = window.prompt('请输入异常销毁原因')?.trim()
    if (!reason) return
    setBusyId(item.public_id); setError('')
    try {
      await apiRequestWithMetadata(`/api/v2/platform/instances/${encodeURIComponent(item.public_id)}/destroy`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason }), ifMatch: `"${item.row_version}"`, intent: new RequestIntent() })
      await queryClient.invalidateQueries({ queryKey: archiveKeys.instances() })
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.payload.error.message : '销毁请求未完成。')
    } finally { setBusyId('') }
  }
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state={stateFor(query.error)} traceId={query.error instanceof ApiError ? query.error.traceId : undefined} onRetry={() => void query.refetch()} />
  const values = query.data.payload.data
  return <section className="workspace-page">
    <PageHeader eyebrow="PLATFORM / RUNTIME RECOVERY" title="实例与孤儿检测" actions={<button className="text-button" title="刷新实例" onClick={() => void query.refetch()}><RefreshCw size={16} aria-hidden="true" /> 刷新</button>} />
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    {values.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>实例</th><th>任务 / 课程</th><th>数据库状态</th><th>外部状态</th><th>异常</th><th>操作</th></tr></thead><tbody>{values.map((item) => <tr key={item.public_id}><td data-wrap><strong>{item.public_id}</strong><br /><small>{item.external_id || '-'}</small></td><td data-wrap>{item.task_id || '外部孤儿'}<br /><small>{item.course_id || '-'}</small></td><td><StatusBadge status={item.status} /></td><td><StatusBadge status={item.external_status} /></td><td>{item.orphan ? '外部孤儿' : item.resource_leak ? '终态资源泄漏' : '-'}</td><td><button className="text-button text-button--danger" disabled={item.orphan || item.status === 'DESTROYED' || busyId === item.public_id} onClick={() => void destroy(item)}><Trash2 size={16} aria-hidden="true" /> {busyId === item.public_id ? '处理中' : '异常销毁'}</button></td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}
  </section>
}

export function PlatformCompensationsPage() {
  const queryClient = useQueryClient()
  const fallbackPolling = usePlatformArchiveEvents()
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState('')
  const query = useQuery({
    queryKey: archiveKeys.compensations(status),
    queryFn: () => apiRequestWithMetadata<CompensationListResponse>(`/api/v2/platform/compensations${status ? `?status=${status}` : ''}`),
    refetchInterval: fallbackPolling ? 3000 : false,
  })
  const retry = async (item: CompensationData) => {
    const reason = window.prompt('请输入人工重试原因')?.trim()
    if (!reason) return
    setBusyId(item.public_id); setError('')
    try {
      await apiRequestWithMetadata('/api/v2/platform/compensations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ compensation_id: item.public_id, reason }), ifMatch: `"${item.row_version}"`, intent: new RequestIntent() })
      await queryClient.invalidateQueries({ queryKey: archiveKeys.all })
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.payload.error.message : '补偿重试请求未完成。')
    } finally { setBusyId('') }
  }
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state={stateFor(query.error)} traceId={query.error instanceof ApiError ? query.error.traceId : undefined} onRetry={() => void query.refetch()} />
  const values = query.data.payload.data
  return <section className="workspace-page">
    <PageHeader eyebrow="PLATFORM / COMPENSATIONS" title="归档与回收补偿" actions={<button className="text-button" title="刷新补偿" onClick={() => void query.refetch()}><RefreshCw size={16} aria-hidden="true" /> 刷新</button>} />
    <label className="field"><span>补偿状态</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部</option><option value="RETRY">等待重试</option><option value="DEAD">已耗尽</option></select></label>
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    {values.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>补偿</th><th>对象</th><th>状态</th><th>尝试</th><th>失败</th><th>Trace</th><th>操作</th></tr></thead><tbody>{values.map((item) => <tr key={item.public_id}><td data-wrap>{item.task_type}<br /><small>{item.public_id}</small></td><td data-wrap>{item.subject_type}<br /><small>{item.subject_ref}</small></td><td><StatusBadge status={item.status} /></td><td>{item.attempt_count} / {item.max_attempts}</td><td>{item.error_code || '-'}</td><td className="digest">{item.trace_id}</td><td><button className="text-button" disabled={!['RETRY', 'DEAD'].includes(item.status) || busyId === item.public_id} onClick={() => void retry(item)}><RotateCcw size={16} aria-hidden="true" /> {busyId === item.public_id ? '处理中' : '人工重试'}</button></td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}
  </section>
}
