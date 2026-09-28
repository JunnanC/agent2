import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { Check, MessageSquarePlus, RefreshCw, RotateCcw, Search, Save, X } from 'lucide-react'
import { ApiError, RequestIntent, apiRequestWithMetadata } from '@edu/api-client'
import { openPortalEventStream } from '@edu/event-client'
import { reviewKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge } from '@edu/ui'

type Envelope<T> = { data: T; meta: { trace_id?: string; total?: number } }
type ReviewListItem = {
  public_id: string
  task_id: string
  publication_id: string
  publication_title: string
  student_id: string
  student_name: string
  round_no: number
  status: string
  target_kind: string
  created_at: string
  row_version: number
}
type Criterion = {
  public_id: string
  title: string
  description: string
  guidance: string
  max_score: string
  score: string | null
  note: string
  revision_no: number
}
type Annotation = {
  public_id: string
  target_type: string
  target_ref: string
  anchor: Record<string, unknown>
  status: string
  body: string
  current_revision_no: number
  row_version: number
}
type AutoCheck = {
  public_id: string
  checker_type: string
  status: string
  attempt_count: number
  result_summary: Record<string, unknown>
  evidence: Array<Record<string, unknown>>
  error_code: string
  trace_id: string
}
type SimilarityRun = {
  public_id: string
  algorithm_version: string
  threshold: string
  candidate_count: number
  status: string
  error_code: string
  trace_id: string
  retention_until: string
}
type SimilarityMatch = {
  public_id: string
  candidate_task_id: string
  candidate_student_name: string
  score: string
  evidence: Array<Record<string, unknown>>
  retention_until: string
}
type ReviewDetail = ReviewListItem & {
  scores: { criteria: Criterion[]; review_row_version: number }
  annotations: Annotation[]
  auto_checks: AutoCheck[]
  similarity_runs: SimilarityRun[]
  decision: { decision: string; score: string; feedback: string; trace_id: string } | null
  submission: {
    kind: 'REPORT' | 'SYSTEM_ARTIFACT'
    version?: { public_id: string; version_no: number; body_markdown: string; body_digest: string }
    artifact?: { public_id: string; kind: string; asset_id: string; digest_sha256: string }
  }
}

const terminalRuns = new Set(['PASSED', 'FAILED', 'COMPLETED'])

function messageFor(error: unknown): string {
  if (!(error instanceof ApiError)) return '请求未完成，请稍后重试。'
  if (error.status === 403) return '当前账号缺少课程审核权限。'
  if (error.status === 409 && error.payload.error.code === 'AUTO_CHECK_PENDING') return '自动检查尚未完成，暂时不能定案。'
  if (error.status === 409) return '审核状态已变化，请刷新后重试。'
  if (error.status === 412) return '审核已被其他教师更新，请刷新后重试。'
  return error.payload.error.message
}

function stateFor(error: unknown): 'forbidden' | 'conflict' | 'precondition' | 'error' {
  if (error instanceof ApiError && error.status === 403) return 'forbidden'
  if (error instanceof ApiError && error.status === 409) return 'conflict'
  if (error instanceof ApiError && error.status === 412) return 'precondition'
  return 'error'
}

function useReviewEvents(): void {
  const queryClient = useQueryClient()
  useEffect(() => {
    const client = openPortalEventStream((event) => {
      if (['review.decided', 'review.auto_check_completed', 'review.similarity.completed'].includes(event.type)) {
        void queryClient.invalidateQueries({ queryKey: reviewKeys.all })
      }
    })
    return () => client.stop()
  }, [queryClient])
}

