import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { ApiError, apiRequestWithMetadata, type WorkspaceEnvelope, type WorkspaceOperationData, type WorkspaceSnapshotData } from '@edu/api-client'
import { workspaceKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge } from '@edu/ui'

function messageFor(error: unknown): string {
  if (!(error instanceof ApiError)) return '工作区过程数据暂时不可用。'
  if (error.status === 403) return '教师授权已撤销或当前课程不在授权范围内。'
  return error.payload.error.message
}

export function TeachingWorkspacePage() {
  const { courseId = '', taskId = '' } = useParams()
  const query = useQuery({ queryKey: workspaceKeys.teacher(courseId, taskId), queryFn: () => apiRequestWithMetadata<WorkspaceEnvelope<{ task_id: string; course_id: string; status: string; latest_snapshot: WorkspaceSnapshotData | null; snapshot_count: number }>>(`/api/v2/teaching/courses/${courseId}/tasks/${taskId}/workspace`) })
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state={query.error instanceof ApiError && query.error.status === 403 ? 'forbidden' : 'error'} message={messageFor(query.error)} onRetry={() => void query.refetch()} />
  const data = query.data?.payload.data
  return <section className="workspace-page"><PageHeader eyebrow="TEACHING / WORKSPACE" title="学生过程快照" description="只读摘要；教师不会获得工作区票据、终端凭证或代理入口。" /><div className="summary-grid"><div className="summary-item"><span>任务状态</span><strong><StatusBadge status={data?.status ?? 'UNKNOWN'} /></strong></div><div className="summary-item"><span>快照版本</span><strong>{data?.latest_snapshot ? `v${data.latest_snapshot.version_no}` : '暂无'}</strong></div><div className="summary-item"><span>保存次数</span><strong>{data?.snapshot_count ?? 0}</strong></div></div>{data?.latest_snapshot ? <section className="section-block"><h2>最新保存状态</h2><p>{new Date(data.latest_snapshot.saved_at).toLocaleString()} · {data.latest_snapshot.media_type} · {data.latest_snapshot.size_bytes} bytes</p></section> : <RequestStateView state="empty" />}</section>
}

export function TeachingWorkspaceReplayPage() {
  const { courseId = '', taskId = '' } = useParams()
  const query = useQuery({ queryKey: workspaceKeys.replay(taskId, 'teacher'), queryFn: () => apiRequestWithMetadata<WorkspaceEnvelope<{ items: WorkspaceOperationData[]; next_cursor: string | null }>>(`/api/v2/teaching/courses/${courseId}/tasks/${taskId}/operation-replay`) })
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state={query.error instanceof ApiError && query.error.status === 403 ? 'forbidden' : 'error'} message={messageFor(query.error)} onRetry={() => void query.refetch()} />
  const items = query.data?.payload.data.items ?? []
  return <section className="workspace-page"><PageHeader eyebrow="TEACHING / REPLAY" title="受控操作回放" description="按课程授权裁剪的脱敏摘要。" />{items.length ? <ol className="timeline">{items.map((item) => <li key={item.public_id}><strong>{item.event_type}</strong><span>{item.result_summary}</span><small>{new Date(item.occurred_at).toLocaleString()}</small></li>)}</ol> : <RequestStateView state="empty" />}</section>
}
