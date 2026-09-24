import { useState, type FormEvent, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiError, RequestIntent, apiRequestWithMetadata, type CourseData, type CourseListResponse, type CourseResponse, type EnrollmentData, type EnrollmentListResponse, type EnrollmentResponse, type MeResponse, type ResourceSummaryResponse, type VerificationData } from '@edu/api-client'
import { useSession } from '@edu/auth-client'
import { accountKeys, courseKeys, governanceKeys } from '@edu/query-keys'
import { AppErrorBoundary, LoginForm, PageHeader, PortalLayout, RequestStateView, StatusBadge, TextField } from '@edu/ui'
import { ExperimentDashboardPage, ExperimentTaskDetailPage, ExperimentTaskListPage } from './p06'
import { WorkspaceCheckpointsPage, WorkspaceLabPage, WorkspaceReplayPage } from './p08'
import { UserReportPage } from './p09'
import { UserReviewResultPage } from './p10'

const release = {
  version: import.meta.env.VITE_APP_VERSION ?? '0.10.0-p10',
  openapiRevision: import.meta.env.VITE_OPENAPI_REVISION ?? 'v2-p10',
  gitRevision: import.meta.env.VITE_GIT_REVISION ?? 'development',
  buildTime: import.meta.env.VITE_BUILD_TIME ?? 'development',
}

function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return '请求未完成，请稍后重试。'
  return {
    INVALID_CREDENTIALS: '账号或密码错误。',
    RATE_LIMITED: '登录尝试过于频繁，请稍后再试。',
    ROW_VERSION_CONFLICT: '资料已在其他页面更新，请刷新后重试。',
  }[error.payload.error.code] ?? error.payload.error.message
}

function LoginPage() {
  const session = useSession(); const navigate = useNavigate()
  const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  if (session.status === 'authenticated') return <Navigate to="/" replace />
  const submit = async (identifier: string, password: string) => {
    setBusy(true); setError('')
    try { await session.signIn({ identifier, password }); navigate('/') }
    catch (reason) { setError(errorMessage(reason)) }
    finally { setBusy(false) }
  }
  return <LoginForm title="用户端" busy={busy} error={error} onSubmit={submit} />
}

function Guard({ children }: { children: ReactNode }) {
  const session = useSession(); const location = useLocation()
  if (session.status === 'loading') return <RequestStateView state="loading" />
  if (session.status === 'anonymous') return <Navigate to="/login" state={{ from: location }} replace />
  if (session.status === 'denied') return <RequestStateView state="forbidden" message="当前账号不能进入用户端。" />
  if (session.status === 'error') return <RequestStateView state="error" traceId={session.error?.traceId} onRetry={() => void session.refresh()} />
  return children
}

