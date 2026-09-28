import { useState, type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiError, RequestIntent, apiRequestWithMetadata, type CourseListResponse, type CourseResponse, type EnrollmentListResponse, type ResourceSummaryResponse } from '@edu/api-client'
import { useSession } from '@edu/auth-client'
import { courseKeys, governanceKeys } from '@edu/query-keys'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AppErrorBoundary, LoginForm, PageHeader, PortalLayout, RequestStateView, StatusBadge } from '@edu/ui'
import { RubricListPage, RubricVersionPage, RubricVersionsPage, TemplateListPage, TemplateVersionPage, TemplateVersionsPage } from './p05'
import { ExperimentDetailPage, ExperimentListPage } from './p06'
import { TeachingWorkspacePage, TeachingWorkspaceReplayPage } from './p08'
import { TeachingSubmissionPreviewPage } from './p09'
import { ReviewQueuePage, ReviewWorkbenchPage } from './p10'
import { TeachingArchiveDetailPage, TeachingArchivesPage } from './p11'
import { TeachingAgentPage } from './p12'
import { TeachingAnalyticsPage } from './p13'

function TeachingAgentRoute() { const { courseId = '' } = useParams(); return <TeachingAgentPage courseId={courseId} /> }
function TeachingAnalyticsRoute() { const { courseId = '' } = useParams(); return <TeachingAnalyticsPage courseId={courseId} /> }

const release = { version: import.meta.env.VITE_APP_VERSION ?? '0.14.0-p14', openapiRevision: import.meta.env.VITE_OPENAPI_REVISION ?? 'v2-p14', gitRevision: import.meta.env.VITE_GIT_REVISION ?? 'development', buildTime: import.meta.env.VITE_BUILD_TIME ?? 'development' }

function LoginPage() {
  const session = useSession(); const navigate = useNavigate(); const [busy, setBusy] = useState(false); const [error, setError] = useState('')
  if (session.status === 'authenticated') return <Navigate to="/" replace />
  const submit = async (identifier: string, password: string) => {
    setBusy(true); setError('')
    try { await session.signIn({ identifier, password }); navigate('/') }
    catch (reason) { setError(reason instanceof ApiError ? reason.payload.error.message : '登录请求未完成，请稍后重试。') }
    finally { setBusy(false) }
  }
  return <LoginForm title="教师端" busy={busy} error={error} onSubmit={submit} />
}

function Guard({ children }: { children: ReactNode }) {
  const session = useSession(); const location = useLocation()
  if (session.status === 'loading') return <RequestStateView state="loading" />
  if (session.status === 'anonymous') return <Navigate to="/login" state={{ from: location }} replace />
  if (session.status === 'denied') return <RequestStateView state="forbidden" title="需要有效教师资格" message="资格暂停或撤销后，原教师端会话会立即失效。" />
  if (session.status === 'error') return <RequestStateView state="error" traceId={session.error?.traceId} onRetry={() => void session.refresh()} />
  return children
}

function CourseListPage() {
  const query = useQuery({ queryKey: courseKeys.teaching(), queryFn: () => apiRequestWithMetadata<CourseListResponse>('/api/v2/teaching/courses') })
  const values = query.data?.payload.data ?? []
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state="error" onRetry={() => void query.refetch()} />
  return <section className="workspace-page"><PageHeader eyebrow="TEACHING COURSES" title="我的课程" description="课程设置、教学团队和名册入口。" /><div className="summary-grid">{values.map((course) => <a className="summary-item" href={'/courses/' + course.public_id} key={course.public_id}><span>{course.code}</span><strong>{course.title}</strong><StatusBadge status={course.status} /></a>)}</div></section>
}

function GovernanceSummary({ courseId }: { courseId: string }) {
  const query = useQuery({
    queryKey: governanceKeys.courseSummary(courseId),
    queryFn: () => apiRequestWithMetadata<ResourceSummaryResponse>(`/api/v2/teaching/courses/${courseId}/governance`),
  })
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state="error" message="治理摘要暂时不可用，课程管理仍可继续。" onRetry={() => void query.refetch()} />
  const summary = query.data?.payload.data
  if (!summary) return <RequestStateView state="empty" />
  return <section className="section-block"><h2>治理摘要</h2><div className="summary-grid governance-summary">
    <div className="summary-item"><span>并发实例可用</span><strong>{summary.available.instance_count ?? '未配置'}</strong><small>已用 {summary.used.instance_count ?? 0}</small></div>
    <div className="summary-item"><span>CPU 可用</span><strong>{summary.available.cpu_millicores ?? '未配置'} mCPU</strong><small>已用 {summary.used.cpu_millicores ?? 0} mCPU</small></div>
    <div className="summary-item"><span>预热实例</span><strong>{summary.prewarm_active ?? 0}</strong><small>策略由平台治理控制</small></div>
  </div></section>
}

