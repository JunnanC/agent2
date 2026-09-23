import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ApiError,
  RequestIntent,
  apiRequestWithMetadata,
  createWorkspaceCheckpoint,
  enterWorkspace,
  getWorkspaceCheckpoints,
  restoreWorkspaceCheckpoint,
  saveWorkspaceSnapshot,
  setWorkspaceToken,
  type TaskData,
  type ApiResult,
  type WorkspaceCheckpointData,
  type WorkspaceCheckpointListData,
  type WorkspaceEnvelope,
  type WorkspaceOperationData,
  type WorkspaceSessionData,
} from '@edu/api-client'
import { experimentKeys, workspaceKeys } from '@edu/query-keys'
import { PageHeader, RequestStateView, StatusBadge } from '@edu/ui'

type QueuedDraft = { clientSeq: number; baseVersion: number; content: string }
type WorkspaceSessionResult = ApiResult<WorkspaceEnvelope<WorkspaceSessionData>>

function etagVersion(etag: string | null, fallback: number): number {
  const parsed = Number(etag?.replaceAll('"', ''))
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback
}

function cacheWorkspaceVersion(
  queryClient: QueryClient,
  taskId: string,
  currentVersion: number,
  latestClientSeq: number,
  rowVersion: number,
): void {
  queryClient.setQueryData<WorkspaceSessionResult>(workspaceKeys.session(taskId), (current) => {
    if (!current) return current
    return {
      ...current,
      payload: {
        ...current.payload,
        data: {
          ...current.payload.data,
          current_version: currentVersion,
          latest_client_seq: latestClientSeq,
          row_version: rowVersion,
        },
      },
    }
  })
}

function openQueue(taskId: string): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(`p08-workspace-drafts-${taskId}`, 1)
    request.onupgradeneeded = () => request.result.createObjectStore('queue', { keyPath: 'clientSeq' })
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

async function queueDraft(taskId: string, draft: QueuedDraft): Promise<void> {
  try {
    const db = await openQueue(taskId)
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction('queue', 'readwrite')
      tx.objectStore('queue').put(draft)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
    })
    db.close()
  } catch { /* IndexedDB is optional; the visible draft remains in React state. */ }
}

async function queuedDrafts(taskId: string): Promise<QueuedDraft[]> {
  try {
    const db = await openQueue(taskId)
    const values = await new Promise<QueuedDraft[]>((resolve, reject) => {
      const tx = db.transaction('queue', 'readonly')
      const request = tx.objectStore('queue').getAll()
      request.onsuccess = () => resolve(request.result as QueuedDraft[])
      request.onerror = () => reject(request.error)
    })
    db.close()
    return values.sort((left, right) => left.clientSeq - right.clientSeq)
  } catch { return [] }
}

async function removeQueuedDraft(taskId: string, clientSeq: number): Promise<void> {
  try {
    const db = await openQueue(taskId)
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction('queue', 'readwrite')
      tx.objectStore('queue').delete(clientSeq)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
    })
    db.close()
  } catch { /* IndexedDB is optional. */ }
}

function messageFor(error: unknown): string {
  if (!(error instanceof ApiError)) return '工作区暂时不可用，请稍后重试。'
  const code = error.payload.error.code
  if (code === 'AUTOSAVE_CONFLICT' || error.status === 412) return '服务端版本冲突：可保留服务端、保留本地，或创建新版本。'
  if (code === 'AUTOSAVE_SEQ_STALE') return '本地保存序号已过期，请刷新后继续。'
  if (error.status === 403) return '当前账号无权访问该工作区。'
  return error.payload.error.message
}

