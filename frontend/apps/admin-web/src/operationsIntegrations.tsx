import { useQuery } from '@tanstack/react-query'
import { apiRequestWithMetadata, RequestIntent } from '@edu/api-client'
import { integrationKeys, notificationKeys, analyticsKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge } from '@edu/ui'

type Data = Record<string, unknown>
type ResponseData = { data: Data | Data[] }

export function OperationsIntegrationsPage() {
  const notifications = useQuery({ queryKey: notificationKeys.list('PLATFORM'), queryFn: () => apiRequestWithMetadata<ResponseData>('/api/v2/notifications') })
  const preference = useQuery({ queryKey: notificationKeys.preference('PLATFORM'), queryFn: () => apiRequestWithMetadata<ResponseData>('/api/v2/notification-preferences') })
  const operations = useQuery({ queryKey: [...analyticsKeys.all, 'operations'], queryFn: () => apiRequestWithMetadata<ResponseData>('/api/v2/platform/operations/overview') })
  const projections = useQuery({ queryKey: analyticsKeys.projections(), queryFn: () => apiRequestWithMetadata<ResponseData>('/api/v2/platform/analytics/projection-jobs') })
  const providers = useQuery({ queryKey: integrationKeys.providers(), queryFn: () => apiRequestWithMetadata<ResponseData>('/api/v2/platform/integrations/oidc-providers') })
  const clients = useQuery({ queryKey: integrationKeys.clients(), queryFn: () => apiRequestWithMetadata<ResponseData>('/api/v2/platform/integrations/api-clients') })
  const webhooks = useQuery({ queryKey: integrationKeys.deliveries(), queryFn: () => apiRequestWithMetadata<ResponseData>('/api/v2/platform/integrations/webhook-deliveries') })
  if (operations.isPending || projections.isPending || clients.isPending || webhooks.isPending || providers.isPending || notifications.isPending || preference.isPending) return <RequestStateView state="loading" />
  if (operations.isError || projections.isError || clients.isError || webhooks.isError || providers.isError || notifications.isError || preference.isError) return <RequestStateView state="error" onRetry={() => { void operations.refetch(); void projections.refetch(); void clients.refetch(); void webhooks.refetch(); void providers.refetch(); void notifications.refetch(); void preference.refetch() }} />
  const summary = operations.data?.payload.data as Data
  const projectionRows = projections.data?.payload.data as Data[]
  const clientRows = clients.data?.payload.data as Data[]
  const deliveryRows = webhooks.data?.payload.data as Data[]
  const providerRows = providers.data?.payload.data as Data[]
  const notificationRows = notifications.data?.payload.data as Data[]
  const preferenceValue = preference.data?.payload.data as Data
  const runtime = (summary?.runtime as Data | undefined) ?? {}
  const runtimeInventory = (runtime.inventory as Data | undefined) ?? {}
  const runtimeOrphans = (runtime.orphans as Data | undefined) ?? {}
  const runtimeDrivers = (runtime.drivers as Data[] | undefined) ?? []
  const savePreference = async (enabled: boolean) => {
    await apiRequestWithMetadata('/api/v2/notification-preferences', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ channels: { in_app: enabled } }), ifMatch: preferenceValue?.row_version ? `"${preferenceValue.row_version}"` : undefined, intent: new RequestIntent() })
    await preference.refetch()
  }
  return <section className="workspace-page"><PageHeader eyebrow="PLATFORM / P13" title="分析、集成与运维" description="运维摘要来自 MySQL 事实和受控运行日志；日志不可用不会阻塞业务。" />
    <section className="summary-grid"><div className="summary-item"><span>DEAD Outbox</span><strong>{String((summary?.outbox as Data)?.DEAD ?? 0)}</strong></div><div className="summary-item"><span>DEAD 补偿</span><strong>{String((summary?.compensations as Data)?.DEAD ?? 0)}</strong></div><div className="summary-item"><span>告警</span><strong>{String(((summary?.alerts as unknown[]) ?? []).length)}</strong></div></section>
    <section className="section-block"><h2>运行时库存与引擎</h2><div className="summary-grid"><div className="summary-item"><span>引擎状态</span><strong><StatusBadge status={String(runtime.status ?? '-')} /></strong></div><div className="summary-item"><span>工作区资源</span><strong>{String(runtimeInventory.runtime ?? 0)}</strong></div><div className="summary-item"><span>临时资源</span><strong>{String(runtimeInventory.transient ?? 0)}</strong></div><div className="summary-item"><span>孤儿资源</span><strong>{String(Number(runtimeOrphans.runtime ?? 0) + Number(runtimeOrphans.judge ?? 0) + Number(runtimeOrphans.volume ?? 0))}</strong></div></div><div className="data-table-wrap"><table className="data-table"><thead><tr><th>驱动</th><th>配置</th><th>健康</th></tr></thead><tbody>{runtimeDrivers.map((row) => <tr key={`${String(row.driver)}-${String(row.code)}`}><td>{String(row.driver)}</td><td>{String(row.code)}</td><td><StatusBadge status={String(row.status ?? '-')} /></td></tr>)}</tbody></table></div>{!runtimeDrivers.length ? <RequestStateView state="empty" /> : null}</section>
    <section className="section-block"><h2>投影新鲜度</h2><div className="data-table-wrap"><table className="data-table"><thead><tr><th>投影</th><th>版本</th><th>游标</th><th>计算时间</th></tr></thead><tbody>{(projectionRows ?? []).map((row) => <tr key={String(row.kind)}><td>{String(row.kind)}</td><td>{String(row.projection_version ?? '-')}</td><td data-wrap>{String(row.source_cursor ?? '-')}</td><td>{String(row.calculated_at ?? '-')}</td></tr>)}</tbody></table></div></section>
    <section className="section-block"><h2>集成管理</h2><p>OIDC Provider：{providerRows?.length ?? 0}；API Client：{clientRows?.length ?? 0}；投递记录：{deliveryRows?.length ?? 0}</p>{(providerRows ?? []).map((row) => <div className="summary-item" key={String(row.public_id)}><div className="toolbar"><strong>{String(row.name)}</strong><StatusBadge status={String(row.status)} /></div><small>{String(row.issuer)}</small></div>)}{(clientRows ?? []).map((row) => <div className="summary-item" key={String(row.public_id)}><div className="toolbar"><strong>{String(row.name)}</strong><StatusBadge status={String(row.status)} /></div><small>Scopes: {String((row.allowed_scopes as unknown[] | undefined)?.join(', ') ?? '-')} · 限流 {String(row.rate_limit_per_minute ?? '-')} / min</small></div>)}{(deliveryRows ?? []).slice(0, 8).map((row) => <div className="summary-item" key={String(row.public_id)}><div className="toolbar"><strong>{String(row.event_type)}</strong><StatusBadge status={String(row.status)} /></div><small>{String(row.last_response_masked ?? '')}</small></div>)}</section>
    <section className="section-block"><h2>通知中心</h2>{(notificationRows ?? []).slice(0, 8).map((row) => <div className="summary-item" key={String(row.public_id)}><div className="toolbar"><strong>{String(row.title)}</strong><StatusBadge status={row.read_at ? '已读' : '未读'} /></div><small>{String(row.body ?? '')}</small></div>)}{!(notificationRows ?? []).length ? <RequestStateView state="empty" /> : null}</section>
    <section className="section-block"><h2>通知偏好</h2><label className="checkbox-field"><input type="checkbox" checked={Boolean((preferenceValue?.channels as Data | undefined)?.in_app)} onChange={(event) => void savePreference(event.target.checked)} />接收站内通知</label></section>
  </section>
}