function CourseSettingsPage() {
  const { courseId = '' } = useParams(); const queryClient = useQueryClient(); const [busy, setBusy] = useState(false); const [notice, setNotice] = useState(''); const [error, setError] = useState('')
  const query = useQuery({ queryKey: courseKeys.teachingDetail(courseId), queryFn: () => apiRequestWithMetadata<CourseResponse>('/api/v2/teaching/courses/' + courseId) })
  const course = query.data?.payload.data
  const publish = async () => { if (!course) return; setBusy(true); setError(''); try { await apiRequestWithMetadata('/api/v2/teaching/courses/' + courseId + '/publish', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', ifMatch: '"' + course.row_version + '"', intent: new RequestIntent() }); setNotice('课程发布请求已完成。'); await queryClient.invalidateQueries({ queryKey: courseKeys.teachingDetail(courseId) }) } catch (reason) { setError(reason instanceof ApiError ? reason.payload.error.message : '请求未完成') } finally { setBusy(false) } }
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError || !course) return <RequestStateView state="error" onRetry={() => void query.refetch()} />
  return <section className="workspace-page"><PageHeader eyebrow={course.code} title={course.title} description="课程设置与教学操作。" actions={<button className="primary-button" disabled={busy || course.status !== 'DRAFT'} onClick={() => void publish()}>发布课程</button>} />{notice ? <p className="notice">{notice}</p> : null}{error ? <p className="form-error">{error}</p> : null}<div className="summary-grid"><div className="summary-item"><span>课程状态</span><strong><StatusBadge status={course.status} /></strong></div><div className="summary-item"><span>选课方式</span><strong>{course.enrollment_mode}</strong></div><div className="summary-item"><span>容量</span><strong>{course.capacity ?? '不限'}</strong></div></div><GovernanceSummary courseId={courseId} /><nav className="tabs"><a href={'/courses/' + courseId + '/enrollments'}>名册</a><a href={'/courses/' + courseId + '/content'}>内容</a><a href={'/courses/' + courseId + '/templates'}>实验模板</a><a href={'/courses/' + courseId + '/rubrics'}>评分量规</a><a href={'/courses/' + courseId + '/experiments'}>实验发布</a><a href={'/courses/' + courseId + '/reviews'}>教师审核</a><a href={'/courses/' + courseId + '/archives'}>成果归档</a><a href={'/courses/' + courseId + '/analytics'}>课程分析</a><a href={'/courses/' + courseId + '/agents'}>课程 Agent</a><a href={'/courses/' + courseId + '/staff'}>教学团队</a><a href={'/courses/' + courseId + '/invitations'}>邀请码</a></nav></section>
}

function RosterPage() {
  const { courseId = '' } = useParams(); const queryClient = useQueryClient(); const [error, setError] = useState('')
  const query = useQuery({ queryKey: courseKeys.roster(courseId), queryFn: () => apiRequestWithMetadata<EnrollmentListResponse>('/api/v2/teaching/courses/' + courseId + '/enrollments') })
  const values = query.data?.payload.data ?? []
  const review = async (id: string, etag: number, decision: string) => { setError(''); try { await apiRequestWithMetadata('/api/v2/teaching/courses/' + courseId + '/enrollments/' + id + '/review', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, note: '教师审核' }), ifMatch: '"' + etag + '"', intent: new RequestIntent() }); await queryClient.invalidateQueries({ queryKey: courseKeys.roster(courseId) }) } catch (reason) { setError(reason instanceof ApiError ? reason.payload.error.message : '请求未完成') } }
  if (query.isPending) return <RequestStateView state="loading" />
  if (query.isError) return <RequestStateView state="error" onRetry={() => void query.refetch()} />
  return <section className="workspace-page"><PageHeader eyebrow="ROSTER" title="名册与申请" description="审批时服务端会重新检查容量和先修。" />{error ? <p className="form-error">{error}</p> : null}<div className="data-table-wrap"><table className="data-table"><thead><tr><th>学生</th><th>状态</th><th>申请时间</th><th>操作</th></tr></thead><tbody>{values.map((item) => <tr key={item.public_id}><td data-wrap><strong>{item.student_name}</strong><br />{item.course_code}</td><td><StatusBadge status={item.status} /></td><td>{new Date(item.applied_at).toLocaleString()}</td><td>{item.status === 'PENDING' ? <div className="toolbar"><button className="text-button" onClick={() => void review(item.public_id, item.row_version, 'APPROVE')}>通过</button><button className="text-button text-button--danger" onClick={() => void review(item.public_id, item.row_version, 'REJECT')}>拒绝</button></div> : null}</td></tr>)}</tbody></table></div></section>
}