export function ReviewQueuePage() {
  const { courseId = '' } = useParams()
  const [status, setStatus] = useState('')
  useReviewEvents()
  const filters = status ? { status } : {}
  const query = useQuery({
    queryKey: reviewKeys.queue(courseId, filters),
    queryFn: () => apiRequestWithMetadata<Envelope<ReviewListItem[]>>(`/api/v2/teaching/courses/${courseId}/reviews${status ? `?status=${status}` : ''}`),
  })
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state={stateFor(query.error)} message={messageFor(query.error)} traceId={query.error instanceof ApiError ? query.error.traceId : undefined} onRetry={() => void query.refetch()} />
  const values = query.data.payload.data
  return <section className="workspace-page">
    <PageHeader eyebrow="TEACHING / REVIEWS" title="教师审核" actions={<a className="text-button" href={`/courses/${courseId}`}>返回课程</a>} />
    <label className="field"><span>审核状态</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部</option><option value="PENDING">待审核</option><option value="IN_REVIEW">审核中</option><option value="DECIDED">已决定</option></select></label>
    {values.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>学生</th><th>实验发布</th><th>轮次</th><th>成果</th><th>状态</th><th>提交时间</th><th>操作</th></tr></thead><tbody>{values.map((item) => <tr key={item.public_id}><td data-wrap>{item.student_name}</td><td data-wrap>{item.publication_title}</td><td>{item.round_no}</td><td>{item.target_kind}</td><td><StatusBadge status={item.status} /></td><td>{new Date(item.created_at).toLocaleString()}</td><td><a className="text-button" href={`/courses/${courseId}/reviews/${item.public_id}`}>打开审核</a></td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}
  </section>
}

export function ReviewWorkbenchPage() {
  const { courseId = '', reviewId = '' } = useParams()
  const queryClient = useQueryClient()
  const [scores, setScores] = useState<Record<string, { score: string; note: string }>>({})
  const [feedback, setFeedback] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  useReviewEvents()
  const query = useQuery({
    queryKey: reviewKeys.detail(courseId, reviewId),
    queryFn: () => apiRequestWithMetadata<Envelope<ReviewDetail>>(`/api/v2/teaching/courses/${courseId}/reviews/${reviewId}`),
    refetchInterval: (current) => {
      const value = current.state.data?.payload.data
      const waiting = value?.auto_checks.some((item) => !terminalRuns.has(item.status)) || value?.similarity_runs.some((item) => !terminalRuns.has(item.status))
      return waiting ? 2500 : false
    },
  })
  const detail = query.data?.payload.data
  useEffect(() => {
    if (!detail) return
    setScores(Object.fromEntries(detail.scores.criteria.map((item) => [item.public_id, { score: item.score ?? '', note: item.note }])))
    setFeedback(detail.decision?.feedback ?? '')
  }, [detail])

  const total = useMemo(() => Object.values(scores).reduce((sum, item) => sum + (Number(item.score) || 0), 0), [scores])
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: reviewKeys.detail(courseId, reviewId) })
  }
  const runAction = async (operation: () => Promise<unknown>, message: string) => {
    setBusy(true); setError(''); setNotice('')
    try { await operation(); setNotice(message); await refresh() }
    catch (reason) { setError(messageFor(reason)) }
    finally { setBusy(false) }
  }
  const saveScores = () => {
    if (!detail) return Promise.resolve()
    return runAction(
      () => apiRequestWithMetadata(`/api/v2/teaching/courses/${courseId}/reviews/${reviewId}/criterion-scores`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scores: detail.scores.criteria.map((criterion) => ({ criterion_id: criterion.public_id, score: scores[criterion.public_id]?.score, note: scores[criterion.public_id]?.note })) }),
        ifMatch: query.data?.etag ?? `"${detail.row_version}"`, intent: new RequestIntent(),
      }),
      '评分已保存。',
    )
  }
  const addAnnotation = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!detail?.submission.version) return
    const element = event.currentTarget
    const form = new FormData(element)
    const body = JSON.stringify({
      target_type: 'REPORT_TEXT', target_ref: detail.submission.version.public_id,
      anchor: { kind: 'TEXT_RANGE', start: Number(form.get('start')), end: Number(form.get('end')) }, body: form.get('body'),
    })
    void runAction(
      () => apiRequestWithMetadata(`/api/v2/teaching/courses/${courseId}/reviews/${reviewId}/annotations`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, ifMatch: query.data?.etag ?? `"${detail.row_version}"`, intent: new RequestIntent() }),
      '批注已添加。',
    ).then(() => element.reset())
  }
  const reviseAnnotation = (item: Annotation) => {
    const body = window.prompt('修改批注正文', item.body)
    if (!body) return
    void runAction(
      () => apiRequestWithMetadata(`/api/v2/teaching/courses/${courseId}/reviews/${reviewId}/annotations/${item.public_id}/revisions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ body }), ifMatch: `"${item.row_version}"`, intent: new RequestIntent() }),
      '批注已修订。',
    )
  }
  const revokeAnnotation = (item: Annotation) => {
    void runAction(
      () => apiRequestWithMetadata(`/api/v2/teaching/courses/${courseId}/reviews/${reviewId}/annotations/${item.public_id}/revoke`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', ifMatch: `"${item.row_version}"`, intent: new RequestIntent() }),
      '批注已撤销。',
    )
  }
  const startSimilarity = () => {
    if (!detail) return
    void runAction(
      () => apiRequestWithMetadata(`/api/v2/teaching/courses/${courseId}/similarity-runs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ review_id: reviewId }), ifMatch: query.data?.etag ?? `"${detail.row_version}"`, intent: new RequestIntent() }),
      '相似度分析已进入队列。',
    )
  }
  const decide = (decision: 'APPROVE' | 'REJECT') => {
    if (!detail || !window.confirm(decision === 'APPROVE' ? '确认通过该成果？' : '确认退回并重新开放任务？')) return
    void runAction(
      () => apiRequestWithMetadata(`/api/v2/teaching/courses/${courseId}/reviews/${reviewId}/decide`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, score: total.toFixed(2), feedback }), ifMatch: query.data?.etag ?? `"${detail.row_version}"`, intent: new RequestIntent() }),
      decision === 'APPROVE' ? '审核已通过。' : '成果已退回。',
    )
  }

  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError || !detail) return <RequestStateView state={stateFor(query.error)} message={messageFor(query.error)} traceId={query.error instanceof ApiError ? query.error.traceId : undefined} onRetry={() => void query.refetch()} />
  const decided = detail.status === 'DECIDED'
  const latestRun = detail.similarity_runs.at(-1)
  return <section className="workspace-page">
    <PageHeader eyebrow={`REVIEW / ROUND ${detail.round_no}`} title={`${detail.student_name} · ${detail.publication_title}`} actions={<><button className="text-button" title="刷新审核" onClick={() => void query.refetch()}><RefreshCw size={16} aria-hidden="true" /> 刷新</button><a className="text-button" href={`/courses/${courseId}/reviews`}>返回队列</a></>} />
    {notice ? <p className="notice" role="status">{notice}</p> : null}{error ? <p className="form-error" role="alert">{error}</p> : null}
    <div className="summary-grid"><div className="summary-item"><span>审核状态</span><strong><StatusBadge status={detail.status} /></strong></div><div className="summary-item"><span>当前总分</span><strong>{total.toFixed(2)}</strong></div><div className="summary-item"><span>成果类型</span><strong>{detail.target_kind}</strong></div></div>
    <section className="section-block"><div className="section-heading"><h2>冻结成果</h2><span className="digest">{detail.submission.version?.body_digest ?? detail.submission.artifact?.digest_sha256}</span></div>{detail.submission.version ? <pre className="report-preview">{detail.submission.version.body_markdown}</pre> : <p>{detail.submission.artifact?.kind}</p>}</section>
    <section className="section-block"><div className="section-heading"><h2>逐项评分</h2><button className="text-button" disabled={decided || busy} onClick={() => void saveScores()}><Save size={16} aria-hidden="true" /> 保存评分</button></div><div className="data-table-wrap"><table className="data-table"><thead><tr><th>评分项</th><th>分值</th><th>评语</th></tr></thead><tbody>{detail.scores.criteria.map((criterion) => <tr key={criterion.public_id}><td data-wrap><strong>{criterion.title}</strong><br /><small>{criterion.guidance || criterion.description}</small></td><td><input aria-label={`${criterion.title}分值`} type="number" min="0" max={criterion.max_score} step="0.01" disabled={decided || busy} value={scores[criterion.public_id]?.score ?? ''} onChange={(event) => setScores((current) => ({ ...current, [criterion.public_id]: { ...(current[criterion.public_id] ?? { score: '', note: '' }), score: event.target.value } }))} /> / {criterion.max_score}</td><td><input aria-label={`${criterion.title}评语`} disabled={decided || busy} value={scores[criterion.public_id]?.note ?? ''} onChange={(event) => setScores((current) => ({ ...current, [criterion.public_id]: { ...(current[criterion.public_id] ?? { score: '', note: '' }), note: event.target.value } }))} /></td></tr>)}</tbody></table></div></section>
    <section className="section-block"><h2>批注</h2>{detail.annotations.length ? <ol className="timeline">{detail.annotations.map((item) => <li key={item.public_id}><span><StatusBadge status={item.status} /> {item.target_type} · {JSON.stringify(item.anchor)}</span><strong>{item.body || '已撤销'}</strong>{!decided && item.status === 'ACTIVE' ? <div className="toolbar"><button className="text-button" onClick={() => reviseAnnotation(item)}><MessageSquarePlus size={15} aria-hidden="true" /> 修订</button><button className="text-button text-button--danger" onClick={() => revokeAnnotation(item)}><X size={15} aria-hidden="true" /> 撤销</button></div> : null}</li>)}</ol> : <RequestStateView state="empty" />}{!decided && detail.submission.version ? <form className="form-grid" onSubmit={addAnnotation}><label className="field"><span>起始位置</span><input name="start" type="number" min="0" required /></label><label className="field"><span>结束位置</span><input name="end" type="number" min="1" required /></label><label className="field form-grid__full"><span>批注正文</span><textarea name="body" required /></label><div className="form-actions"><button className="text-button" disabled={busy} type="submit"><MessageSquarePlus size={16} aria-hidden="true" /> 添加批注</button></div></form> : null}</section>
    <section className="section-block"><div className="section-heading"><h2>自动检查</h2><span>{detail.auto_checks.length} 项</span></div>{detail.auto_checks.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>检查器</th><th>状态</th><th>尝试</th><th>结果</th><th>Trace</th></tr></thead><tbody>{detail.auto_checks.map((item) => <tr key={item.public_id}><td>{item.checker_type}</td><td><StatusBadge status={item.status} /></td><td>{item.attempt_count}</td><td data-wrap>{item.error_code || JSON.stringify(item.result_summary)}</td><td className="digest">{item.trace_id}</td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}</section>
    <SimilaritySection courseId={courseId} run={latestRun} disabled={decided || busy || !detail.submission.version} onStart={startSimilarity} />
    <section className="section-block"><h2>审核决定</h2>{detail.decision ? <div className="notice"><StatusBadge status={detail.decision.decision} /> 得分 {detail.decision.score} · {detail.decision.feedback || '无总体反馈'} · trace {detail.decision.trace_id}</div> : <><label className="field"><span>总体反馈</span><textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} /></label><div className="toolbar"><button className="primary-button" disabled={busy} onClick={() => decide('APPROVE')}><Check size={16} aria-hidden="true" /> 通过</button><button className="secondary-button" disabled={busy} onClick={() => decide('REJECT')}><RotateCcw size={16} aria-hidden="true" /> 退回</button></div></>}</section>
  </section>
}

