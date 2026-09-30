import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { Download, FileText } from 'lucide-react'
import { ApiError, RequestIntent, apiRequestWithMetadata, type DownloadGrantResponse, type ReportPreviewResponse } from '@edu/api-client'
import { reportKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge } from '@edu/ui'

type PreviewData = {
  kind: 'REPORT' | 'SYSTEM_ARTIFACT'
  task_id: string
  version?: {
    version_no: number
    body_markdown: string
    submitted_at: string
    trace_id: string
    snapshot_digest: string
    execution_run_id: string | null
    execution_status: string
    execution_result_summary: string
    execution_rule_digest: string
    execution_snapshot_id: string | null
    execution_snapshot_digest: string
    stdout_asset_id: string | null
    stderr_asset_id: string | null
    test_report_asset_id: string | null
    attachments: Array<{ public_id: string; asset_id: string; file_name: string; size_bytes: number; media_type: string; digest_sha256: string }>
  }
  artifact?: { public_id: string; kind: string; asset_id: string; digest_sha256: string; created_at: string }
}
type PreviewEnvelope = ReportPreviewResponse & { data: PreviewData }
type GrantEnvelope = DownloadGrantResponse & { data: { download_path: string } }

function messageFor(error: unknown): string {
  if (!(error instanceof ApiError)) return '成果暂时不可用。'
  if (error.status === 403) return '当前账号缺少课程 REVIEW_SUBMISSION 权限。'
  return error.payload.error.message
}

export function TeachingSubmissionPreviewPage() {
  const { courseId = '', taskId = '' } = useParams()
  const [error, setError] = useState('')
  const query = useQuery({
    queryKey: reportKeys.preview(courseId, taskId),
    queryFn: () => apiRequestWithMetadata<PreviewEnvelope>(`/api/v2/teaching/courses/${courseId}/tasks/${taskId}/submission-preview`),
  })
  const download = async (assetId: string) => {
    setError('')
    try {
      const result = await apiRequestWithMetadata<GrantEnvelope>(`/api/v2/files/${assetId}/download-grants`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', intent: new RequestIntent(),
      })
      window.location.assign(result.payload.data.download_path)
    } catch (reason) { setError(messageFor(reason)) }
  }
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state={query.error instanceof ApiError && query.error.status === 403 ? 'forbidden' : 'error'} message={messageFor(query.error)} onRetry={() => void query.refetch()} />
  const data = query.data?.payload.data
  const version = data?.version
  const artifact = data?.artifact
  const executionAssets = version ? [
    ['标准输出', version.stdout_asset_id],
    ['错误输出', version.stderr_asset_id],
    ['测试报告', version.test_report_asset_id],
  ] as const : []
  return <section className="workspace-page">
    <PageHeader eyebrow="SUBMISSION / READ ONLY" title="成果预览" actions={<a className="text-button" href={`/courses/${courseId}/experiments`}>返回课程</a>} />
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    <div className="summary-grid">
      <div className="summary-item"><span>成果类型</span><strong>{data?.kind ?? '-'}</strong></div>
      <div className="summary-item"><span>任务</span><strong>{taskId}</strong></div>
      <div className="summary-item"><span>状态</span><strong><StatusBadge status="UNDER_REVIEW" /></strong></div>
    </div>
    {version ? <>
      <section className="section-block"><div className="section-heading"><h2>报告 v{version.version_no}</h2><span>{new Date(version.submitted_at).toLocaleString()} · {version.trace_id}</span></div><pre className="report-preview">{version.body_markdown}</pre></section>
      <section className="section-block"><div className="section-heading"><h2>执行证据</h2><StatusBadge status={version.execution_status || 'NOT_AVAILABLE'} /></div><div className="summary-grid"><div className="summary-item"><span>执行记录</span><strong>{version.execution_run_id ?? '无'}</strong></div><div className="summary-item"><span>结果摘要</span><strong>{version.execution_result_summary || '-'}</strong></div><div className="summary-item"><span>执行快照</span><strong>{version.execution_snapshot_id ?? '无'}</strong><small className="digest">{version.execution_snapshot_digest || version.snapshot_digest}</small></div><div className="summary-item"><span>规则 digest</span><strong className="digest">{version.execution_rule_digest || '-'}</strong></div></div>{executionAssets.some(([, assetId]) => assetId) ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>资产</th><th>操作</th></tr></thead><tbody>{executionAssets.map(([label, assetId]) => assetId ? <tr key={label}><td>{label}</td><td><button className="text-button" onClick={() => void download(assetId)}><Download size={16} aria-hidden="true" /> 下载</button></td></tr> : null)}</tbody></table></div> : <RequestStateView state="empty" />}</section>
      <section className="section-block"><h2>已扫描附件</h2>{version.attachments.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>文件</th><th>类型</th><th>大小</th><th>操作</th></tr></thead><tbody>{version.attachments.map((item) => <tr key={item.public_id}><td data-wrap><FileText size={16} aria-hidden="true" /> {item.file_name}</td><td>{item.media_type}</td><td>{item.size_bytes.toLocaleString()} B</td><td><button className="text-button" onClick={() => void download(item.asset_id)}><Download size={16} aria-hidden="true" /> 下载</button></td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}</section>
    </> : artifact ? <section className="section-block"><h2>系统成果</h2><p>{artifact.kind} · {new Date(artifact.created_at).toLocaleString()}</p><p className="digest">SHA-256 {artifact.digest_sha256}</p><button className="text-button" onClick={() => void download(artifact.asset_id)}><Download size={16} aria-hidden="true" /> 下载成果</button></section> : <RequestStateView state="empty" />}
  </section>
}