function ProfilePage() {
  const session = useSession(); const [message, setMessage] = useState(''); const [error, setError] = useState('')
  const verification = useQuery({ queryKey: accountKeys.verification(), queryFn: () => apiRequestWithMetadata<{ data: VerificationData }>('/api/v2/me/verification') })
  const updateProfile = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(''); setMessage(''); const form = new FormData(event.currentTarget)
    try {
      const result = await apiRequestWithMetadata<MeResponse>('/api/v2/me', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ display_name: form.get('display_name') }), ifMatch: session.etag ?? undefined })
      session.updateMe(result.payload.data, result.etag); setMessage('个人资料已更新。')
    } catch (reason) { setError(errorMessage(reason)) }
  }
  const updatePassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(''); setMessage(''); const form = new FormData(event.currentTarget)
    try {
      const result = await apiRequestWithMetadata<MeResponse>('/api/v2/me/password', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ current_password: form.get('current_password'), new_password: form.get('new_password') }), ifMatch: session.etag ?? undefined, intent: new RequestIntent() })
      session.updateMe(result.payload.data, result.etag); event.currentTarget.reset(); setMessage('密码已更新，其他门户会话已失效。')
    } catch (reason) { setError(errorMessage(reason)) }
  }
  const updateVerification = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setError(''); setMessage(''); const form = new FormData(event.currentTarget)
    try {
      await apiRequestWithMetadata('/api/v2/me/verification', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ identity_type: form.get('identity_type'), organization_name: form.get('organization_name'), identity_number: form.get('identity_number'), material_asset_id: '', submit: form.get('submit') === 'true' }), ifMatch: verification.data?.etag ?? undefined })
      await verification.refetch(); event.currentTarget.reset(); setMessage('身份资料已保存。')
    } catch (reason) { setError(errorMessage(reason)) }
  }
  const verificationData = verification.data?.payload.data
  return <section className="workspace-page">
    <PageHeader eyebrow="PROFILE" title="个人资料" description="维护展示信息、登录密码和身份资料。" />
    {message ? <p className="notice" role="status">{message}</p> : null}{error ? <p className="form-error" role="alert">{error}</p> : null}
    <section className="section-block"><h2>基本信息</h2><form className="form-grid" onSubmit={updateProfile}>
      <TextField label="展示名称" name="display_name" defaultValue={session.me?.display_name} required /><div />
      <div className="form-actions"><button className="primary-button" type="submit">保存资料</button></div>
    </form></section>
    <section className="section-block"><h2>修改密码</h2><form className="form-grid" onSubmit={updatePassword}>
      <TextField label="当前密码" name="current_password" type="password" required />
      <TextField label="新密码" name="new_password" type="password" minLength={12} required />
      <div className="form-actions"><button className="primary-button" type="submit">更新密码</button></div>
    </form></section>
    <section className="section-block"><h2>学校或企业身份</h2>
      {verification.isPending ? <RequestStateView state="loading" /> : verification.isError ? <RequestStateView state="error" onRetry={() => void verification.refetch()} /> : <>
        <p>当前状态：<StatusBadge status={verificationData?.status ?? 'DRAFT'} /></p>
        {['DRAFT', 'REJECTED'].includes(verificationData?.status ?? '') ? <form className="form-grid" onSubmit={updateVerification}>
          <label className="field"><span>身份类型</span><select name="identity_type" defaultValue={verificationData?.identity_type}><option value="SCHOOL">学校</option><option value="ENTERPRISE">企业</option></select></label>
          <TextField label="机构名称" name="organization_name" defaultValue={verificationData?.organization_name} required />
          <TextField label="证件编号" name="identity_number" required />
          <div className="form-actions"><button className="text-button" name="submit" value="false">保存草稿</button><button className="primary-button" name="submit" value="true">提交审核</button></div>
        </form> : <p className="notice">证件编号仅显示掩码：{verificationData?.identity_number_masked || '未提供'}</p>}</>}
    </section>
  </section>
}

function CourseCard({ course }: { course: CourseData }) {
  return <a className="summary-item" href={'/courses/' + course.public_id}><span>{course.code} · {course.owner_name}</span><strong>{course.title}</strong><small>{course.summary || '暂无摘要'}</small><StatusBadge status={course.status} /></a>
}

function CourseCatalogPage() {
  const query = useQuery({ queryKey: courseKeys.catalog(), queryFn: () => apiRequestWithMetadata<CourseListResponse>('/api/v2/courses') })
  const values = query.data?.payload.data ?? []
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state="error" onRetry={() => void query.refetch()} />
  return <section className="workspace-page"><PageHeader eyebrow="COURSE CATALOG" title="课程目录" description="浏览已发布课程并查看报名状态。" />{values.length ? <div className="summary-grid">{values.map((course) => <CourseCard course={course} key={course.public_id} />)}</div> : <RequestStateView state="empty" />}</section>
}

function ResourceSummary({ courseId }: { courseId: string }) {
  const query = useQuery({
    queryKey: governanceKeys.resourceSummary(courseId),
    queryFn: () => apiRequestWithMetadata<ResourceSummaryResponse>(`/api/v2/me/courses/${courseId}/resource-summary`),
  })
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state="error" message="当前课程尚未开放实验资源摘要。" onRetry={() => void query.refetch()} />
  const summary = query.data?.payload.data
  if (!summary) return <RequestStateView state="empty" />
  return <section className="section-block"><h2>可用资源</h2><div className="summary-grid governance-summary">
    <div className="summary-item"><span>并发实例</span><strong>{summary.available.instance_count ?? '未配置'}</strong><small>课程与账号配额交集</small></div>
    <div className="summary-item"><span>CPU</span><strong>{summary.available.cpu_millicores ?? '未配置'} mCPU</strong><small>当前已用 {summary.used.cpu_millicores ?? 0} mCPU</small></div>
    <div className="summary-item"><span>磁盘</span><strong>{summary.available.disk_gb ?? '未配置'} GB</strong><small>只读摘要，不可修改</small></div>
  </div></section>
}

