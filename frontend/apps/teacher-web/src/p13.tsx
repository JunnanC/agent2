import { useQuery } from '@tanstack/react-query'
import { apiRequestWithMetadata, RequestIntent } from '@edu/api-client'
import { analyticsKeys, notificationKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge } from '@edu/ui'

type RecordData = { public_id?: string; course_id?: string; student_id?: string; status?: string; severity?: string; explanation?: string; row_version?: number; metrics?: Record<string, unknown>; quality_score?: number; period_start?: string; [key: string]: unknown }
type Envelope = { data: RecordData | RecordData[] }

export function TeachingAnalyticsPage({ courseId }: { courseId: string }) {
  const notifications = useQuery({ queryKey: notificationKeys.list('TEACHING'), queryFn: () => apiRequestWithMetadata<Envelope>('/api/v2/notifications') })
  const preference = useQuery({ queryKey: notificationKeys.preference('TEACHING'), queryFn: () => apiRequestWithMetadata<Envelope>('/api/v2/notification-preferences') })
  const base = `/api/v2/teaching/courses/${courseId}/analytics`
  const overview = useQuery({ queryKey: analyticsKeys.overview(courseId), queryFn: () => apiRequestWithMetadata<Envelope>(`${base}/overview`) })
  const risks = useQuery({ queryKey: analyticsKeys.risks(courseId), queryFn: () => apiRequestWithMetadata<Envelope>(`${base}/risk-signals`) })
  const quality = useQuery({ queryKey: analyticsKeys.quality(courseId), queryFn: () => apiRequestWithMetadata<Envelope>(`${base}/quality`) })
  const costs = useQuery({ queryKey: analyticsKeys.resourceCosts(courseId), queryFn: () => apiRequestWithMetadata<Envelope>(`${base}/resource-costs`) })
  if (overview.isPending || risks.isPending || quality.isPending || costs.isPending || notifications.isPending || preference.isPending) return <RequestStateView state="loading" />
  if (overview.isError || risks.isError || quality.isError || costs.isError || notifications.isError || preference.isError) return <RequestStateView state="error" onRetry={() => { void overview.refetch(); void risks.refetch(); void quality.refetch(); void costs.refetch(); void notifications.refetch(); void preference.refetch() }} />
  const riskValues = (risks.data?.payload.data as RecordData[] | undefined) ?? []
  const resolve = async (item: RecordData, status: string) => {
    await apiRequestWithMetadata(`${base}/risk-signals/${item.public_id}/resolve`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }), ifMatch: `"${item.row_version}"`, intent: new RequestIntent() })
    await risks.refetch()
  }
  const overviewValue = overview.data?.payload.data as RecordData
  const notificationValues = (notifications.data?.payload.data as RecordData[] | undefined) ?? []
  const preferenceValue = preference.data?.payload.data as RecordData
  const savePreference = async (enabled: boolean) => {
    await apiRequestWithMetadata('/api/v2/notification-preferences', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ channels: { in_app: enabled } }), ifMatch: preferenceValue?.row_version ? `"${preferenceValue.row_version}"` : undefined, intent: new RequestIntent() })
    await preference.refetch()
  }
  return <section className="workspace-page"><PageHeader eyebrow="TEACHING / ANALYTICS" title="课程分析与风险" description="风险信号保留证据和版本信息，教师处置会写入审计。" />
    <section className="section-block"><h2>通知中心</h2>{notificationValues.length ? notificationValues.slice(0, 8).map((item) => <article className="summary-item" key={String(item.public_id)}><div className="toolbar"><strong>{String(item.title ?? '')}</strong><StatusBadge status={item.read_at ? '已读' : '未读'} /></div><p>{String(item.body ?? '')}</p></article>) : <RequestStateView state="empty" />}</section>
    <section className="section-block"><h2>通知偏好</h2><label className="checkbox-field"><input type="checkbox" checked={Boolean((preferenceValue?.channels as Record<string, unknown> | undefined)?.in_app)} onChange={(event) => void savePreference(event.target.checked)} />接收站内通知</label></section>
    <section className="summary-grid"><div className="summary-item"><span>活跃学生</span><strong>{String(overviewValue?.metrics?.active_students ?? 0)}</strong></div><div className="summary-item"><span>任务总数</span><strong>{String(overviewValue?.metrics?.task_total ?? 0)}</strong></div><div className="summary-item"><span>质量快照</span><strong>{String(((quality.data?.payload.data as RecordData[] | undefined) ?? [])[0]?.quality_score ?? 0)}</strong></div></section>
    <section className="section-block"><h2>风险信号</h2>{riskValues.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>学生</th><th>等级</th><th>说明</th><th>状态</th><th>处置</th></tr></thead><tbody>{riskValues.map((item) => <tr key={item.public_id}><td>{item.student_id}</td><td><StatusBadge status={item.severity ?? ''} /></td><td data-wrap>{item.explanation}</td><td><StatusBadge status={item.status ?? ''} /></td><td>{item.status === 'OPEN' ? <div className="toolbar"><button className="text-button" onClick={() => void resolve(item, 'ACKNOWLEDGED')}>确认</button><button className="text-button" onClick={() => void resolve(item, 'IGNORED')}>忽略</button></div> : '-'}</td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}</section>
    <section className="section-block"><h2>资源成本趋势</h2><pre className="summary-item">{JSON.stringify(costs.data?.payload.data ?? [], null, 2)}</pre></section>
  </section>
}
