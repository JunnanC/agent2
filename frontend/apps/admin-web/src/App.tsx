import { useState, type FormEvent, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import {
  ApiError,
  RequestIntent,
  apiRequestWithMetadata,
  type AdminAssignmentData,
  type AlertListResponse,
  type AllowlistData,
  type AllowlistListResponse,
  type CourseListResponse,
  type ImageData,
  type ImageListResponse,
  type ListEnvelope,
  type PolicyData,
  type PolicyListResponse,
  type QuotaData,
  type QuotaListResponse,
  type QualificationData,
  type ResourceProfileData,
  type ResourceProfileListResponse,
  type RuntimeAdapterData,
  type RuntimeAdapterListResponse,
  type UsageResponse,
  type UserData,
  type VerificationData,
} from '@edu/api-client'
import { useSession } from '@edu/auth-client'
import { accountKeys, courseKeys, governanceKeys } from '@edu/query-keys'
import { AppErrorBoundary, LoginForm, PageHeader, PortalLayout, RequestStateView, StatusBadge, TextField } from '@edu/ui'
import { PrecheckSummaryPage } from './p05'

const release = { version: import.meta.env.VITE_APP_VERSION ?? '0.6.0-p05', openapiRevision: import.meta.env.VITE_OPENAPI_REVISION ?? 'v2-p05', gitRevision: import.meta.env.VITE_GIT_REVISION ?? 'development', buildTime: import.meta.env.VITE_BUILD_TIME ?? 'development' }
const tabs = [{ href: '/users', label: '用户' }, { href: '/teachers', label: '教师资格' }, { href: '/admins', label: '管理员资格' }, { href: '/verifications', label: '身份审核' }, { href: '/courses', label: '课程监管' }, { href: '/runtimes', label: '运行时' }, { href: '/images', label: '镜像' }, { href: '/resource-profiles', label: '资源规格' }, { href: '/quotas', label: '配额' }, { href: '/security', label: '安全策略' }, { href: '/template-prechecks', label: '模板预检' }]

function messageFor(error: unknown): string {
  if (!(error instanceof ApiError)) return '请求未完成，请稍后重试。'
  return error.payload.error.message
}

function LoginPage() {
  const session = useSession(); const navigate = useNavigate(); const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  if (session.status === 'authenticated') return <Navigate to="/users" replace />
  const submit = async (identifier: string, password: string) => {
    setBusy(true); setError('')
    try { await session.signIn({ identifier, password }); navigate('/users') }
    catch (reason) { setError(messageFor(reason)) }
    finally { setBusy(false) }
  }
  return <LoginForm title="管理端" busy={busy} error={error} onSubmit={submit} />
}

function Guard({ children }: { children: ReactNode }) {
  const session = useSession(); const location = useLocation()
  if (session.status === 'loading') return <RequestStateView state="loading" />
  if (session.status === 'anonymous') return <Navigate to="/login" state={{ from: location }} replace />
  if (session.status === 'denied') return <RequestStateView state="forbidden" title="需要平台管理员资格" message="管理员资格撤销后，原管理端会话会立即失效。" />
  if (session.status === 'error') return <RequestStateView state="error" traceId={session.error?.traceId} onRetry={() => void session.refresh()} />
  return children
}

function Tabs() {
  const location = useLocation()
  return <nav className="tabs" aria-label="账号治理视图">{tabs.map((tab) => <a key={tab.href} href={tab.href} aria-current={location.pathname === tab.href ? 'page' : undefined}>{tab.label}</a>)}</nav>
}

function AsyncState({ query, children }: { query: { isPending: boolean; isError: boolean; refetch: () => unknown }; children: ReactNode }) {
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state="error" onRetry={() => void query.refetch()} />
  return children
}

function UsersPage() {
  const queryClient = useQueryClient(); const [error, setError] = useState(''); const [showCreate, setShowCreate] = useState(false)
  const query = useQuery({ queryKey: accountKeys.users(), queryFn: () => apiRequestWithMetadata<ListEnvelope<UserData>>('/api/v2/platform/users') })
  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(''); const form = new FormData(event.currentTarget)
    try {
      await apiRequestWithMetadata('/api/v2/platform/users', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(form)), intent: new RequestIntent() })
      event.currentTarget.reset(); setShowCreate(false); await queryClient.invalidateQueries({ queryKey: accountKeys.users() })
    } catch (reason) { setError(messageFor(reason)) }
  }
  const changeStatus = async (user: UserData) => {
    const next = user.account_status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE'
    if (!window.confirm(`确认将 ${user.display_name} 设置为 ${next}？`)) return
    try {
      await apiRequestWithMetadata(`/api/v2/platform/users/${user.public_id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ account_status: next, reason: '管理员账号治理操作' }), ifMatch: `"${user.row_version}"` })
      await queryClient.invalidateQueries({ queryKey: accountKeys.users() })
    } catch (reason) { setError(messageFor(reason)) }
  }
  const grant = async (user: UserData, kind: 'teacher' | 'admin') => {
    const suffix = kind === 'teacher' ? 'teacher-qualification' : 'admin-assignment'
    try {
      await apiRequestWithMetadata(`/api/v2/platform/users/${user.public_id}/${suffix}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: '管理员授予资格' }), ifMatch: `"${user.row_version}"`, intent: new RequestIntent() })
      await queryClient.invalidateQueries({ queryKey: kind === 'teacher' ? accountKeys.teachers() : accountKeys.admins() })
    } catch (reason) { setError(messageFor(reason)) }
  }
  const values = query.data?.payload.data ?? []
  return <section className="workspace-page"><PageHeader eyebrow="PLATFORM ACCOUNTS" title="用户账号" description="创建、停用、恢复账号并授予门户资格。" actions={<button className="text-button" onClick={() => setShowCreate((value) => !value)}>新建账号</button>} /><Tabs />
    {error ? <p className="form-error" role="alert">{error}</p> : null}
    {showCreate ? <section className="section-block"><h2>新建账号</h2><form className="form-grid" onSubmit={create}><TextField label="邮箱" name="email" type="email" required /><TextField label="用户名" name="username" required /><TextField label="展示名称" name="display_name" required /><TextField label="初始密码" name="password" type="password" minLength={12} required /><div className="form-actions"><button className="primary-button" type="submit">创建</button></div></form></section> : null}
    <AsyncState query={query}>{values.length === 0 ? <RequestStateView state="empty" /> : <div className="data-table-wrap"><table className="data-table"><thead><tr><th>用户</th><th>用户名</th><th>状态</th><th>版本</th><th>操作</th></tr></thead><tbody>{values.map((user) => <tr key={user.public_id}><td data-wrap><strong>{user.display_name}</strong><br />{user.email}</td><td>{user.username}</td><td><StatusBadge status={user.account_status} /></td><td>{user.row_version}</td><td><div className="toolbar"><button className={user.account_status === 'ACTIVE' ? 'text-button text-button--danger' : 'text-button'} onClick={() => void changeStatus(user)}>{user.account_status === 'ACTIVE' ? '停用' : '恢复'}</button><button className="text-button" onClick={() => void grant(user, 'teacher')}>授予教师</button><button className="text-button" onClick={() => void grant(user, 'admin')}>授予管理员</button></div></td></tr>)}</tbody></table></div>}</AsyncState>
  </section>
}