function useWorkspace(taskId: string) {
  const task = useQuery({
    queryKey: experimentKeys.task(taskId),
    queryFn: () => apiRequestWithMetadata<WorkspaceEnvelope<TaskData>>(`/api/v2/tasks/${encodeURIComponent(taskId)}`),
  })
  return useQuery({
    queryKey: workspaceKeys.session(taskId),
    queryFn: async () => {
      const item = task.data?.payload.data
      if (!item) throw new Error('任务信息尚未加载')
      if (item.status === 'READY') {
        const result = await enterWorkspace(taskId, `"${item.row_version}"`, new RequestIntent())
        return {
          ...result,
          payload: { ...result.payload, data: result.payload.data.session },
        }
      }
      if (item.status === 'IN_PROGRESS' || item.status === 'REPORT_DRAFT') {
        const result = await apiRequestWithMetadata<WorkspaceEnvelope<WorkspaceSessionData>>(`/api/v2/tasks/${encodeURIComponent(taskId)}/workspace-sessions`, { method: 'POST', intent: new RequestIntent() })
        setWorkspaceToken(result.payload.data.workspace_token)
        return result
      }
      throw new Error(`任务当前状态不允许进入工作区：${item.status}`)
    },
    retry: false,
    enabled: task.isSuccess,
  })
}

