import { useEffect, useState, type ChangeEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { Download, FileText, RotateCw, Save, Send, Upload } from 'lucide-react'
import {
  ApiError,
  RequestIntent,
  apiRequestWithMetadata,
  type DownloadGrantResponse,
  type ReportAttachmentData,
  type ReportAttachmentUploadResponse,
  type ReportDraftResponse,
  type ReportVersionListResponse,
  type TaskData,
  type WorkspaceEnvelope,
} from '@edu/api-client'
import { experimentKeys, reportKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge } from '@edu/ui'

type UploadPost = { url: string; fields: Record<string, string>; expires_at?: string }
type UploadEnvelope = ReportAttachmentUploadResponse & {
  data: { asset: ReportAttachmentData; upload: UploadPost }
}
type TaskResponse = WorkspaceEnvelope<TaskData>
type GrantEnvelope = DownloadGrantResponse & {
  data: { grant_id: string; download_path: string; expires_at: string; max_downloads: number }
}

function messageFor(error: unknown): string {
  if (!(error instanceof ApiError)) return '请求未完成，请稍后重试。'
  if (error.status === 403) return '当前账号无权访问此成果。'
  if (error.status === 409) return '任务状态或附件扫描状态已变化。'
  if (error.status === 412) return '内容已被更新，请刷新后重试。'
  return error.payload.error.message
}

function mediaType(file: File): string {
  const suffix = file.name.split('.').pop()?.toLowerCase()
  return {
    pdf: 'application/pdf',
    docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    md: 'text/markdown',
    txt: 'text/plain',
  }[suffix ?? ''] ?? file.type
}

async function sha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, '0')).join('')
}

async function uploadToStore(upload: UploadPost, file: File): Promise<void> {
  const body = new FormData()
  for (const [key, value] of Object.entries(upload.fields)) body.append(key, value)
  body.append('file', file)
  const response = await fetch(upload.url, { method: 'POST', body })
  if (!response.ok) throw new Error(`附件上传失败 (${response.status})`)
}

async function downloadAsset(assetId: string): Promise<void> {
  const response = await apiRequestWithMetadata<GrantEnvelope>(`/api/v2/files/${assetId}/download-grants`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
    intent: new RequestIntent(),
  })
  window.location.assign(response.payload.data.download_path)
}

