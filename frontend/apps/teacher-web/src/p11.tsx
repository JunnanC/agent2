import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, RefreshCw } from 'lucide-react'
import { useParams } from 'react-router-dom'
import {
  ApiError,
  RequestIntent,
  apiRequestWithMetadata,
  downloadFileInMemory,
  saveMemoryBlob,
  type ArchiveData,
  type ArchiveExportResponse,
  type ArchiveListResponse,
  type ArchiveResponse,
} from '@edu/api-client'
import { PortalEventClient } from '@edu/event-client'
import { archiveKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge } from '@edu/ui'

type ArchiveManifest = {
  public_id: string
  manifest_digest: string
  package_digest: string
  object_count: number
  total_size_bytes: number
  retention_until: string
  entries: Array<Record<string, unknown>>
  asset: { public_id: string; original_name: string; size_bytes: number }
}

function stateFor(error: unknown): 'empty' | 'forbidden' | 'conflict' | 'precondition' | 'error' {
  if (error instanceof ApiError && error.status === 403) return 'forbidden'
  if (error instanceof ApiError && error.status === 404) return 'empty'
  if (error instanceof ApiError && error.status === 409) return 'conflict'
  if (error instanceof ApiError && error.status === 412) return 'precondition'
  return 'error'
}

function useArchiveEvents(courseId: string): boolean {
  const queryClient = useQueryClient()
  const [fallbackPolling, setFallbackPolling] = useState(false)
  useEffect(() => {
    let active = true
    const client = new PortalEventClient({
      onEvent: (event) => {
        if (event.type.startsWith('archive.') && event.data.course_id === courseId) {
          void queryClient.invalidateQueries({ queryKey: archiveKeys.course(courseId) })
        }
      },
      onStateChange: (state) => {
        if (active) setFallbackPolling(state === 'backoff' || state === 'polling')
      },
    })
    client.start()
    return () => { active = false; client.stop() }
  }, [courseId, queryClient])
  return fallbackPolling
}

