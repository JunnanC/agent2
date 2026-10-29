import { useQuery } from '@tanstack/react-query'
import { ApiError, apiRequestWithMetadata, type WorkspaceEnvelope, type WorkspaceSessionData } from '@edu/api-client'
import { workspaceKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge } from '@edu/ui'

export function WorkspaceSessionsPage() {
  const query = useQuery({ queryKey: workspaceKeys.adminSessions(), queryFn: () => apiRequestWithMetadata<WorkspaceEnvelope<Array<WorkspaceSessionData & { public_id: string; student_id: string }>>>('/api/v2/platform/workspaces/sessions') })
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state={query.error instanceof ApiError && query.error.status === 403 ? 'forbidden' : 'error'} message="工作区会话摘要暂时不可用。" onRetry={() => void query.refetch()} />
  const items = query.data?.payload.data ?? []
  return <section className="workspace-page"><PageHeader eyebrow="PLATFORM / WORKSPACES" title="工作区会话摘要" description="仅显示状态、过期、撤销和版本摘要；不提供进入学生工作区或签发票据的入口。" /><div className="data-table-wrap"><table className="data-table"><thead><tr><th>会话</th><th>任务 / 学生</th><th>状态</th><th>过期</th><th>版本</th></tr></thead><tbody>{items.map((item) => <tr key={item.public_id}><td>{item.public_id}</td><td>{item.task_id}<br /><small>{item.student_id}</small></td><td><StatusBadge status={item.status} /></td><td>{new Date(item.expires_at).toLocaleString()}</td><td>{item.current_version}</td></tr>)}</tbody></table></div>{items.length === 0 ? <RequestStateView state="empty" /> : null}</section>
}