export function UserReportPage() {
  const { taskId = '' } = useParams()
  const queryClient = useQueryClient()
  const [body, setBody] = useState('')
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const taskQuery = useQuery({
    queryKey: experimentKeys.task(taskId),
    queryFn: () => apiRequestWithMetadata<TaskResponse>(`/api/v2/tasks/${encodeURIComponent(taskId)}`),
  })
  const draftQuery = useQuery({
    queryKey: reportKeys.draft(taskId),
    queryFn: () => apiRequestWithMetadata<ReportDraftResponse>(`/api/v2/tasks/${encodeURIComponent(taskId)}/report-draft`),
    refetchInterval: (query) => query.state.data?.payload.data.attachments.some((item) => item.scan_status === 'PENDING') ? 2500 : false,
  })
  const historyQuery = useQuery({
    queryKey: reportKeys.versions(taskId),
    queryFn: () => apiRequestWithMetadata<ReportVersionListResponse>(`/api/v2/tasks/${encodeURIComponent(taskId)}/report-versions`),
  })
  const draft = draftQuery.data?.payload.data
  const task = taskQuery.data?.payload.data
  const reportBody = draft?.body_markdown

  useEffect(() => {
    if (reportBody !== undefined && !dirty) setBody(reportBody)
  }, [draft?.public_id, draft?.updated_at, reportBody, dirty])

  const save = async () => {
    if (!draft) return
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await apiRequestWithMetadata<ReportDraftResponse>(`/api/v2/tasks/${encodeURIComponent(taskId)}/report-draft`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body_markdown: body }),
        ifMatch: draftQuery.data?.etag ?? `"${draft.row_version}"`,
        intent: new RequestIntent(),
      })
      queryClient.setQueryData(reportKeys.draft(taskId), result)
      await taskQuery.refetch()
      setDirty(false); setNotice('草稿已保存。')
    } catch (reason) { setError(messageFor(reason)) } finally { setBusy(false) }
  }

  const submit = async () => {
    if (!draft || !task || dirty) return
    if (!window.confirm('确认提交当前报告版本？提交后草稿将锁定。')) return
    setBusy(true); setError(''); setNotice('')
    try {
      await apiRequestWithMetadata(`/api/v2/tasks/${encodeURIComponent(taskId)}/submit-report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
        ifMatch: taskQuery.data?.etag ?? `"${task.row_version}"`,
        intent: new RequestIntent(),
      })
      setNotice('报告已提交。')
      await Promise.all([draftQuery.refetch(), historyQuery.refetch(), taskQuery.refetch()])
    } catch (reason) { setError(messageFor(reason)) } finally { setBusy(false) }
  }

  const addAttachment = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0]
    event.currentTarget.value = ''
    if (!file) return
    setBusy(true); setError(''); setNotice('')
    try {
      const created = await apiRequestWithMetadata<UploadEnvelope>(`/api/v2/tasks/${encodeURIComponent(taskId)}/attachments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_name: file.name, media_type: mediaType(file), size_bytes: file.size, digest_sha256: await sha256(file) }),
        intent: new RequestIntent(),
      })
      await uploadToStore(created.payload.data.upload, file)
      await apiRequestWithMetadata(`/api/v2/tasks/${encodeURIComponent(taskId)}/attachments/${created.payload.data.asset.public_id}/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
        ifMatch: `"${created.payload.data.asset.row_version}"`,
        intent: new RequestIntent(),
      })
      setNotice('附件已上传，安全扫描进行中。')
      await draftQuery.refetch()
    } catch (reason) { setError(messageFor(reason)) } finally { setBusy(false) }
  }

  if (taskQuery.isPending || draftQuery.isPending || historyQuery.isPending) return <RequestStateView state="loading" />
  const failed = [taskQuery, draftQuery, historyQuery].find((query) => query.isError)
  if (failed?.isError || !draft || !task) return <RequestStateView state={failed?.error instanceof ApiError && failed.error.status === 403 ? 'forbidden' : 'error'} message={messageFor(failed?.error)} onRetry={() => { void draftQuery.refetch(); void taskQuery.refetch() }} />
  const editable = draft.status === 'DRAFT' && ['IN_PROGRESS', 'REPORT_DRAFT'].includes(task.status)
  const versions = historyQuery.data?.payload.data ?? []

  return <section className="workspace-page">
    <PageHeader eyebrow="REPORT / SUBMISSION" title="实验报告" actions={<><a className="text-button" href={`/tasks/${taskId}/review-result`}>审核结果</a><a className="text-button" href={`/tasks/${taskId}`}>返回任务</a></>} />
    {notice ? <p className="notice" role="status">{notice}</p> : null}
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    <div className="summary-grid">
      <div className="summary-item"><span>任务状态</span><strong><StatusBadge status={task.status} /></strong></div>
      <div className="summary-item"><span>草稿状态</span><strong><StatusBadge status={draft.status} /></strong></div>
      <div className="summary-item"><span>工作区快照</span><strong className="digest">{draft.snapshot_digest || '尚未保存'}</strong></div>
    </div>
    <section className="section-block">
      <div className="section-heading"><h2>报告正文</h2><span>{dirty ? '未保存' : '已同步'}</span></div>
      <textarea className="report-editor" aria-label="Markdown 报告正文" value={body} disabled={!editable || busy} onChange={(event) => { setBody(event.target.value); setDirty(true) }} />
      <div className="toolbar">
        <button className="text-button" disabled={!editable || !dirty || busy} onClick={() => void save()}><Save size={16} aria-hidden="true" /> 保存草稿</button>
        <button className="primary-button" disabled={!editable || dirty || busy || !body.trim()} onClick={() => void submit()}><Send size={16} aria-hidden="true" /> 提交报告</button>
      </div>
    </section>
    <section className="section-block">
      <div className="section-heading"><h2>附件</h2><label className="text-button"><Upload size={16} aria-hidden="true" /> 上传附件<input aria-label="上传附件" type="file" accept=".pdf,.docx,.md,.txt" hidden disabled={!editable || busy} onChange={(event) => void addAttachment(event)} /></label></div>
      {draft.attachments.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>文件</th><th>大小</th><th>扫描</th><th>操作</th></tr></thead><tbody>{draft.attachments.map((attachment) => <tr key={attachment.public_id}><td data-wrap><FileText size={16} aria-hidden="true" /> {attachment.file_name}</td><td>{attachment.size_bytes.toLocaleString()} B</td><td><StatusBadge status={attachment.scan_status} />{attachment.failure_code ? <small className="form-error">{attachment.failure_code}</small> : null}</td><td>{attachment.scan_status === 'CLEAN' && attachment.status === 'ACTIVE' ? <button className="text-button" onClick={() => void downloadAsset(attachment.public_id)}><Download size={16} aria-hidden="true" /> 下载</button> : <button className="text-button" onClick={() => void draftQuery.refetch()}><RotateCw size={16} aria-hidden="true" /> 刷新状态</button>}</td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}
    </section>
    <section className="section-block">
      <h2>提交历史</h2>
      {versions.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>版本</th><th>提交时间</th><th>Trace</th><th>附件</th></tr></thead><tbody>{versions.map((version) => <tr key={version.public_id}><td>v{version.version_no}</td><td>{new Date(version.submitted_at).toLocaleString()}</td><td>{version.trace_id}</td><td>{version.attachments.length ? version.attachments.map((attachment) => <button className="text-button" key={attachment.public_id} onClick={() => void downloadAsset(attachment.asset_id)}><Download size={14} aria-hidden="true" /> {attachment.file_name}</button>) : '-'}</td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}
    </section>
  </section>
}