function TeachersPage() {
  const queryClient = useQueryClient(); const [error, setError] = useState('')
  const query = useQuery({ queryKey: accountKeys.teachers(), queryFn: () => apiRequestWithMetadata<ListEnvelope<QualificationData>>('/api/v2/platform/teacher-qualifications') })
  const change = async (value: QualificationData, status: 'SUSPENDED' | 'REVOKED') => {
    if (!window.confirm(`确认将 ${value.display_name} 的教师资格设置为 ${status}？`)) return
    try {
      await apiRequestWithMetadata(`/api/v2/platform/teacher-qualifications/${value.public_id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status, reason: '管理员资格治理操作' }), ifMatch: `"${value.row_version}"` })
      await queryClient.invalidateQueries({ queryKey: accountKeys.teachers() })
    } catch (reason) { setError(messageFor(reason)) }
  }
  const values = query.data?.payload.data ?? []
  return <section className="workspace-page"><PageHeader eyebrow="QUALIFICATIONS" title="教师资格" description="暂停会立即禁止教师端访问；撤销在 P03 接入课程负责人阻断。" /><Tabs />{error ? <p className="form-error">{error}</p> : null}<AsyncState query={query}>{values.length === 0 ? <RequestStateView state="empty" /> : <div className="data-table-wrap"><table className="data-table"><thead><tr><th>教师</th><th>状态</th><th>原因</th><th>操作</th></tr></thead><tbody>{values.map((value) => <tr key={value.public_id}><td>{value.display_name}</td><td><StatusBadge status={value.status} /></td><td data-wrap>{value.reason}</td><td><div className="toolbar">{value.status === 'ACTIVE' ? <button className="text-button" onClick={() => void change(value, 'SUSPENDED')}>暂停</button> : null}{value.status !== 'REVOKED' ? <button className="text-button text-button--danger" onClick={() => void change(value, 'REVOKED')}>撤销</button> : null}</div></td></tr>)}</tbody></table></div>}</AsyncState></section>
}

function AdminsPage() {
  const queryClient = useQueryClient(); const [error, setError] = useState('')
  const query = useQuery({ queryKey: accountKeys.admins(), queryFn: () => apiRequestWithMetadata<ListEnvelope<AdminAssignmentData>>('/api/v2/platform/admin-assignments') })
  const revoke = async (value: AdminAssignmentData) => {
    if (!window.confirm(`确认撤销 ${value.display_name} 的管理员资格？最后一名管理员不可撤销。`)) return
    try {
      await apiRequestWithMetadata(`/api/v2/platform/admin-assignments/${value.public_id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'REVOKED', reason: '管理员资格治理操作' }), ifMatch: `"${value.row_version}"` })
      await queryClient.invalidateQueries({ queryKey: accountKeys.admins() })
    } catch (reason) { setError(messageFor(reason)) }
  }
  const values = query.data?.payload.data ?? []
  return <section className="workspace-page"><PageHeader eyebrow="PLATFORM ACCESS" title="管理员资格" description="管理员资格与教师资格独立维护。" /><Tabs />{error ? <p className="form-error">{error}</p> : null}<AsyncState query={query}>{values.length === 0 ? <RequestStateView state="empty" /> : <div className="data-table-wrap"><table className="data-table"><thead><tr><th>管理员</th><th>状态</th><th>授予时间</th><th>操作</th></tr></thead><tbody>{values.map((value) => <tr key={value.public_id}><td>{value.display_name}</td><td><StatusBadge status={value.status} /></td><td>{new Date(value.granted_at).toLocaleString()}</td><td>{value.status === 'ACTIVE' ? <button className="text-button text-button--danger" onClick={() => void revoke(value)}>撤销</button> : null}</td></tr>)}</tbody></table></div>}</AsyncState></section>
}

