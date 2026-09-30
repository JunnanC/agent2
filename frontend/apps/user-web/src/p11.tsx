import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import {
  ApiError,
  RequestIntent,
  apiRequestWithMetadata,
  downloadFileInMemory,
  saveMemoryBlob,
  type ArchiveResponse,
  type DownloadGrantResponse,
} from '@edu/api-client'
import { PortalEventClient } from '@edu/event-client'
import { archiveKeys } from '@edu/query-keys'
import { RequestStateView, StatusBadge } from '@edu/ui'

type ArchiveManifest = {
  public_id: string
  package_digest: string
  object_count: number
  total_size_bytes: number
  retention_until: string
  asset: { public_id: string; original_name: string; size_bytes: number }
}

function archiveState(error: unknown): 'empty' | 'forbidden' | 'error' {
  if (error instanceof ApiError && error.status === 404) return 'empty'
  if (error instanceof ApiError && error.status === 403) return 'forbidden'
  return 'error'
}

export function UserArchivePanel({ taskId }: { taskId: string }) {
  const queryClient = useQueryClient()
  const [fallbackPolling, setFallbackPolling] = useState(false)
  const [progress, setProgress] = useState<number | null>(null)
  const [downloadError, setDownloadError] = useState('')
  const query = useQuery({
    queryKey: archiveKeys.user(taskId),
    queryFn: () => apiRequestWithMetadata<ArchiveResponse>(`/api/v2/tasks/${encodeURIComponent(taskId)}/archive`),
    refetchInterval: fallbackPolling ? 3000 : false,
  })

  useEffect(() => {
    let active = true
    const client = new PortalEventClient({
      onEvent: (event) => {
        if (event.type.startsWith('archive.') && event.data.task_id === taskId) {
          void queryClient.invalidateQueries({ queryKey: archiveKeys.user(taskId) })
        }
      },
      onStateChange: (state) => {
        if (active) setFallbackPolling(state === 'backoff' || state === 'polling')
      },
    })
    client.start()
    return () => { active = false; client.stop() }
  }, [queryClient, taskId])

  if (query.isPending) return <section className="section-block"><h2>归档与导出</h2><RequestStateView state="loading" /></section>
  if (query.isError) return <section className="section-block"><h2>归档与导出</h2><RequestStateView state={archiveState(query.error)} message={query.error instanceof ApiError && query.error.status === 404 ? '任务尚未进入归档流程。' : undefined} traceId={query.error instanceof ApiError ? query.error.traceId : undefined} onRetry={() => void query.refetch()} /></section>

  const archive = query.data.payload.data
  const manifest = archive.manifest as ArchiveManifest | null
  const download = async () => {
    if (!manifest) return
    setDownloadError(''); setProgress(0)
    try {
      const grant = await apiRequestWithMetadata<DownloadGrantResponse>(`/api/v2/files/${encodeURIComponent(manifest.asset.public_id)}/download-grants`, { method: 'POST', body: '{}', headers: { 'Content-Type': 'application/json' }, intent: new RequestIntent() })
      const blob = await downloadFileInMemory(grant.payload.data.download_path, (received, total) => setProgress(total ? Math.round((received / total) * 100) : received))
      saveMemoryBlob(blob, manifest.asset.original_name || `${taskId}-archive.zip`)
      setProgress(100)
    } catch {
      setDownloadError('归档下载未完成，请重新申请。')
      setProgress(null)
    }
  }

  return <section className="section-block">
    <div className="section-heading"><h2>归档与导出</h2><StatusBadge status={archive.status} /></div>
    <div className="constraint-strip"><span>目标终态 {archive.terminal_target}</span><span>当前任务 {archive.task_status}</span><span>校验 {archive.verifications.length ? String(archive.verifications.at(-1)?.result) : '等待中'}</span></div>
    {archive.failure ? <p className="form-error" role="alert">{String(archive.failure.error_code ?? 'ARCHIVE_FAILED')} · trace {String(archive.failure.trace_id ?? '')}</p> : null}
    {manifest ? <><div className="summary-grid"><div className="summary-item"><span>归档对象</span><strong>{manifest.object_count}</strong></div><div className="summary-item"><span>归档大小</span><strong>{manifest.total_size_bytes} B</strong></div><div className="summary-item"><span>保留至</span><strong>{new Date(manifest.retention_until).toLocaleDateString()}</strong></div></div><p className="digest">SHA-256 {manifest.package_digest}</p><button className="primary-button" onClick={() => void download()}><Download size={16} aria-hidden="true" /> 下载归档</button>{progress !== null ? <progress aria-label="归档下载进度" max={100} value={Math.min(progress, 100)} /> : null}</> : <p className="notice">归档正在异步生成和校验。</p>}
    {downloadError ? <p className="form-error" role="alert">{downloadError}</p> : null}
  </section>
}
