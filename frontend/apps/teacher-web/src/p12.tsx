import { useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ApiError, RequestIntent, apiRequestWithMetadata, type AgentProfileData, type AgentProfileListResponse } from '@edu/api-client'
import { agentKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge, TextField } from '@edu/ui'

type RecordData = {
  public_id: string
  version_no?: number
  modes: string[]
  model_route?: string
  status?: string
  name?: string
  source_type?: string
  title?: string
  threshold?: { minimum_score?: number }
  case_count?: number
  rating?: string | number
  note?: string
  issue_type?: string
  triage?: { status?: string; row_version: number }
  model_routes?: RecordData[]
  key?: string
  model_name?: string
  [key: string]: unknown
}
type AgentOptions = { data: { model_routes: RecordData[] } }
function message(error: unknown) { return error instanceof ApiError ? `${error.payload.error.message}（trace: ${error.traceId || 'n/a'}）` : '课程 Agent 请求未完成。' }
function useAgentList<T>(path: string, key: readonly unknown[]) { return useQuery({ queryKey: key, queryFn: () => apiRequestWithMetadata<{ data: T[] }>(path) }) }

export function TeachingAgentPage({ courseId }: { courseId: string }) {
  const base = `/api/v2/teaching/courses/${courseId}`
  const [showCreate, setShowCreate] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState('')
  const profiles = useQuery({ queryKey: agentKeys.teachingProfiles(courseId), queryFn: () => apiRequestWithMetadata<AgentProfileListResponse>(`${base}/agent-profiles`) })
  const knowledge = useAgentList<RecordData>(`${base}/agent-knowledge-bases`, agentKeys.teachingKnowledge(courseId))
  const feedback = useAgentList<RecordData>(`${base}/agent-feedback`, agentKeys.teachingFeedback(courseId))
  const analytics = useQuery({ queryKey: [...agentKeys.all, 'teaching', 'analytics', courseId], queryFn: () => apiRequestWithMetadata<RecordData>(`${base}/agent-analytics`) })
  const options = useQuery({ queryKey: [...agentKeys.all, 'teaching', 'options', courseId], queryFn: () => apiRequestWithMetadata<AgentOptions>(`${base}/agent-options`) })
  const prompts = useAgentList<RecordData>(`${base}/agent-prompt-templates`, [...agentKeys.all, 'teaching', 'prompts', courseId])
  const suites = useAgentList<RecordData>(`${base}/agent-eval-suites`, [...agentKeys.all, 'teaching', 'eval-suites', courseId])
  const [selectedKb, setSelectedKb] = useState('')
  const sources = useQuery({ queryKey: [...agentKeys.teachingKnowledge(courseId), 'sources', selectedKb], queryFn: () => apiRequestWithMetadata<{ data: RecordData[] }>(`${base}/agent-knowledge-bases/${selectedKb}/sources`), enabled: Boolean(selectedKb) })

  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(''); const form = new FormData(event.currentTarget)
    try { await apiRequestWithMetadata(`${base}/agent-profiles`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ modes: [form.get('mode')], model_route: form.get('model_route'), budget: { max_tokens: Number(form.get('max_tokens') || 2048) } }), intent: new RequestIntent() }); setShowCreate(false); setNotice('草稿 profile 已创建。'); await profiles.refetch() } catch (cause) { setError(message(cause)) }
  }
  const createKnowledge = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(''); const form = new FormData(event.currentTarget)
    try { const result = await apiRequestWithMetadata<{ data: RecordData }>(`${base}/agent-knowledge-bases`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: form.get('name'), description: form.get('description') }), intent: new RequestIntent() }); setSelectedKb(result.payload.data.public_id); setNotice('知识库草稿已创建。'); await knowledge.refetch(); event.currentTarget.reset() } catch (cause) { setError(message(cause)) }
  }
  const createSource = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!selectedKb) return; setError(''); const form = new FormData(event.currentTarget)
    try { await apiRequestWithMetadata(`${base}/agent-knowledge-bases/${selectedKb}/sources`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source_type: form.get('source_type'), title: form.get('title'), material_version_id: form.get('material_version_id') || '' }), intent: new RequestIntent() }); setNotice('知识来源已登记；静态资料必须通过扫描上传后再摄取。'); await sources.refetch(); event.currentTarget.reset() } catch (cause) { setError(message(cause)) }
  }
  const createPrompt = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(''); const form = new FormData(event.currentTarget)
    try { await apiRequestWithMetadata(`${base}/agent-prompt-templates`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ body: form.get('body'), template_id: '' }), intent: new RequestIntent() }); setNotice('课程提示词版本已发布；profile 重新评测后才会生效。'); await prompts.refetch(); event.currentTarget.reset() } catch (cause) { setError(message(cause)) }
  }
  const createSuite = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(''); const form = new FormData(event.currentTarget)
    try { await apiRequestWithMetadata(`${base}/agent-eval-suites`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: form.get('name'), threshold: { minimum_score: Number(form.get('minimum_score') || 1) } }), intent: new RequestIntent() }); setNotice('课程评测套件已创建；平台强制用例仍然保留。'); await suites.refetch(); event.currentTarget.reset() } catch (cause) { setError(message(cause)) }
  }
  const action = async (item: AgentProfileData, name: 'evaluate' | 'activate' | 'retire') => {
    setError(''); try { await apiRequestWithMetadata(`${base}/agent-profiles/${item.public_id}/${name}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', ifMatch: `"${item.row_version}"`, intent: new RequestIntent() }); setNotice(name === 'evaluate' ? '平台与课程评测已排队。' : name === 'activate' ? 'profile 已激活。' : 'profile 已退休。'); await profiles.refetch() } catch (cause) { setError(message(cause)) }
  }
  const triage = async (item: RecordData) => {
    if (!item.triage) return
    setError(''); try { await apiRequestWithMetadata(`${base}/agent-feedback/${item.public_id}/triage`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'CLOSED', note: '教师已处置' }), ifMatch: `"${item.triage.row_version}"`, intent: new RequestIntent() }); setNotice('反馈已标记为已处置。'); await feedback.refetch() } catch (cause) { setError(message(cause)) }
  }
  if (profiles.isPending || knowledge.isPending) return <RequestStateView state="loading" />
  if (profiles.isError) return <RequestStateView state="error" message={message(profiles.error)} onRetry={() => void profiles.refetch()} />
  const values = profiles.data?.payload.data ?? []
  const kbValues = knowledge.data?.payload.data ?? []
  const firstKb = kbValues[0]
  const routeValues = options.data?.payload.data.model_routes ?? []
  return <section className="workspace-page"><PageHeader eyebrow="TEACHING / AGENTS" title="课程 Agent 配置" description="profile、知识源、提示词、评测和反馈均在课程 scope 内，激活必须通过完整版本评测。" actions={<button className="text-button" onClick={() => setShowCreate((value) => !value)}>新建 profile</button>} />{notice ? <p className="notice" role="status">{notice}</p> : null}{error ? <p className="form-error" role="alert">{error}</p> : null}
    {showCreate ? <section className="section-block"><h2>新建 profile 草稿</h2><form className="form-grid" onSubmit={(event) => void create(event)}><label className="field"><span>模式</span><select name="mode" defaultValue="KNOWLEDGE_QA"><option>KNOWLEDGE_QA</option><option>SOCRATIC_HINT</option><option>DEBUG_ASSIST</option><option>REPORT_COACH</option><option>WORKSPACE_ASSIST</option></select></label><label className="field"><span>模型路由</span><select name="model_route" defaultValue={routeValues[0]?.public_id ?? 'local-rule-based'}>{routeValues.map((route: RecordData) => <option key={route.public_id} value={route.public_id}>{route.key} · {route.model_name}</option>)}</select></label><TextField label="最大 token" name="max_tokens" type="number" defaultValue="2048" /><div className="form-actions"><button className="primary-button" type="submit">创建草稿</button></div></form></section> : null}
    <section className="section-block"><h2>Profile 与激活门禁</h2><div className="data-table-wrap"><table className="data-table"><thead><tr><th>版本</th><th>模式</th><th>路由</th><th>状态</th><th>操作</th></tr></thead><tbody>{values.map((item) => <tr key={item.public_id}><td>v{item.version_no}</td><td data-wrap>{item.modes?.join(', ') ?? ''}</td><td>{item.model_route}</td><td><StatusBadge status={item.status ?? ''} /></td><td><div className="toolbar">{item.status === 'DRAFT' ? <button className="text-button" onClick={() => void action(item, 'evaluate')}>评测</button> : null}{item.status === 'EVALUATING' ? <button className="text-button" onClick={() => void action(item, 'activate')}>激活</button> : null}{item.status === 'ACTIVE' ? <button className="text-button text-button--danger" onClick={() => void action(item, 'retire')}>退休</button> : null}</div></td></tr>)}</tbody></table></div>{values.length === 0 ? <RequestStateView state="empty" /> : null}</section>
    <section className="section-block"><h2>知识库与来源</h2><form className="form-grid" onSubmit={(event) => void createKnowledge(event)}><TextField label="知识库名称" name="name" required /><TextField label="说明" name="description" /><button className="primary-button" type="submit">新建知识库</button></form>{kbValues.length ? <label className="field"><span>当前知识库</span><select value={selectedKb || firstKb?.public_id || ''} onChange={(event) => setSelectedKb(event.target.value)}>{kbValues.map((item) => <option key={item.public_id} value={item.public_id}>{item.name} · {item.status}</option>)}</select></label> : <RequestStateView state="empty" />}{selectedKb || firstKb ? <><form className="form-grid" onSubmit={(event) => void createSource(event)}><label className="field"><span>来源类型</span><select name="source_type" defaultValue="STATIC"><option>STATIC</option><option>TEACHER_FAQ</option><option>LAB_MANUAL</option><option>COURSE_MATERIAL</option></select></label><TextField label="来源标题" name="title" required /><TextField label="已发布资料版本（可选）" name="material_version_id" /><button className="text-button" type="submit">登记来源</button></form>{sources.isError ? <RequestStateView state="error" message={message(sources.error)} onRetry={() => void sources.refetch()} /> : <div className="data-table-wrap"><table className="data-table"><thead><tr><th>来源</th><th>类型</th><th>状态</th></tr></thead><tbody>{(sources.data?.payload.data ?? []).map((item) => <tr key={item.public_id}><td>{item.title}</td><td>{item.source_type}</td><td><StatusBadge status={item.status ?? ''} /></td></tr>)}</tbody></table></div>}</> : null}</section>
    <section className="section-block"><h2>提示词版本</h2><form className="form-grid" onSubmit={(event) => void createPrompt(event)}><TextField label="课程指令" name="body" required /><button className="text-button" type="submit">发布版本</button></form>{prompts.data?.payload.data.length ? <ul>{prompts.data.payload.data.map((item) => <li key={item.public_id}>{item.name} · {item.status}</li>)}</ul> : <RequestStateView state="empty" />}</section>
    <section className="section-block"><h2>课程评测套件</h2><form className="form-grid" onSubmit={(event) => void createSuite(event)}><TextField label="套件名称" name="name" required /><TextField label="最低分" name="minimum_score" type="number" step="0.01" defaultValue="1" /><button className="text-button" type="submit">创建套件</button></form>{suites.data?.payload.data.length ? <ul>{suites.data.payload.data.map((item) => <li key={item.public_id}>{item.name} · {item.case_count ?? 0} 题 · 门槛 {item.threshold?.minimum_score ?? 1}</li>)}</ul> : <RequestStateView state="empty" />}</section>
    <section className="section-block"><h2>反馈处置与聚合分析</h2>{feedback.isError ? <RequestStateView state="error" message={message(feedback.error)} onRetry={() => void feedback.refetch()} /> : <div className="data-table-wrap"><table className="data-table"><thead><tr><th>反馈</th><th>问题类型</th><th>处置</th></tr></thead><tbody>{(feedback.data?.payload.data ?? []).map((item) => <tr key={item.public_id}><td>{item.rating} · {item.note || '无说明'}</td><td>{item.issue_type || '-'}</td><td>{item.triage?.status === 'CLOSED' ? <StatusBadge status="CLOSED" /> : <button className="text-button" onClick={() => void triage(item)}>关闭</button>}</td></tr>)}</tbody></table></div>}{analytics.data ? <pre className="summary-item">{JSON.stringify(analytics.data.payload.data, null, 2)}</pre> : null}</section>
  </section>
}