function VerificationsPage() {
  const queryClient = useQueryClient(); const [error, setError] = useState('')
  const query = useQuery({ queryKey: accountKeys.verifications(), queryFn: () => apiRequestWithMetadata<ListEnvelope<VerificationData>>('/api/v2/platform/verifications') })
  const review = async (value: VerificationData, decision: 'APPROVE' | 'REJECT') => {
    const reason = decision === 'REJECT' ? window.prompt('请输入拒绝原因') : ''
    if (decision === 'REJECT' && !reason) return
    try {
      await apiRequestWithMetadata(`/api/v2/platform/verifications/${value.public_id}/review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, reason }), ifMatch: `"${value.row_version}"`, intent: new RequestIntent() })
      await queryClient.invalidateQueries({ queryKey: accountKeys.verifications() })
    } catch (cause) { setError(messageFor(cause)) }
  }
  const values = query.data?.payload.data ?? []
  return <section className="workspace-page"><PageHeader eyebrow="IDENTITY REVIEW" title="身份审核" description="证件原值不会出现在响应、日志或审计中。" /><Tabs />{error ? <p className="form-error">{error}</p> : null}<AsyncState query={query}>{values.length === 0 ? <RequestStateView state="empty" /> : <div className="data-table-wrap"><table className="data-table"><thead><tr><th>用户</th><th>类型</th><th>机构</th><th>证件掩码</th><th>状态</th><th>操作</th></tr></thead><tbody>{values.map((value) => <tr key={value.public_id}><td>{value.user_id}</td><td>{value.identity_type}</td><td data-wrap>{value.organization_name}</td><td>{value.identity_number_masked || '-'}</td><td><StatusBadge status={value.status} /></td><td>{value.status === 'SUBMITTED' ? <div className="toolbar"><button className="text-button" onClick={() => void review(value, 'APPROVE')}>通过</button><button className="text-button text-button--danger" onClick={() => void review(value, 'REJECT')}>拒绝</button></div> : null}</td></tr>)}</tbody></table></div>}</AsyncState></section>
}

function CoursesPage() {
  const query = useQuery({ queryKey: courseKeys.catalog({ portal: 'PLATFORM' }), queryFn: () => apiRequestWithMetadata<CourseListResponse>('/api/v2/platform/courses') })
  const values = query.data?.payload.data ?? []
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state="error" onRetry={() => void query.refetch()} />
  return <section className="workspace-page"><PageHeader eyebrow="COURSE GOVERNANCE" title="课程监管" description="管理端只读取课程监管事实；教学审批仍由教师端完成。" />{values.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>课程</th><th>负责人</th><th>状态</th><th>治理入口</th></tr></thead><tbody>{values.map((course) => <tr key={course.public_id}><td data-wrap><strong>{course.title}</strong><br />{course.code}</td><td>{course.owner_name}</td><td><StatusBadge status={course.status} /></td><td><button className="text-button" disabled title="治理冻结能力尚未开放">冻结入口（不可用）</button></td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}</section>
}

function GovernanceError({ error, retry }: { error: unknown; retry: () => void }) {
  if (error instanceof ApiError && error.status === 403) return <RequestStateView state="forbidden" message={messageFor(error)} />
  if (error instanceof ApiError && error.status === 409) return <RequestStateView state="conflict" message={messageFor(error)} onRetry={retry} />
  if (error instanceof ApiError && error.status === 412) return <RequestStateView state="precondition" message={messageFor(error)} onRetry={retry} />
  return <RequestStateView state="error" message={messageFor(error)} onRetry={retry} />
}

function RuntimesPage() {
  const queryClient = useQueryClient(); const [error, setError] = useState(''); const [showCreate, setShowCreate] = useState(false)
  const query = useQuery({ queryKey: governanceKeys.runtimes(), queryFn: () => apiRequestWithMetadata<RuntimeAdapterListResponse>('/api/v2/platform/runtime-adapters') })
  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(''); const form = new FormData(event.currentTarget)
    try { await apiRequestWithMetadata('/api/v2/platform/runtime-adapters', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(form)), intent: new RequestIntent() }); event.currentTarget.reset(); setShowCreate(false); await queryClient.invalidateQueries({ queryKey: governanceKeys.runtimes() }) } catch (reason) { setError(messageFor(reason)) }
  }
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <GovernanceError error={query.error} retry={() => void query.refetch()} />
  const values = query.data?.payload.data ?? []
  return <section className="workspace-page"><PageHeader eyebrow="GOVERNANCE / RUNTIMES" title="运行时目录" description="维护运行时能力和健康快照；P04 不创建容器。" actions={<button className="text-button" onClick={() => setShowCreate((value) => !value)}>新建运行时</button>} /><Tabs />{error ? <p className="form-error" role="alert">{error}</p> : null}{showCreate ? <section className="section-block"><h2>登记运行时</h2><form className="form-grid" onSubmit={create}><TextField label="编码" name="code" required /><TextField label="名称" name="name" required /><label className="field"><span>类型</span><select name="runtime_type" defaultValue="CONTAINER"><option value="CONTAINER">容器</option><option value="VM">虚拟机</option></select></label><label className="field"><span>驱动</span><select name="driver" defaultValue="FAKE"><option value="FAKE">Fake</option><option value="DOCKER_SWARM">Docker Swarm</option><option value="LIBVIRT">Libvirt</option></select></label><TextField label="配置引用" name="config_ref" /><TextField label="变更原因" name="reason" required /><div className="form-actions"><button className="primary-button" type="submit">登记</button></div></form></section> : null}<div className="data-table-wrap"><table className="data-table"><thead><tr><th>运行时</th><th>类型/驱动</th><th>状态</th><th>健康</th><th>容量</th></tr></thead><tbody>{values.map((item: RuntimeAdapterData) => <tr key={item.public_id}><td data-wrap><strong>{item.name}</strong><br />{item.code}</td><td>{item.runtime_type} / {item.driver}</td><td><StatusBadge status={item.status} /></td><td><StatusBadge status={item.health_status} /></td><td>{item.available_cpu_millicores} / {item.capacity_cpu_millicores} mCPU</td></tr>)}</tbody></table></div>{values.length === 0 ? <RequestStateView state="empty" /> : null}</section>
}

function ImagesPage() {
  const queryClient = useQueryClient(); const [error, setError] = useState(''); const [showCreate, setShowCreate] = useState(false)
  const query = useQuery({ queryKey: governanceKeys.images(), queryFn: () => apiRequestWithMetadata<ImageListResponse>('/api/v2/platform/images') })
  const create = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setError(''); const form = new FormData(event.currentTarget); try { await apiRequestWithMetadata('/api/v2/platform/images', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(form)), intent: new RequestIntent() }); event.currentTarget.reset(); setShowCreate(false); await queryClient.invalidateQueries({ queryKey: governanceKeys.images() }) } catch (reason) { setError(messageFor(reason)) } }
  const decide = async (item: ImageData, decision: 'APPROVED' | 'REJECTED' | 'RETIRED') => { const reason = window.prompt('请输入变更原因'); if (!reason) return; setError(''); try { await apiRequestWithMetadata(`/api/v2/platform/images/${item.public_id}/decide`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, reason }), ifMatch: `"${item.row_version}"`, intent: new RequestIntent() }); await queryClient.invalidateQueries({ queryKey: governanceKeys.images() }) } catch (cause) { setError(messageFor(cause)) } }
  if (query.isPending) return <RequestStateView state="loading" />; if (query.isError) return <GovernanceError error={query.error} retry={() => void query.refetch()} />
  const values = query.data?.payload.data ?? []
  return <section className="workspace-page"><PageHeader eyebrow="GOVERNANCE / IMAGES" title="镜像目录" description="digest 是不可漂移的运行事实，tag 仅用于展示。" actions={<button className="text-button" onClick={() => setShowCreate((value) => !value)}>登记镜像</button>} /><Tabs />{error ? <p className="form-error" role="alert">{error}</p> : null}{showCreate ? <section className="section-block"><h2>登记镜像 digest</h2><form className="form-grid" onSubmit={create}><TextField label="镜像仓库" name="registry" required /><TextField label="仓库路径" name="repository" required /><TextField label="展示 tag" name="display_tag" /><TextField label="digest" name="digest" pattern="sha256:[a-fA-F0-9]{64}" required /><label className="field"><span>风险等级</span><select name="risk_level" defaultValue="LOW"><option value="LOW">低</option><option value="MEDIUM">中</option><option value="HIGH">高</option></select></label><TextField label="变更原因" name="reason" required /><div className="form-actions"><button className="primary-button" type="submit">登记</button></div></form></section> : null}<div className="data-table-wrap"><table className="data-table"><thead><tr><th>镜像</th><th>digest</th><th>扫描</th><th>批准</th><th>操作</th></tr></thead><tbody>{values.map((item: ImageData) => <tr key={item.public_id}><td data-wrap><strong>{item.repository}</strong><br />{item.display_tag || '-'}</td><td>{item.digest.slice(0, 18)}...</td><td><StatusBadge status={item.scan_status} /></td><td><StatusBadge status={item.approval_status} /></td><td>{item.approval_status === 'PENDING' ? <button className="text-button" onClick={() => void decide(item, 'APPROVED')}>批准</button> : null}</td></tr>)}</tbody></table></div>{values.length === 0 ? <RequestStateView state="empty" /> : null}</section>
}

function ResourceProfilesPage() {
  const queryClient = useQueryClient(); const [error, setError] = useState(''); const [showCreate, setShowCreate] = useState(false)
  const query = useQuery({ queryKey: governanceKeys.profiles(), queryFn: () => apiRequestWithMetadata<ResourceProfileListResponse>('/api/v2/platform/resource-profiles') })
  const create = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setError(''); const form = new FormData(event.currentTarget); try { await apiRequestWithMetadata('/api/v2/platform/resource-profiles', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(form)), intent: new RequestIntent() }); event.currentTarget.reset(); setShowCreate(false); await queryClient.invalidateQueries({ queryKey: governanceKeys.profiles() }) } catch (reason) { setError(messageFor(reason)) } }
  const activate = async (item: ResourceProfileData) => { const reason = window.prompt('请输入激活原因'); if (!reason) return; try { await apiRequestWithMetadata(`/api/v2/platform/resource-profiles/${item.public_id}/activate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason }), ifMatch: `"${item.row_version}"`, intent: new RequestIntent() }); await queryClient.invalidateQueries({ queryKey: governanceKeys.profiles() }) } catch (cause) { setError(messageFor(cause)) } }
  if (query.isPending) return <RequestStateView state="loading" />; if (query.isError) return <GovernanceError error={query.error} retry={() => void query.refetch()} />; const values = query.data?.payload.data ?? []
  return <section className="workspace-page"><PageHeader eyebrow="GOVERNANCE / PROFILES" title="资源规格" description="ACTIVE 规格冻结；后续变更创建新规格。" actions={<button className="text-button" onClick={() => setShowCreate((value) => !value)}>新建规格</button>} /><Tabs />{error ? <p className="form-error" role="alert">{error}</p> : null}{showCreate ? <section className="section-block"><h2>新建资源规格</h2><form className="form-grid" onSubmit={create}><TextField label="编码" name="code" required /><TextField label="名称" name="name" required /><TextField label="CPU mCPU" name="cpu_millicores" type="number" min="1" required /><TextField label="内存 MB" name="memory_mb" type="number" min="1" required /><TextField label="磁盘 GB" name="disk_gb" type="number" min="1" required /><label className="field"><span>网络模式</span><select name="network_mode" defaultValue="DENY_ALL"><option value="DENY_ALL">禁止出网</option><option value="ALLOWLIST">白名单</option></select></label><TextField label="变更原因" name="reason" required /><div className="form-actions"><button className="primary-button" type="submit">保存草稿</button></div></form></section> : null}<div className="data-table-wrap"><table className="data-table"><thead><tr><th>规格</th><th>资源</th><th>网络</th><th>状态</th><th>操作</th></tr></thead><tbody>{values.map((item: ResourceProfileData) => <tr key={item.public_id}><td data-wrap><strong>{item.name}</strong><br />{item.code}</td><td>{item.cpu_millicores} mCPU / {item.memory_mb} MB / {item.disk_gb} GB</td><td>{item.network_mode}</td><td><StatusBadge status={item.status} /></td><td>{item.status === 'DRAFT' ? <button className="text-button" onClick={() => void activate(item)}>激活</button> : null}</td></tr>)}</tbody></table></div>{values.length === 0 ? <RequestStateView state="empty" /> : null}</section>
}