function CourseDetailPage() {
  const { courseId = '' } = useParams(); const queryClient = useQueryClient(); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [notice, setNotice] = useState('')
  const query = useQuery({ queryKey: courseKeys.detail(courseId), queryFn: () => apiRequestWithMetadata<CourseResponse>('/api/v2/courses/' + courseId), enabled: Boolean(courseId) })
  const course = query.data?.payload.data
  const apply = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!course) return; setBusy(true); setError(''); setNotice('')
    const form = new FormData(event.currentTarget)
    try {
      await apiRequestWithMetadata<EnrollmentResponse>('/api/v2/courses/' + course.public_id + '/enrollments', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ application_message: form.get('application_message') ?? '', invitation_code: form.get('invitation_code') ?? '' }), intent: new RequestIntent() })
      setNotice('选课申请已提交。'); event.currentTarget.reset(); await queryClient.invalidateQueries({ queryKey: courseKeys.all })
    } catch (reason) { setError(errorMessage(reason)) } finally { setBusy(false) }
  }
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError || !course) return <RequestStateView state="error" onRetry={() => void query.refetch()} />
  return <section className="workspace-page"><PageHeader eyebrow={course.code} title={course.title} description={course.summary} /><div className="summary-grid"><div className="summary-item"><span>任课教师</span><strong>{course.owner_name}</strong></div><div className="summary-item"><span>选课方式</span><strong>{course.enrollment_mode}</strong></div><div className="summary-item"><span>容量</span><strong>{course.capacity === null ? '不限' : course.active_enrollment_count + ' / ' + course.capacity}</strong></div></div><ResourceSummary courseId={courseId} /><section className="section-block"><h2>课程说明</h2><p>{course.description || '暂无课程说明。'}</p>{notice ? <p className="notice" role="status">{notice}</p> : null}{error ? <p className="form-error" role="alert">{error}</p> : null}<form className="form-grid" onSubmit={apply}><TextField label="申请说明" name="application_message" /><TextField label="邀请码（可选）" name="invitation_code" /><div className="form-actions"><button className="primary-button" type="submit" disabled={busy}>{busy ? '提交中' : '申请选课'}</button></div></form></section></section>
}

function CourseLearningPage() {
  const { courseId = '' } = useParams()
  const query = useQuery({ queryKey: courseKeys.content(courseId, 'chapters'), queryFn: () => apiRequestWithMetadata<{ data: Array<Record<string, unknown>> }>('/api/v2/courses/' + courseId + '/chapters') })
  const materialQuery = useQuery({ queryKey: courseKeys.content(courseId, 'materials'), queryFn: () => apiRequestWithMetadata<{ data: Array<Record<string, unknown>> }>('/api/v2/courses/' + courseId + '/materials') })
  if (query.isPending || materialQuery.isPending) return <RequestStateView state="loading" />
  if (query.isError || materialQuery.isError) return <RequestStateView state="error" onRetry={() => { void query.refetch(); void materialQuery.refetch() }} />
  const chapters = query.data?.payload.data ?? []; const materials = materialQuery.data?.payload.data ?? []
  return <section className="workspace-page"><PageHeader eyebrow="COURSE LEARNING" title="课程学习" description="已发布章节和资料按当前选课状态显示。" />{chapters.length ? <div className="summary-grid">{chapters.map((chapter) => <div className="summary-item" key={String(chapter.public_id)}><span>第 {String(chapter.position)} 章</span><strong>{String(chapter.title)}</strong><small>{String(chapter.summary ?? '')}</small><div>{materials.filter((material) => material.chapter_id === chapter.public_id).map((material) => <p key={String(material.public_id)}>{String(material.title)} · {String(material.kind)}</p>)}</div></div>)}</div> : <RequestStateView state="empty" />}</section>
}

function MyCoursesPage() {
  const query = useQuery({ queryKey: courseKeys.myEnrollments(), queryFn: () => apiRequestWithMetadata<EnrollmentListResponse>('/api/v2/me/enrollments') })
  const values = query.data?.payload.data ?? []
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state="error" onRetry={() => void query.refetch()} />
  return <section className="workspace-page"><PageHeader eyebrow="MY COURSES" title="我的课程" description="查看当前和历史选课周期。" />{values.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>课程</th><th>周期</th><th>状态</th><th>操作</th></tr></thead><tbody>{values.map((item) => <EnrollmentRow item={item} key={item.public_id} />)}</tbody></table></div> : <RequestStateView state="empty" />}</section>
}

