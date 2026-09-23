import { useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import {
  ApiError,
  RequestIntent,
  apiRequestWithMetadata,
  type ExtensionData,
  type ListEnvelope,
  type PublicationData,
  type RubricListResponse,
  type TaskData,
  type TemplateListResponse,
} from '@edu/api-client'
import { experimentKeys, rubricKeys, templateKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge, TextField } from '@edu/ui'

type Envelope<T> = { data: T; meta: Record<string, unknown> }

function messageFor(error: unknown): string {
  if (!(error instanceof ApiError)) return '请求未完成，请稍后重试。'
  if (error.status === 409) return '当前状态已变化，请刷新后重试。'
  if (error.status === 412) return '内容已被其他操作更新，请刷新后重试。'
  return error.payload.error.message
}

function toIso(value: FormDataEntryValue | null): string {
  return new Date(String(value ?? '')).toISOString()
}

function parsePrerequisites(value: FormDataEntryValue | null) {
  return String(value ?? '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line) => {
    const [kind, id] = line.split(':', 2)
    return kind === 'CHAPTER' ? { kind, chapter_id: id } : { kind: 'PUBLICATION', publication_id: id }
  })
}

export function ExperimentListPage() {
  const { courseId = '' } = useParams()
  const queryClient = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const publications = useQuery({
    queryKey: experimentKeys.publications(courseId),
    queryFn: () => apiRequestWithMetadata<Envelope<PublicationData[]>>(`/api/v2/teaching/courses/${courseId}/experiments`),
  })
  const templates = useQuery({
    queryKey: templateKeys.list(courseId),
    queryFn: () => apiRequestWithMetadata<TemplateListResponse>(`/api/v2/teaching/courses/${courseId}/templates`),
  })
  const rubrics = useQuery({
    queryKey: rubricKeys.list(courseId),
    queryFn: () => apiRequestWithMetadata<RubricListResponse>(`/api/v2/teaching/courses/${courseId}/rubrics`),
  })
  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError('')
    const form = new FormData(event.currentTarget)
    const body = {
      title: form.get('title'), description: form.get('description'),
      template_version_id: form.get('template_version_id'), rubric_version_id: form.get('rubric_version_id'),
      audience_mode: form.get('audience_mode'), late_enrollment_policy: form.get('late_enrollment_policy'),
      window_start: toIso(form.get('window_start')), window_end: toIso(form.get('window_end')),
      assignment_deadline: form.get('assignment_deadline') ? toIso(form.get('assignment_deadline')) : null,
      report_required: form.get('report_required') === 'on', review_mode: form.get('review_mode'),
      prerequisites: parsePrerequisites(form.get('prerequisites')),
    }
    try {
      await apiRequestWithMetadata(`/api/v2/teaching/courses/${courseId}/experiments`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), intent: new RequestIntent() })
      event.currentTarget.reset(); setShowCreate(false)
      await queryClient.invalidateQueries({ queryKey: experimentKeys.publications(courseId) })
    } catch (reason) { setError(messageFor(reason)) } finally { setBusy(false) }
  }
  if (publications.isPending || templates.isPending || rubrics.isPending) return <RequestStateView state="loading" />
  const failed = [publications, templates, rubrics].find((query) => query.isError)
  if (failed?.isError) return <RequestStateView state={failed.error instanceof ApiError && failed.error.status === 403 ? 'forbidden' : 'error'} message={messageFor(failed.error)} onRetry={() => void failed.refetch()} />
  const items = publications.data?.payload.data ?? []
  const templateItems = (templates.data?.payload.data ?? []).filter((item) => item.status === 'PUBLISHED' && item.current_version_id)
  const rubricItems = (rubrics.data?.payload.data ?? []).filter((item) => item.status === 'PUBLISHED' && item.current_version_id)
  return <section className="workspace-page">
    <PageHeader eyebrow="EXPERIMENTS" title="实验发布" description="管理冻结版本、受众快照、窗口和发布状态。" actions={<button className="text-button" onClick={() => setShowCreate((value) => !value)}>{showCreate ? '取消' : '新建草稿'}</button>} />
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    {showCreate ? <section className="section-block"><h2>发布草稿</h2><form className="form-grid" onSubmit={create}>
      <TextField label="实验标题" name="title" required />
      <label className="field"><span>模板版本</span><select name="template_version_id" required><option value="">请选择</option>{templateItems.map((item) => <option key={item.public_id} value={item.current_version_id ?? ''}>{item.name}</option>)}</select></label>
      <label className="field"><span>Rubric 版本</span><select name="rubric_version_id" required><option value="">请选择</option>{rubricItems.map((item) => <option key={item.public_id} value={item.current_version_id ?? ''}>{item.name}</option>)}</select></label>
      <label className="field"><span>受众</span><select name="audience_mode" defaultValue="ALL_ACTIVE"><option value="ALL_ACTIVE">全部在读学生</option><option value="SELECTED">指定学生</option></select></label>
      <label className="field"><span>晚选策略</span><select name="late_enrollment_policy" defaultValue="ASSIGN_UNTIL_DEADLINE"><option value="ASSIGN_UNTIL_DEADLINE">截止前补建</option><option value="DO_NOT_ASSIGN">不补建</option></select></label>
      <label className="field"><span>审核方式</span><select name="review_mode" defaultValue="MANUAL"><option value="MANUAL">人工审核</option><option value="MANUAL_WITH_AUTO_CHECK">自动检查辅助人工审核</option></select></label>
      <TextField label="开放时间" name="window_start" type="datetime-local" required />
      <TextField label="截止时间" name="window_end" type="datetime-local" required />
      <TextField label="分配截止时间" name="assignment_deadline" type="datetime-local" />
      <label className="field form-grid__full"><span>先修引用</span><textarea name="prerequisites" placeholder="CHAPTER:ID 或 PUBLICATION:ID，每行一项" /></label>
      <label className="field form-grid__full"><span>实验说明</span><textarea name="description" /></label>
      <label className="check-list form-grid__full"><input name="report_required" type="checkbox" defaultChecked /> 要求实验报告</label>
      <div className="form-actions"><button className="primary-button" disabled={busy}>{busy ? '保存中' : '保存草稿'}</button></div>
    </form></section> : null}
    {items.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>实验</th><th>窗口</th><th>受众</th><th>状态</th><th>操作</th></tr></thead><tbody>{items.map((item) => <tr key={item.public_id}><td data-wrap><strong>{item.title}</strong><br /><small>{item.public_id}</small></td><td>{new Date(item.window_start).toLocaleString()}<br />{new Date(item.window_end).toLocaleString()}</td><td>{item.audience_mode} · {item.audience_count}</td><td><StatusBadge status={item.status} /></td><td><a className="text-button" href={`/courses/${courseId}/experiments/${item.public_id}`}>管理</a></td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}
  </section>
}

export function ExperimentDetailPage() {
  const { courseId = '', publicationId = '' } = useParams()
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const [selected, setSelected] = useState('')
  const publication = useQuery({ queryKey: experimentKeys.publication(courseId, publicationId), queryFn: () => apiRequestWithMetadata<Envelope<PublicationData>>(`/api/v2/teaching/courses/${courseId}/experiments/${publicationId}`) })
  const tasks = useQuery({ queryKey: experimentKeys.tasks(courseId, publicationId), queryFn: () => apiRequestWithMetadata<ListEnvelope<TaskData>>(`/api/v2/teaching/courses/${courseId}/experiments/${publicationId}/tasks`) })
  const progress = useQuery({ queryKey: experimentKeys.progress(courseId), queryFn: () => apiRequestWithMetadata<Envelope<{ total: number; task_counts: Record<string, number> }>>(`/api/v2/teaching/courses/${courseId}/progress`) })
  const extensions = useQuery({ queryKey: experimentKeys.extensionRequests(courseId, { publicationId }), queryFn: () => apiRequestWithMetadata<ListEnvelope<ExtensionData>>(`/api/v2/teaching/courses/${courseId}/extension-requests?publication_id=${publicationId}`) })
  const item = publication.data?.payload.data
  const action = async (name: 'publish' | 'close' | 'withdraw') => {
    if (!item) return; setBusy(true); setError('')
    try {
      const body = name === 'publish' ? { selected_enrollment_ids: selected.split(',').map((value) => value.trim()).filter(Boolean) } : {}
      await apiRequestWithMetadata(`/api/v2/teaching/courses/${courseId}/experiments/${publicationId}/${name}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), ifMatch: `"${item.row_version}"`, intent: new RequestIntent() })
      await Promise.all([publication.refetch(), tasks.refetch(), progress.refetch()])
    } catch (reason) { setError(messageFor(reason)) } finally { setBusy(false) }
  }
  const decide = async (request: ExtensionData, decision: 'APPROVE' | 'REJECT') => {
    const reason = window.prompt(decision === 'APPROVE' ? '批准说明' : '拒绝原因') ?? ''
    if (decision === 'REJECT' && !reason) return
    try {
      await apiRequestWithMetadata(`/api/v2/teaching/courses/${courseId}/extension-requests/${request.public_id}/decide`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, reason }), ifMatch: `"${request.row_version}"`, intent: new RequestIntent() })
      await extensions.refetch()
    } catch (cause) { setError(messageFor(cause)) }
  }
  if (publication.isPending) return <RequestStateView state="loading" />
  if (publication.isError || !item) return <RequestStateView state={publication.error instanceof ApiError && publication.error.status === 403 ? 'forbidden' : 'error'} message={messageFor(publication.error)} onRetry={() => void publication.refetch()} />
  const taskItems = tasks.data?.payload.data ?? []; const requestItems = extensions.data?.payload.data ?? []; const summary = progress.data?.payload.data
  return <section className="workspace-page">
    <PageHeader eyebrow="EXPERIMENT" title={item.title} description={item.description} actions={<a className="text-button" href={`/courses/${courseId}/experiments`}>返回列表</a>} />
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    {Object.keys(item.publication_error ?? {}).length ? <p className="form-error">发布失败：{JSON.stringify(item.publication_error)}</p> : null}
    <div className="summary-grid"><div className="summary-item"><span>发布状态</span><strong><StatusBadge status={item.status} /></strong></div><div className="summary-item"><span>任务总数</span><strong>{summary?.total ?? taskItems.length}</strong></div><div className="summary-item"><span>受众快照</span><strong>{item.audience_count}</strong></div></div>
    {item.status === 'DRAFT' ? <section className="section-block"><h2>发布</h2>{item.audience_mode === 'SELECTED' ? <TextField label="Enrollment ID（逗号分隔）" value={selected} onChange={(event) => setSelected(event.target.value)} /> : null}<div className="toolbar"><button className="primary-button" disabled={busy} onClick={() => void action('publish')}>发布实验</button></div></section> : null}
    {['PUBLISHED', 'PUBLISHING', 'PUBLISH_FAILED'].includes(item.status) ? <div className="toolbar">{item.status === 'PUBLISHED' ? <button className="text-button" disabled={busy} onClick={() => void action('close')}>关闭发布</button> : null}<button className="text-button text-button--danger" disabled={busy} onClick={() => void action('withdraw')}>撤回发布</button></div> : null}
    <section className="section-block"><h2>任务追踪</h2>{tasks.isPending ? <RequestStateView state="loading" /> : tasks.isError ? <RequestStateView state="error" onRetry={() => void tasks.refetch()} /> : taskItems.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>学生</th><th>任务状态</th><th>装载作业</th><th>阶段</th><th>进度</th><th>个人截止时间</th><th>成果</th></tr></thead><tbody>{taskItems.map((task) => { const provisioning = (task.provisioning ?? {}) as Record<string, unknown>; return <tr key={task.public_id}><td data-wrap>{task.student_name}<br /><small>{task.public_id}</small></td><td><StatusBadge status={task.status} /></td><td>{provisioning.status ? <StatusBadge status={String(provisioning.status)} /> : '-'}</td><td>{String(provisioning.current_stage ?? '-')}</td><td>{task.progress}%</td><td>{task.effective_deadline ? new Date(task.effective_deadline).toLocaleString() : '-'}</td><td>{task.status === 'UNDER_REVIEW' ? <a className="text-button" href={`/courses/${courseId}/tasks/${task.public_id}/submission`}>只读预览</a> : '-'}</td></tr> })}</tbody></table></div> : <RequestStateView state="empty" />}</section>
    <section className="section-block"><h2>延期申请</h2>{extensions.isPending ? <RequestStateView state="loading" /> : extensions.isError ? <RequestStateView state="error" onRetry={() => void extensions.refetch()} /> : requestItems.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>任务</th><th>申请截止时间</th><th>状态</th><th>决定历史</th><th>操作</th></tr></thead><tbody>{requestItems.map((request) => <tr key={request.public_id}><td>{request.task_id}</td><td>{new Date(request.requested_deadline).toLocaleString()}</td><td><StatusBadge status={request.status} /></td><td>{request.decisions.length}</td><td>{request.status === 'PENDING' ? <div className="toolbar"><button className="text-button" onClick={() => void decide(request, 'APPROVE')}>批准</button><button className="text-button text-button--danger" onClick={() => void decide(request, 'REJECT')}>拒绝</button></div> : null}</td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}</section>
  </section>
}