function QuotasPage() {
  const queryClient = useQueryClient(); const [error, setError] = useState(''); const [showCreate, setShowCreate] = useState(false)
  const query = useQuery({ queryKey: governanceKeys.quotas(), queryFn: () => apiRequestWithMetadata<QuotaListResponse>('/api/v2/platform/quotas') })
  const create = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setError(''); const form = new FormData(event.currentTarget); const raw = Object.fromEntries(form); const body = { ...raw, max_concurrent_instances: Number(raw.max_concurrent_instances), max_cpu_millicores: Number(raw.max_cpu_millicores) }; try { await apiRequestWithMetadata('/api/v2/platform/quotas', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), intent: new RequestIntent() }); event.currentTarget.reset(); setShowCreate(false); await queryClient.invalidateQueries({ queryKey: governanceKeys.quotas() }) } catch (reason) { setError(messageFor(reason)) } }
  if (query.isPending) return <RequestStateView state="loading" />; if (query.isError) return <GovernanceError error={query.error} retry={() => void query.refetch()} />; const values = query.data?.payload.data ?? []
  return <section className="workspace-page"><PageHeader eyebrow="GOVERNANCE / QUOTAS" title="三级配额" description="平台、课程和用户配额由 MySQL 事实计算，缺省时继承上层。" actions={<button className="text-button" onClick={() => setShowCreate((value) => !value)}>新增配额</button>} /><Tabs />{error ? <p className="form-error" role="alert">{error}</p> : null}{showCreate ? <section className="section-block"><h2>新增平台配额</h2><form className="form-grid" onSubmit={create}><input type="hidden" name="scope_type" value="PLATFORM" /><TextField label="并发实例" name="max_concurrent_instances" type="number" min="1" required /><TextField label="CPU mCPU" name="max_cpu_millicores" type="number" min="1" required /><TextField label="变更原因" name="reason" required /><div className="form-actions"><button className="primary-button" type="submit">保存配额</button></div></form></section> : null}<div className="data-table-wrap"><table className="data-table"><thead><tr><th>范围</th><th>实例</th><th>CPU</th><th>内存</th><th>版本</th></tr></thead><tbody>{values.map((item: QuotaData) => <tr key={item.public_id}><td>{item.scope_type}<br /><small>{item.course_id || item.user_id || 'PLATFORM'}</small></td><td>{item.max_concurrent_instances ?? '继承'}</td><td>{item.max_cpu_millicores ?? '继承'} mCPU</td><td>{item.max_memory_mb ?? '继承'} MB</td><td>{item.row_version}</td></tr>)}</tbody></table></div>{values.length === 0 ? <RequestStateView state="empty" /> : null}</section>
}