export function WorkspaceLabPage() {
  const { taskId = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const task = useQuery({ queryKey: experimentKeys.task(taskId), queryFn: () => apiRequestWithMetadata<WorkspaceEnvelope<TaskData>>(`/api/v2/tasks/${encodeURIComponent(taskId)}`) })
  const workspace = useWorkspace(taskId)
  const [content, setContent] = useState('// FakeRuntime workspace\n')
  const [saveState, setSaveState] = useState<'saved' | 'dirty' | 'saving' | 'offline' | 'conflict'>('saved')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [seq, setSeq] = useState(0)
  const [version, setVersion] = useState(0)
  const [operations, setOperations] = useState<WorkspaceOperationData[]>([])
  const flushing = useRef(false)
  const latest = useRef({ content, seq, version })
  latest.current = { content, seq, version }
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (latest.current.content && saveState === 'dirty') void save(false)
    }, 10_000)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saveState])
  const session = workspace.data?.payload.data as unknown as WorkspaceSessionData | undefined
  useEffect(() => {
    if (!session) return
    setSeq(session.latest_client_seq)
    setVersion(session.current_version)
  }, [session])
  const flushQueue = async () => {
    if (!session || flushing.current || !navigator.onLine) return
    flushing.current = true
    try {
      for (const draft of await queuedDrafts(taskId)) {
        try {
          const result = await saveWorkspaceSnapshot(taskId, { clientSeq: draft.clientSeq, baseVersion: draft.baseVersion, file: new Blob([draft.content], { type: 'text/plain' }) }, session.workspace_token)
          const snapshot = result.payload.data.snapshot
          await removeQueuedDraft(taskId, draft.clientSeq)
          cacheWorkspaceVersion(queryClient, taskId, snapshot.version_no, snapshot.client_seq, etagVersion(result.etag, session.row_version + 1))
          setSeq(snapshot.client_seq); setVersion(snapshot.version_no); setSaveState('saved')
        } catch (reason) {
          setSaveState(reason instanceof ApiError && reason.status === 412 ? 'conflict' : 'offline')
          setError(messageFor(reason))
          break
        }
      }
    } finally { flushing.current = false }
  }
  useEffect(() => {
    if (!session) return undefined
    const onOnline = () => { void flushQueue() }
    window.addEventListener('online', onOnline)
    void flushQueue()
    return () => window.removeEventListener('online', onOnline)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.public_id, taskId])
  const save = async (manual = true) => {
    if (!session) return
    const nextSeq = latest.current.seq + 1
    setSaveState('saving'); setError('')
    try {
      const result = await saveWorkspaceSnapshot(taskId, { clientSeq: nextSeq, baseVersion: latest.current.version, file: new Blob([latest.current.content], { type: 'text/plain' }) }, session.workspace_token)
      const snapshot = result.payload.data.snapshot
      cacheWorkspaceVersion(queryClient, taskId, snapshot.version_no, snapshot.client_seq, etagVersion(result.etag, session.row_version + 1))
      setSeq(snapshot.client_seq); setVersion(snapshot.version_no); setSaveState('saved')
      if (manual) setNotice('已保存到工作区对象存储。')
    } catch (reason) {
      if (!navigator.onLine) { await queueDraft(taskId, { clientSeq: nextSeq, baseVersion: latest.current.version, content: latest.current.content }); setSaveState('offline') }
      else setSaveState(reason instanceof ApiError && reason.status === 412 ? 'conflict' : 'dirty')
      setError(messageFor(reason))
    }
  }
  const operation = async (name: string) => {
    if (!session) return
    try {
      const result = await apiRequestWithMetadata<WorkspaceEnvelope<WorkspaceOperationData>>(`/workspace/${session.public_id}/operations`, { method: 'POST', body: JSON.stringify({ operation: name, arguments: { source: 'user-web' } }), headers: { 'Content-Type': 'application/json' }, workspaceToken: session.workspace_token })
      setOperations((items) => [result.payload.data, ...items]); setNotice(result.payload.data.result_summary)
    } catch (reason) { setError(messageFor(reason)) }
  }
  if (task.isPending || workspace.isPending) return <RequestStateView state="loading" />
  if (task.isError || workspace.isError || !session) return <RequestStateView state={task.error instanceof ApiError && task.error.status === 403 ? 'forbidden' : 'error'} message={messageFor(task.error ?? workspace.error)} onRetry={() => void workspace.refetch()} />
  const item = task.data?.payload.data
  return <section className="workspace-page workspace-lab">
    <PageHeader eyebrow="EXPERIMENT LAB" title={item?.title ?? '工作区'} description="FakeRuntime 受控工作区；快照和操作均可审计回放。" actions={<><button className="text-button" onClick={() => navigate(`/tasks/${taskId}/checkpoints`)}>检查点</button><button className="text-button" onClick={() => navigate(`/tasks/${taskId}/replay`)}>回放</button></>} />
    {notice ? <p className="notice" role="status">{notice}</p> : null}{error ? <p className="form-error" role="alert">{error}</p> : null}
    {saveState === 'conflict' ? <div className="conflict-actions" role="group" aria-label="版本冲突处理"><span>请选择版本处理方式：</span><button className="text-button" onClick={() => { setSaveState('saved'); setError(''); setNotice('已保留服务端版本；本地草稿仍保留在当前页面。') }}>保留服务端</button><button className="text-button" onClick={() => { setVersion(session.current_version); setSaveState('dirty'); setError(''); setNotice('已保留本地内容，可再次保存。') }}>保留本地</button><button className="primary-button" onClick={() => { setVersion(session.current_version); setSaveState('dirty'); setError(''); setNotice('已准备创建新版本。') }}>创建新版本</button></div> : null}
    <div className="summary-grid"><div className="summary-item"><span>连接</span><strong><StatusBadge status={session.status} /></strong></div><div className="summary-item"><span>保存状态</span><strong>{saveState === 'saved' ? '已保存' : saveState === 'saving' ? '保存中' : saveState === 'offline' ? '待同步' : saveState === 'conflict' ? '版本冲突' : '有未保存内容'}</strong></div><div className="summary-item"><span>工作区版本</span><strong>v{version || session.current_version}</strong></div></div>
    <div className="workspace-lab__grid"><section className="section-block"><h2>手册</h2><p>使用右侧受控操作面板完成实验步骤。浏览器不会保存工作区票据。</p><h2>IDE / 内容</h2><textarea aria-label="实验内容" value={content} onChange={(event) => { setContent(event.target.value); setSaveState('dirty') }} rows={18} /></section><section className="section-block"><h2>FakeRuntime 操作</h2><div className="toolbar"><button className="primary-button" onClick={() => void operation('RUN_CHECK')}>运行检查</button><button className="text-button" onClick={() => void operation('OPEN_PREVIEW')}>打开预览</button><button className="text-button" onClick={() => void operation('FORMAT_DOCUMENT')}>格式化</button></div><button className="primary-button" onClick={() => void save()}>立即保存</button><p className="muted">终端、IDE 凭证和真实命令不会通过此面板暴露。</p><h2>最近操作</h2>{operations.length ? <ul>{operations.map((item) => <li key={item.public_id}>{item.event_type} · {item.result_summary}</li>)}</ul> : <RequestStateView state="empty" />}</section></div>
  </section>
}

