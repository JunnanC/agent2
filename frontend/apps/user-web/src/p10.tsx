import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { RotateCcw } from 'lucide-react'
import { ApiError, apiRequestWithMetadata } from '@edu/api-client'
import { openPortalEventStream } from '@edu/event-client'
import { reviewKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge } from '@edu/ui'
import { UserArchivePanel } from './p11'

type CriterionResult = { public_id: string; title: string; max_score: string; score: string | null; note: string }
type ReviewRound = {
  review_id: string
  round_no: number
  status: string
  scores: { criteria: CriterionResult[] } | null
  annotations: Array<{ public_id: string; target_type: string; anchor: Record<string, unknown>; body: string }>
  decision: { decision: string; score: string; feedback: string; created_at: string; trace_id: string } | null
}
type ReviewResult = { task_id: string; task_status: string; rounds: ReviewRound[]; allowed_actions: string[] }
type Envelope<T> = { data: T; meta: { trace_id?: string } }

export function UserReviewResultPage() {
  const { taskId = '' } = useParams()
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: reviewKeys.result(taskId),
    queryFn: () => apiRequestWithMetadata<Envelope<ReviewResult>>(`/api/v2/tasks/${encodeURIComponent(taskId)}/review-result`),
    refetchInterval: (current) => current.state.data?.payload.data.rounds.some((round) => round.status !== 'DECIDED') ? 5000 : false,
  })
  useEffect(() => {
    const client = openPortalEventStream((event) => {
      if (event.type === 'review.decided' && event.data.task_id === taskId) {
        void queryClient.invalidateQueries({ queryKey: reviewKeys.result(taskId) })
      }
    })
    return () => client.stop()
  }, [queryClient, taskId])
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) {
    const forbidden = query.error instanceof ApiError && query.error.status === 403
    return <RequestStateView state={forbidden ? 'forbidden' : 'error'} message={query.error instanceof ApiError && query.error.status === 404 ? '尚无可查看的审核结果。' : undefined} traceId={query.error instanceof ApiError ? query.error.traceId : undefined} onRetry={() => void query.refetch()} />
  }
  const result = query.data.payload.data
  return <section className="workspace-page">
    <PageHeader eyebrow="TASK / REVIEW RESULT" title="审核结果" actions={<a className="text-button" href={`/tasks/${taskId}`}>返回任务</a>} />
    <div className="summary-grid"><div className="summary-item"><span>任务状态</span><strong><StatusBadge status={result.task_status} /></strong></div><div className="summary-item"><span>审核轮次</span><strong>{result.rounds.length}</strong></div><div className="summary-item"><span>最新决定</span><strong>{result.rounds[0]?.decision ? <StatusBadge status={result.rounds[0].decision.decision} /> : '审核中'}</strong></div></div>
    {result.allowed_actions.includes('REVISE_AND_RESUBMIT') ? <div className="notice"><RotateCcw size={16} aria-hidden="true" /> 报告已重新开放。<a href={`/tasks/${taskId}/report`}>修改并重新提交</a></div> : null}
    {result.rounds.map((round) => <section className="section-block" key={round.review_id}>
      <div className="section-heading"><h2>第 {round.round_no} 轮</h2><StatusBadge status={round.decision?.decision ?? round.status} /></div>
      {round.decision ? <><div className="constraint-strip constraint-strip--valid"><span>得分 {round.decision.score}</span><span>{new Date(round.decision.created_at).toLocaleString()}</span><span className="digest">trace {round.decision.trace_id}</span></div><p>{round.decision.feedback || '无总体反馈'}</p></> : <p className="notice">教师正在审核，本轮评分和批注将在定案后显示。</p>}
      {round.scores ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>评分项</th><th>得分</th><th>反馈</th></tr></thead><tbody>{round.scores.criteria.map((criterion) => <tr key={criterion.public_id}><td data-wrap>{criterion.title}</td><td>{criterion.score} / {criterion.max_score}</td><td data-wrap>{criterion.note || '-'}</td></tr>)}</tbody></table></div> : null}
      {round.annotations.length ? <ol className="timeline">{round.annotations.map((item) => <li key={item.public_id}><span>{item.target_type} · {JSON.stringify(item.anchor)}</span><strong>{item.body}</strong></li>)}</ol> : null}
    </section>)}
    <UserArchivePanel taskId={taskId} />
  </section>
}