function EnrollmentRow({ item }: { item: EnrollmentData }) {
  const queryClient = useQueryClient(); const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const drop = async () => {
    setBusy(true); setError('')
    try {
      const check = await apiRequestWithMetadata<{ data: { allowed: boolean; blockers: unknown[] } }>('/api/v2/me/enrollments/' + item.public_id + '/drop-check')
      if (!check.payload.data.allowed) { setError('存在退课阻断，请先完成相关任务或审核。'); return }
      await apiRequestWithMetadata('/api/v2/me/enrollments/' + item.public_id + '/drop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: '学生主动退课' }), ifMatch: '"' + item.row_version + '"', intent: new RequestIntent() })
      await queryClient.invalidateQueries({ queryKey: courseKeys.myEnrollments() })
    } catch (reason) { setError(errorMessage(reason)) } finally { setBusy(false) }
  }
  return <tr><td data-wrap><strong>{item.course_title}</strong><br />{item.course_code}</td><td>{item.cycle_no}</td><td><StatusBadge status={item.status} />{error ? <small className="form-error">{error}</small> : null}</td><td>{item.status === 'ACTIVE' ? <button className="text-button text-button--danger" disabled={busy} onClick={() => void drop()}>退课</button> : null}</td></tr>
}

function AppRoutes() {
  const session = useSession(); const queryClient = useQueryClient()
  const signOut = async () => { await session.signOut(); queryClient.clear() }
  const nav = session.status === 'authenticated' ? [{ href: '/dashboard', label: '实验工作台' }, { href: '/tasks', label: '我的实验' }, { href: '/courses', label: '课程目录' }, { href: '/my-courses', label: '我的课程' }, { href: '/profile', label: '个人资料' }] : [{ href: '/login', label: '登录' }]
  return <PortalLayout title="用户端" tone="user" release={release} nav={nav} actions={session.status === 'authenticated' ? <button className="text-button" onClick={() => void signOut()}>退出</button> : null}><AppErrorBoundary><Routes>
    <Route path="/login" element={<LoginPage />} /><Route path="/" element={<Navigate to="/dashboard" replace />} /><Route path="/dashboard" element={<Guard><ExperimentDashboardPage /></Guard>} /><Route path="/tasks" element={<Guard><ExperimentTaskListPage /></Guard>} /><Route path="/tasks/:taskId" element={<Guard><ExperimentTaskDetailPage /></Guard>} /><Route path="/tasks/:taskId/report" element={<Guard><UserReportPage /></Guard>} /><Route path="/tasks/:taskId/review-result" element={<Guard><UserReviewResultPage /></Guard>} /><Route path="/tasks/:taskId/lab" element={<Guard><WorkspaceLabPage /></Guard>} /><Route path="/tasks/:taskId/checkpoints" element={<Guard><WorkspaceCheckpointsPage /></Guard>} /><Route path="/tasks/:taskId/replay" element={<Guard><WorkspaceReplayPage /></Guard>} /><Route path="/experiments/:taskId/lab" element={<Guard><WorkspaceLabPage /></Guard>} /><Route path="/experiments/:taskId/checkpoints" element={<Guard><WorkspaceCheckpointsPage /></Guard>} /><Route path="/experiments/:taskId/replay" element={<Guard><WorkspaceReplayPage /></Guard>} /><Route path="/courses" element={<Guard><CourseCatalogPage /></Guard>} /><Route path="/courses/:courseId" element={<Guard><CourseDetailPage /></Guard>} /><Route path="/courses/:courseId/chapters" element={<Guard><CourseLearningPage /></Guard>} /><Route path="/my-courses" element={<Guard><MyCoursesPage /></Guard>} /><Route path="/profile" element={<Guard><ProfilePage /></Guard>} /><Route path="*" element={<Navigate to="/dashboard" replace />} />
  </Routes></AppErrorBoundary></PortalLayout>
}

export function App() { return <BrowserRouter><AppRoutes /></BrowserRouter> }
