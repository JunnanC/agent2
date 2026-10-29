import { useQuery } from '@tanstack/react-query'
import { ApiError, apiRequestWithMetadata } from './legacy/api-client'
import { reviewKeys } from './legacy/query-keys'
import { PageHeader, RequestStateView, StatusBadge } from './legacy/ui'

type ReviewMonitor = {
  review_counts: Record<string, number>
  auto_check_failures: number
  similarity_counts: Record<string, number>
  latest_trace_id: string
}
type Envelope<T> = { data: T; meta: { trace_id?: string } }

export function ReviewMonitorPage() {
  const query = useQuery({
    queryKey: reviewKeys.monitor(),
    queryFn: () => apiRequestWithMetadata<Envelope<ReviewMonitor>>('/api/v2/platform/reviews/summary'),
    refetchInterval: 10000,
  })
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state={query.error instanceof ApiError && query.error.status === 403 ? 'forbidden' : 'error'} traceId={query.error instanceof ApiError ? query.error.traceId : undefined} onRetry={() => void query.refetch()} />
  const summary = query.data.payload.data
  return <section className="workspace-page">
    <PageHeader eyebrow="PLATFORM / REVIEW GOVERNANCE" title="审核监管" />
    <div className="summary-grid">
      <div className="summary-item"><span>待处理</span><strong>{(summary.review_counts.PENDING ?? 0) + (summary.review_counts.IN_REVIEW ?? 0)}</strong></div>
      <div className="summary-item"><span>已决定</span><strong>{summary.review_counts.DECIDED ?? 0}</strong></div>
      <div className="summary-item"><span>自动检查失败</span><strong>{summary.auto_check_failures}</strong></div>
    </div>
    <section className="section-block"><h2>相似度运行</h2>{Object.keys(summary.similarity_counts).length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>状态</th><th>运行数</th></tr></thead><tbody>{Object.entries(summary.similarity_counts).map(([status, count]) => <tr key={status}><td><StatusBadge status={status} /></td><td>{count}</td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}</section>
    <section className="section-block"><h2>最近 Trace</h2><p className="digest">{summary.latest_trace_id || '-'}</p></section>
  </section>
}