export function TeachingArchivesPage() {
  const { courseId = '' } = useParams()
  const fallbackPolling = useArchiveEvents(courseId)
  const query = useQuery({
    queryKey: archiveKeys.course(courseId),
    queryFn: () => apiRequestWithMetadata<ArchiveListResponse>(`/api/v2/teaching/courses/${encodeURIComponent(courseId)}/archives`),
    refetchInterval: fallbackPolling ? 3000 : false,
  })
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state={stateFor(query.error)} traceId={query.error instanceof ApiError ? query.error.traceId : undefined} onRetry={() => void query.refetch()} />
  const values = query.data.payload.data
  return <section className="workspace-page">
    <PageHeader eyebrow="TEACHING / ARCHIVES" title="课程成果归档" actions={<a className="text-button" href={`/courses/${courseId}`}>返回课程</a>} />
    {values.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>学生</th><th>任务</th><th>归档</th><th>终态</th><th>校验</th><th>操作</th></tr></thead><tbody>{values.map((item: ArchiveData) => <tr key={item.public_id}><td data-wrap>{item.student_name}</td><td className="digest">{item.task_id}</td><td><StatusBadge status={item.status} /></td><td><StatusBadge status={item.task_status} /> → {item.terminal_target}</td><td>{item.verifications.length ? <StatusBadge status={String(item.verifications.at(-1)?.result)} /> : '等待中'}</td><td><a className="text-button" href={`/courses/${courseId}/archives/${item.public_id}`}>查看校验</a></td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}
  </section>
}

export function TeachingArchiveDetailPage() {
  const { courseId = '', archiveId = '' } = useParams()
  const fallbackPolling = useArchiveEvents(courseId)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState<number | null>(null)
  const [error, setError] = useState('')
  const query = useQuery({
    queryKey: archiveKeys.detail(courseId, archiveId),
    queryFn: () => apiRequestWithMetadata<ArchiveResponse>(`/api/v2/teaching/courses/${encodeURIComponent(courseId)}/archives/${encodeURIComponent(archiveId)}`),
    refetchInterval: fallbackPolling ? 3000 : false,
  })
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state={stateFor(query.error)} traceId={query.error instanceof ApiError ? query.error.traceId : undefined} onRetry={() => void query.refetch()} />
  const archive = query.data.payload.data
  const manifest = archive.manifest as ArchiveManifest | null
  const exportArchive = async () => {
    if (!manifest) return
    setBusy(true); setError(''); setProgress(0)
    try {
      const grant = await apiRequestWithMetadata<ArchiveExportResponse>(`/api/v2/teaching/courses/${encodeURIComponent(courseId)}/archives/${encodeURIComponent(archiveId)}/exports`, { method: 'POST', body: '{}', headers: { 'Content-Type': 'application/json' }, ifMatch: query.data.etag ?? `"${archive.row_version}"`, intent: new RequestIntent() })
      const data = grant.payload.data as { download_path: string }
      const blob = await downloadFileInMemory(data.download_path, (received, total) => setProgress(total ? Math.round((received / total) * 100) : received))
      saveMemoryBlob(blob, manifest.asset.original_name || `${archive.task_id}-archive.zip`)
      setProgress(100)
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.payload.error.message : '导出未完成，请重新申请。')
      setProgress(null)
    } finally { setBusy(false) }
  }
  return <section className="workspace-page">
    <PageHeader eyebrow="ARCHIVE / VERIFICATION" title={`${archive.student_name} · ${archive.task_id}`} actions={<><button className="text-button" title="刷新归档" onClick={() => void query.refetch()}><RefreshCw size={16} aria-hidden="true" /> 刷新</button><a className="text-button" href={`/courses/${courseId}/archives`}>返回清单</a></>} />
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    <div className="summary-grid"><div className="summary-item"><span>归档状态</span><strong><StatusBadge status={archive.status} /></strong></div><div className="summary-item"><span>任务状态</span><strong><StatusBadge status={archive.task_status} /></strong></div><div className="summary-item"><span>安全回收时间</span><strong>{new Date(archive.safe_recycle_at).toLocaleString()}</strong></div></div>
    <section className="section-block"><h2>校验记录</h2>{archive.verifications.length ? <div className="data-table-wrap archive-table-wrap"><table className="data-table archive-table"><thead><tr><th>尝试</th><th>结果</th><th>Digest</th><th>错误</th><th>Trace</th></tr></thead><tbody>{archive.verifications.map((item) => <tr key={String(item.public_id)}><td>{String(item.attempt_no)}</td><td><StatusBadge status={String(item.result)} /></td><td className="digest">{String(item.actual_digest || item.expected_digest || '-')}</td><td>{String(item.error_code || '-')}</td><td className="digest">{String(item.trace_id)}</td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}</section>
    <section className="section-block"><h2>归档清单</h2>{manifest ? <><div className="constraint-strip"><span>{manifest.object_count} 个对象</span><span>{manifest.total_size_bytes} B</span><span>保留至 {new Date(manifest.retention_until).toLocaleString()}</span></div><p className="digest">Manifest {manifest.manifest_digest}</p><p className="digest">Package {manifest.package_digest}</p><div className="data-table-wrap archive-table-wrap"><table className="data-table archive-table"><thead><tr><th>路径</th><th>类型</th><th>大小</th><th>Digest</th></tr></thead><tbody>{manifest.entries.map((item, index) => <tr key={`${String(item.path)}-${index}`}><td data-wrap>{String(item.path)}</td><td>{String(item.kind)}</td><td>{String(item.size_bytes)} B</td><td className="digest">{String(item.digest)}</td></tr>)}</tbody></table></div><button className="primary-button" disabled={busy || archive.status !== 'PASSED'} onClick={() => void exportArchive()}><Download size={16} aria-hidden="true" /> {busy ? '传输中' : '申请并下载'}</button>{progress !== null ? <progress aria-label="归档传输进度" max={100} value={Math.min(progress, 100)} /> : null}</> : <p className="notice">归档尚未通过完整性校验，当前不可导出。</p>}</section>
  </section>
}