export function WorkspaceCheckpointsPage() {
  const { taskId = '' } = useParams(); const [name, setName] = useState(''); const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const queryClient = useQueryClient(); const session = useWorkspace(taskId); const item = session.data?.payload.data as unknown as WorkspaceSessionData | undefined
  const query = useQuery({ queryKey: workspaceKeys.checkpoints(taskId), queryFn: () => getWorkspaceCheckpoints(taskId), enabled: Boolean(item) })
  const create = async () => { if (!item) return; try { await createWorkspaceCheckpoint(taskId, name, item.workspace_token); setName(''); setNotice('检查点已创建。'); await query.refetch() } catch (reason) { setError(messageFor(reason)) } }
  const restore = async (checkpoint: WorkspaceCheckpointData) => { if (!item || !query.data) return; try { const result = await restoreWorkspaceCheckpoint(taskId, checkpoint.public_id, query.data.payload.data.row_version, item.workspace_token); const snapshot = result.payload.data; cacheWorkspaceVersion(queryClient, taskId, snapshot.version_no, snapshot.client_seq, etagVersion(result.etag, query.data.payload.data.row_version + 1)); setNotice(`已恢复“${checkpoint.name}”并创建 v${snapshot.version_no}。`); setError(''); await query.refetch() } catch (reason) { setError(messageFor(reason)) } }
  if (session.isPending || query.isPending) return <RequestStateView state="loading" />
  if (query.isError || !item) return <RequestStateView state="error" message={messageFor(query.error ?? session.error)} onRetry={() => void query.refetch()} />
  const data = query.data?.payload.data as WorkspaceCheckpointListData | undefined
  return <section className="workspace-page"><PageHeader eyebrow="CHECKPOINTS" title="命名检查点" description="检查点不可变，恢复会创建新的工作区版本。" actions={<a className="text-button" href={`/tasks/${taskId}/lab`}>返回实验室</a>} />{notice ? <p className="notice" role="status">{notice}</p> : null}{error ? <p className="form-error" role="alert">{error}</p> : null}<div className="toolbar"><input aria-label="检查点名称" value={name} onChange={(event) => setName(event.target.value)} placeholder="检查点名称" /><button className="primary-button" onClick={() => void create()}>创建检查点</button></div><p className="muted">当前工作区版本：v{data?.current_version ?? 0}</p><div className="data-table-wrap"><table className="data-table"><thead><tr><th>名称</th><th>版本</th><th>序号</th><th>时间</th><th>操作</th></tr></thead><tbody>{(data?.items ?? []).map((checkpoint) => <tr key={checkpoint.public_id}><td>{checkpoint.name}</td><td>v{checkpoint.version_no}</td><td>{checkpoint.source_seq}</td><td>{new Date(checkpoint.created_at).toLocaleString()}</td><td><button className="text-button" onClick={() => void restore(checkpoint)}>恢复</button></td></tr>)}</tbody></table></div></section>
}

export function WorkspaceReplayPage() {
  const { taskId = '' } = useParams()
  const query = useQuery({ queryKey: workspaceKeys.replay(taskId), queryFn: () => apiRequestWithMetadata<WorkspaceEnvelope<{ items: WorkspaceOperationData[]; next_cursor: string | null }>>(`/api/v2/tasks/${taskId}/operation-replay`) })
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state={query.error instanceof ApiError && query.error.status === 403 ? 'forbidden' : 'error'} message={messageFor(query.error)} onRetry={() => void query.refetch()} />
  const items = query.data?.payload.data.items ?? []
  return <section className="workspace-page"><PageHeader eyebrow="OPERATION REPLAY" title="工作区回放" description="仅显示当前学生可见的脱敏高层动作与结果摘要。" actions={<a className="text-button" href={`/tasks/${taskId}/lab`}>返回实验室</a>} /><ol className="timeline">{items.map((item) => <li key={item.public_id}><strong>{item.event_type}</strong><span>{item.result_summary}</span><small>{new Date(item.occurred_at).toLocaleString()} · {item.trace_id}</small></li>)}</ol>{items.length === 0 ? <RequestStateView state="empty" /> : null}</section>
}