function SecurityPage() {
  const queryClient = useQueryClient(); const [error, setError] = useState(''); const [message, setMessage] = useState('')
  const policiesQuery = useQuery({ queryKey: governanceKeys.policies(), queryFn: () => apiRequestWithMetadata<PolicyListResponse>('/api/v2/platform/security-policies') })
  const scalingQuery = useQuery({ queryKey: governanceKeys.policies('RESOURCE_SCALING'), queryFn: () => apiRequestWithMetadata<PolicyListResponse>('/api/v2/platform/resource-scaling-policies') })
  const allowlistQuery = useQuery({ queryKey: governanceKeys.allowlists(), queryFn: () => apiRequestWithMetadata<AllowlistListResponse>('/api/v2/platform/network-allowlists') })
  const usageQuery = useQuery({ queryKey: governanceKeys.usage(), queryFn: () => apiRequestWithMetadata<UsageResponse>('/api/v2/platform/governance/usage') })
  const alertsQuery = useQuery({ queryKey: governanceKeys.alerts(), queryFn: () => apiRequestWithMetadata<AlertListResponse>('/api/v2/platform/governance/alerts') })
  const savePolicy = async (event: FormEvent<HTMLFormElement>, kind: 'security' | 'scaling') => { event.preventDefault(); setError(''); setMessage(''); const form = new FormData(event.currentTarget); const rules = kind === 'security' ? { default_egress: 'DENY_ALL', allow_privileged: false, require_workspace_gateway: true } : { prewarm_enabled: true, min_replicas: 0, max_replicas: 2, cooldown_seconds: 300, idle_reclaim_seconds: 1800, budget_minor: 10000 }; try { await apiRequestWithMetadata(`/api/v2/platform/${kind === 'security' ? 'security-policies' : 'resource-scaling-policies'}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scope_type: 'PLATFORM', risk_level: 'HIGH', rules, reason: form.get('reason') }), intent: new RequestIntent() }); setMessage('策略已提交，审计与 Outbox 已记录。'); await Promise.all([queryClient.invalidateQueries({ queryKey: governanceKeys.policies() }), queryClient.invalidateQueries({ queryKey: governanceKeys.policies('RESOURCE_SCALING') })]) } catch (cause) { setError(messageFor(cause)) } }
  const busy = policiesQuery.isPending || scalingQuery.isPending || allowlistQuery.isPending || usageQuery.isPending || alertsQuery.isPending
  if (busy) return <RequestStateView state="loading" />
  const failedQuery = [policiesQuery, scalingQuery, allowlistQuery, usageQuery, alertsQuery].find((candidate) => candidate.isError)
  if (failedQuery?.isError) return <GovernanceError error={failedQuery.error} retry={() => void failedQuery.refetch()} />
  const policies = policiesQuery.data?.payload.data ?? []; const scaling = scalingQuery.data?.payload.data ?? []; const allowlist = allowlistQuery.data?.payload.data ?? []; const usage = usageQuery.data?.payload.data; const alerts = alertsQuery.data?.payload.data ?? []
  return <section className="workspace-page"><PageHeader eyebrow="GOVERNANCE / SECURITY" title="安全与策略护栏" description="安全策略、网络白名单、预热、扩缩容和预算共用治理事实表。" /><Tabs />{message ? <p className="notice" role="status">{message}</p> : null}{error ? <p className="form-error" role="alert">{error}</p> : null}<div className="summary-grid"><div className="summary-item"><span>当前预留实例</span><strong>{usage?.reservation.instance_count ?? 0}</strong></div><div className="summary-item"><span>对象存储</span><strong>{usage?.object_storage_bytes ?? 0} B</strong></div><div className="summary-item"><span>告警摘要</span><strong>{alerts.length}</strong></div></div><section className="section-block"><h2>安全策略</h2><p>{policies.length ? JSON.stringify((policies[0] as PolicyData).rules) : '尚未配置平台安全策略'}</p><form className="form-grid" onSubmit={(event) => void savePolicy(event, 'security')}><TextField label="变更原因" name="reason" required /><div className="form-actions"><button className="primary-button" type="submit">保存默认拒绝策略</button></div></form></section><section className="section-block"><h2>扩缩容与预热</h2><p>{scaling.length ? JSON.stringify((scaling[0] as PolicyData).rules) : '尚未配置扩缩容策略'}</p><form className="form-grid" onSubmit={(event) => void savePolicy(event, 'scaling')}><TextField label="变更原因" name="reason" required /><div className="form-actions"><button className="primary-button" type="submit">保存预算护栏</button></div></form></section><section className="section-block"><h2>网络白名单</h2>{allowlist.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>范围</th><th>目标</th><th>端口</th><th>状态</th></tr></thead><tbody>{allowlist.map((item: AllowlistData) => <tr key={item.public_id}><td>{item.scope_type}</td><td>{item.target_value}</td><td>{item.protocol} {item.port_start}-{item.port_end}</td><td><StatusBadge status={item.status} /></td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}</section><section className="section-block"><h2>告警</h2>{alerts.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>等级</th><th>代码</th><th>资源</th><th>说明</th></tr></thead><tbody>{alerts.map((item) => <tr key={`${item.code}-${item.resource_ref}`}><td><StatusBadge status={item.severity} /></td><td>{item.code}</td><td>{item.resource_ref}</td><td data-wrap>{item.message}</td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}</section></section>
}

function AppRoutes() {
  const session = useSession(); const queryClient = useQueryClient(); const signOut = async () => { await session.signOut(); queryClient.clear() }
  const nav = session.status === 'authenticated' ? tabs : [{ href: '/login', label: '登录' }]
  return <PortalLayout title="管理端" tone="admin" release={release} nav={nav} actions={session.status === 'authenticated' ? <button className="text-button" onClick={() => void signOut()}>退出</button> : null}><AppErrorBoundary><Routes>
    <Route path="/login" element={<LoginPage />} /><Route path="/" element={<Navigate to="/users" replace />} /><Route path="/users" element={<Guard><UsersPage /></Guard>} /><Route path="/teachers" element={<Guard><TeachersPage /></Guard>} /><Route path="/admins" element={<Guard><AdminsPage /></Guard>} /><Route path="/verifications" element={<Guard><VerificationsPage /></Guard>} /><Route path="/courses" element={<Guard><CoursesPage /></Guard>} /><Route path="/runtimes" element={<Guard><RuntimesPage /></Guard>} /><Route path="/images" element={<Guard><ImagesPage /></Guard>} /><Route path="/resource-profiles" element={<Guard><ResourceProfilesPage /></Guard>} /><Route path="/quotas" element={<Guard><QuotasPage /></Guard>} /><Route path="/security" element={<Guard><SecurityPage /></Guard>} /><Route path="/template-prechecks" element={<Guard><PrecheckSummaryPage /></Guard>} /><Route path="*" element={<Navigate to="/users" replace />} />
  </Routes></AppErrorBoundary></PortalLayout>
}

export function App() { return <BrowserRouter><AppRoutes /></BrowserRouter> }
