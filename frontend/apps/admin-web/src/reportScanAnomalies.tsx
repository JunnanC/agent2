import { useQuery } from '@tanstack/react-query'
import { ApiError, apiRequestWithMetadata } from './legacy/api-client'
import { reportKeys } from './legacy/query-keys'
import { PageHeader, RequestStateView, StatusBadge } from './legacy/ui'

type ScanSummary = {
  counts: Record<string, number>
  items: Array<{ asset_id: string; task_id: string; scan_status: string; failure_code: string; created_at: string }>
}
type ScanSummaryResponse = { data: ScanSummary; meta: Record<string, unknown> }

export function ReportScanAnomaliesPage() {
  const query = useQuery({
    queryKey: reportKeys.scanAnomalies(),
    queryFn: () => apiRequestWithMetadata<ScanSummaryResponse>('/api/v2/platform/reports/scan-anomalies'),
  })
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state={query.error instanceof ApiError && query.error.status === 403 ? 'forbidden' : 'error'} message="扫描摘要暂时不可用。" onRetry={() => void query.refetch()} />
  const data = query.data?.payload.data
  const counts = data?.counts ?? {}
  return <section className="workspace-page">
    <PageHeader eyebrow="PLATFORM / REPORT ASSETS" title="附件扫描异常" />
    <div className="summary-grid">{Object.entries(counts).map(([status, count]) => <div className="summary-item" key={status}><span><StatusBadge status={status} /></span><strong>{count}</strong></div>)}</div>
    {data?.items.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>资产</th><th>任务</th><th>扫描</th><th>错误代码</th><th>时间</th></tr></thead><tbody>{data.items.map((item) => <tr key={item.asset_id}><td>{item.asset_id}</td><td>{item.task_id}</td><td><StatusBadge status={item.scan_status} /></td><td>{item.failure_code || '-'}</td><td>{new Date(item.created_at).toLocaleString()}</td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}
  </section>
}