function ContentPage() {
  const { courseId = '' } = useParams(); const [resource, setResource] = useState('chapters')
  const query = useQuery({ queryKey: courseKeys.content(courseId, resource), queryFn: () => apiRequestWithMetadata<{ data: Array<Record<string, unknown>> }>('/api/v2/teaching/courses/' + courseId + '/' + resource) })
  const values = query.data?.payload.data ?? []
  return <section className="workspace-page"><PageHeader eyebrow="CONTENT" title="内容编排" description="章节、资料、公告、日历与问答均按课程 scope 隔离。" /><label className="field"><span>内容类型</span><select value={resource} onChange={(event) => setResource(event.target.value)}><option value="chapters">章节</option><option value="materials">资料</option><option value="announcements">公告</option><option value="calendar-events">日历</option><option value="questions">问答</option></select></label>{query.isPending ? <RequestStateView state="loading" /> : query.isError ? <RequestStateView state="error" onRetry={() => void query.refetch()} /> : values.length ? <div className="data-table-wrap"><table className="data-table"><thead><tr><th>标识</th><th>标题</th><th>状态</th></tr></thead><tbody>{values.map((value) => <tr key={String(value.public_id)}><td>{String(value.public_id)}</td><td data-wrap>{String(value.title ?? value.body ?? '')}</td><td><StatusBadge status={String(value.status ?? 'ACTIVE')} /></td></tr>)}</tbody></table></div> : <RequestStateView state="empty" />}</section>
}

function AppRoutes() {
  const session = useSession(); const queryClient = useQueryClient()
  const signOut = async () => { await session.signOut(); queryClient.clear() }
  return <PortalLayout title="教师端" tone="teacher" release={release} nav={session.status === 'authenticated' ? [{ href: '/courses', label: '我的课程' }] : [{ href: '/login', label: '登录' }]} actions={session.status === 'authenticated' ? <button className="text-button" onClick={() => void signOut()}>退出</button> : null}><AppErrorBoundary><Routes>
    <Route path="/login" element={<LoginPage />} /><Route path="/" element={<Navigate to="/courses" replace />} /><Route path="/courses" element={<Guard><CourseListPage /></Guard>} /><Route path="/courses/:courseId" element={<Guard><CourseSettingsPage /></Guard>} /><Route path="/courses/:courseId/analytics" element={<Guard><TeachingAnalyticsRoute /></Guard>} /><Route path="/courses/:courseId/agents" element={<Guard><TeachingAgentRoute /></Guard>} /><Route path="/courses/:courseId/enrollments" element={<Guard><RosterPage /></Guard>} /><Route path="/courses/:courseId/content" element={<Guard><ContentPage /></Guard>} /><Route path="/courses/:courseId/templates" element={<Guard><TemplateListPage /></Guard>} /><Route path="/courses/:courseId/templates/:templateId" element={<Guard><TemplateVersionsPage /></Guard>} /><Route path="/courses/:courseId/template-versions/:versionId" element={<Guard><TemplateVersionPage /></Guard>} /><Route path="/courses/:courseId/rubrics" element={<Guard><RubricListPage /></Guard>} /><Route path="/courses/:courseId/rubrics/:rubricId" element={<Guard><RubricVersionsPage /></Guard>} /><Route path="/courses/:courseId/rubric-versions/:versionId" element={<Guard><RubricVersionPage /></Guard>} /><Route path="/courses/:courseId/experiments" element={<Guard><ExperimentListPage /></Guard>} /><Route path="/courses/:courseId/experiments/:publicationId" element={<Guard><ExperimentDetailPage /></Guard>} /><Route path="/courses/:courseId/reviews" element={<Guard><ReviewQueuePage /></Guard>} /><Route path="/courses/:courseId/reviews/:reviewId" element={<Guard><ReviewWorkbenchPage /></Guard>} /><Route path="/courses/:courseId/archives" element={<Guard><TeachingArchivesPage /></Guard>} /><Route path="/courses/:courseId/archives/:archiveId" element={<Guard><TeachingArchiveDetailPage /></Guard>} /><Route path="/courses/:courseId/tasks/:taskId/submission" element={<Guard><TeachingSubmissionPreviewPage /></Guard>} /><Route path="/courses/:courseId/tasks/:taskId/workspace" element={<Guard><TeachingWorkspacePage /></Guard>} /><Route path="/courses/:courseId/tasks/:taskId/operation-replay" element={<Guard><TeachingWorkspaceReplayPage /></Guard>} /><Route path="*" element={<Navigate to="/courses" replace />} />
  </Routes></AppErrorBoundary></PortalLayout>
}

export function App() { return <BrowserRouter><AppRoutes /></BrowserRouter> }
