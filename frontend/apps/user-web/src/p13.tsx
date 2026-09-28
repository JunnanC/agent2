import { useQuery } from '@tanstack/react-query'
import { apiRequestWithMetadata, RequestIntent } from '@edu/api-client'
import { analyticsKeys, notificationKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge } from '@edu/ui'

type RecordData = { public_id?: string; title?: string; body?: string; kind?: string; status?: string; severity?: string; explanation?: string; valid_until?: string; link_url?: string; created_at?: string; [key: string]: unknown }
type ListResponse = { data: RecordData[] }

function useP13List(path: string, queryKey: readonly unknown[]) { return useQuery({ queryKey, queryFn: () => apiRequestWithMetadata<ListResponse>(path) }) }

export function UserP13Page() {
  const notifications = useP13List('/api/v2/notifications', notificationKeys.list('USER'))
  const recommendations = useP13List('/api/v2/analytics/recommendations', analyticsKeys.recommendations())
  const risks = useP13List('/api/v2/analytics/risk-signals', analyticsKeys.risks())
  const preference = useQuery({ queryKey: notificationKeys.preference('USER'), queryFn: () => apiRequestWithMetadata<{ data: RecordData }>('/api/v2/notification-preferences') })
  if (notifications.isPending || recommendations.isPending || risks.isPending || preference.isPending) return <RequestStateView state="loading" />
  const failed = notifications.error ?? recommendations.error ?? risks.error ?? preference.error
  if (failed) return <RequestStateView state="error" onRetry={() => { void notifications.refetch(); void recommendations.refetch(); void risks.refetch(); void preference.refetch() }} />
  const items = notifications.data?.payload.data ?? []
  const markRead = async (item: RecordData) => {
    await apiRequestWithMetadata(`/api/v2/notifications/${item.public_id}/read`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', ifMatch: `"${item.row_version}"`, intent: new RequestIntent() })
    await notifications.refetch()
  }
  const savePreference = async (enabled: boolean) => {
    await apiRequestWithMetadata('/api/v2/notification-preferences', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ channels: { in_app: enabled } }), ifMatch: preference.data?.payload.data.row_version ? `"${preference.data.payload.data.row_version}"` : undefined, intent: new RequestIntent() })
    await preference.refetch()
  }
  return <section className="workspace-page"><PageHeader eyebrow="USER / INSIGHTS" title="通知与学习建议" description="建议和风险提示仅用于辅助判断，不会自动改变课程或任务状态。" />
    <section className="section-block"><h2>通知</h2>{items.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>标题</th><th>内容</th><th>状态</th><th>时间</th><th>操作</th></tr></thead><tbody>{items.map((item) => <tr key={item.public_id}><td>{item.title}</td><td data-wrap>{item.body}</td><td><StatusBadge status={item.read_at ? '已读' : '未读'} /></td><td>{item.created_at ? new Date(item.created_at).toLocaleString() : '-'}</td><td>{item.read_at ? '-' : <button className="text-button" onClick={() => void markRead(item)}>标记已读</button>}</td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}</section>
    <section className="section-block"><h2>通知偏好</h2><label className="checkbox-field"><input type="checkbox" checked={Boolean((preference.data?.payload.data.channels as Record<string, unknown> | undefined)?.in_app)} onChange={(event) => void savePreference(event.target.checked)} />接收站内通知</label></section>
    <section className="section-block"><h2>学习建议</h2>{(recommendations.data?.payload.data ?? []).map((item) => <article className="summary-item" key={item.public_id}><strong>{item.title}</strong><p>{item.explanation}</p><small>{item.kind}</small></article>)}{!(recommendations.data?.payload.data ?? []).length ? <RequestStateView state="empty" /> : null}</section>
    <section className="section-block"><h2>风险提示</h2>{(risks.data?.payload.data ?? []).map((item) => <article className="summary-item" key={item.public_id}><div className="toolbar"><StatusBadge status={item.severity ?? ''} /><StatusBadge status={item.status ?? ''} /></div><p>{item.explanation}</p></article>)}{!(risks.data?.payload.data ?? []).length ? <RequestStateView state="empty" /> : null}</section>
  </section>
}