function SimilaritySection({ courseId, run, disabled, onStart }: { courseId: string; run?: SimilarityRun; disabled: boolean; onStart: () => void }) {
  const matches = useQuery({
    queryKey: reviewKeys.similarityMatches(courseId, run?.public_id ?? ''),
    queryFn: () => apiRequestWithMetadata<Envelope<SimilarityMatch[]>>(`/api/v2/teaching/courses/${courseId}/similarity-runs/${run?.public_id}/matches`),
    enabled: run?.status === 'COMPLETED',
  })
  return <section className="section-block"><div className="section-heading"><h2>相似度分析</h2><button className="text-button" disabled={disabled} onClick={onStart}><Search size={16} aria-hidden="true" /> 运行分析</button></div>{run ? <div className="constraint-strip"><StatusBadge status={run.status} /><span>{run.algorithm_version}</span><span>阈值 {run.threshold}</span><span>候选 {run.candidate_count}</span><span>保留至 {new Date(run.retention_until).toLocaleDateString()}</span></div> : <RequestStateView state="empty" />}{matches.isPending && run?.status === 'COMPLETED' ? <RequestStateView state="loading" /> : matches.isError ? <RequestStateView state="error" onRetry={() => void matches.refetch()} /> : matches.data?.payload.data.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>候选学生</th><th>任务</th><th>相似度</th><th>证据</th></tr></thead><tbody>{matches.data.payload.data.map((item) => <tr key={item.public_id}><td>{item.candidate_student_name}</td><td>{item.candidate_task_id}</td><td>{(Number(item.score) * 100).toFixed(1)}%</td><td data-wrap>{item.evidence.length ? JSON.stringify(item.evidence) : '证据已清理'}</td></tr>)}</tbody></table></div> : null}</section>
}
