import { useQuery } from '@tanstack/react-query'
import { apiRequestWithMetadata, type PlatformPrecheckSummaryResponse } from '@edu/api-client'
import { templateKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge } from '@edu/ui'

export function PrecheckSummaryPage() {
  const query = useQuery({ queryKey: templateKeys.platformSummary(), queryFn: () => apiRequestWithMetadata<PlatformPrecheckSummaryResponse>('/api/v2/platform/template-prechecks/summary') })
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state="error" onRetry={() => void query.refetch()} />
  const summary = query.data?.payload.data ?? {}; const prechecks = (summary.precheck_counts ?? {}) as Record<string, number>; const images = (summary.image_counts ?? {}) as Record<string, number>; const failures = Array.isArray(summary.recent_failures) ? summary.recent_failures as Array<Record<string, unknown>> : []
  return <section className="workspace-page"><PageHeader eyebrow="PLATFORM / TEMPLATE PRECHECKS" title="预检监管" description="只读汇总与脱敏失败事实；平台管理员不能代替教师修改或发布。" /><div className="summary-grid"><div className="summary-item"><span>预检通过</span><strong>{prechecks.PASSED ?? 0}</strong></div><div className="summary-item"><span>预检失败</span><strong>{prechecks.FAILED ?? 0}</strong></div><div className="summary-item"><span>批准镜像</span><strong>{images.APPROVED ?? 0}</strong></div></div><section className="section-block"><h2>预检状态计数</h2><div className="data-table-wrap"><table className="data-table"><thead><tr><th>状态</th><th>数量</th></tr></thead><tbody>{Object.entries(prechecks).map(([status, count]) => <tr key={status}><td><StatusBadge status={status} /></td><td>{count}</td></tr>)}</tbody></table></div></section><section className="section-block"><h2>近期失败</h2>{failures.length === 0 ? <RequestStateView state="empty" /> : <div className="data-table-wrap"><table className="data-table"><thead><tr><th>阶段</th><th>错误</th><th>模板版本</th><th>Trace</th></tr></thead><tbody>{failures.map((failure, index) => <tr key={index}><td>{String(failure.current_stage ?? '-')}</td><td>{String(failure.error_code ?? '-')}</td><td><code>{String(failure.template_version_id ?? '-')}</code></td><td><code>{String(failure.trace_id ?? '-')}</code></td></tr>)}</tbody></table></div>}</section></section>
}
