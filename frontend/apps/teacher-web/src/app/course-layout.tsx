import type { ReactNode } from "react";
import { Link, NavLink, useParams, useLocation } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { teachingApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, Panel, RequestStateView, EmptyState, useToast } from "@edu/ui";

import { CourseMaterials } from "@/components/course-materials";

export function CourseLayout({ children }: { children: ReactNode }) {
  const { courseId } = useParams();
  const course = useQuery({ queryKey: keys.teachingCourse(courseId ?? ""), queryFn: () => teachingApi.course(courseId!), enabled: Boolean(courseId) });
  return <>{courseId && <section className="course-context"><div><Link to="/courses">我的课程</Link><span> / {course.data?.title ?? "课程"}</span></div><h1>{course.data?.title ?? "课程教学空间"}</h1><p className="subtle">{course.data?.code} · 学生、实验与教学数据</p><nav aria-label="课程功能" className="course-tabs">{[["", "课程概况"], ["/enrollments", "成员与申请"], ["/students", "实验进度"], ["/templates", "实验设计"], ["/publishing", "实验发布"], ["/analytics", "教学分析"]].map(([path, label]) => <NavLink key={path} end={path === ""} to={`/courses/${courseId}${path}`}>{label}</NavLink>)}</nav></section>}{children}</>;
}

export function CourseOverview() {
  const { courseId = "" } = useParams();
  const course = useQuery({ queryKey: keys.teachingCourse(courseId), queryFn: () => teachingApi.course(courseId) });
  const client = useQueryClient();
  const toast = useToast();
  const publish = useMutation({
    mutationFn: () => teachingApi.publishCourse(courseId, String(course.data?.row_version ?? "")),
    onSuccess: () => { void client.invalidateQueries({ queryKey: keys.teachingCourses() }); void course.refetch(); toast.notify("课程已发布，学生可申请加入"); },
    onError: (error) => toast.notify(error.message, "error"),
  });
  const publications = useQuery({ queryKey: keys.publications(courseId, {}), queryFn: () => teachingApi.publications(courseId, {}) });
  return <RequestStateView loading={course.isLoading || publications.isLoading} error={course.error ?? publications.error} onRetry={() => { void course.refetch(); void publications.refetch(); }} empty={false} emptyState={null}><div className="page-actions">{course.data?.status === "DRAFT" ? <Button variant="primary" disabled={publish.isPending} onClick={() => publish.mutate()}>{publish.isPending ? "发布中…" : "发布课程"}</Button> : <span>课程状态：{course.data?.status === "PUBLISHED" ? "已发布" : course.data?.status}</span>}</div><div className="teacher-summary"><div><span>选课学生</span><strong>{course.data?.active_enrollment_count ?? "—"}</strong></div><div><span>实验发布</span><strong>{publications.data?.total ?? publications.data?.rows.length ?? "—"}</strong></div><div><span>课程容量</span><strong>{course.data?.capacity ?? "不限"}</strong></div></div><Panel title={<h2>课程实验</h2>}><div className="teacher-list">{(publications.data?.rows ?? []).map(p => <div className="item" key={p.public_id}><div><strong>{p.title}</strong><small>{p.status} · {p.audience_count ?? 0} 名学生</small></div><Link className="btn" to={`/courses/${courseId}/publishing/${p.public_id}/reviews`}>报告与评审</Link></div>)}{publications.data?.rows.length === 0 && <EmptyState title="尚未发布实验" action={<Link to={`/courses/${courseId}/templates`}>设计第一个实验</Link>} />}</div></Panel><CourseMaterials key={courseId} courseId={courseId} /></RequestStateView>;
}

export function StudentDetail() {
  const { courseId = "" } = useParams();
  return <Panel title={<h2>学生个人数据</h2>}><EmptyState title="个人汇总接口待接入" hint="需要使用稳定学生 ID 查询，不能以姓名关联。请在课程实验进度与发布评审中查看已有任务数据。" /><Link to={`/courses/${courseId}/students`}>返回实验进度</Link></Panel>;
}

export function ValidationWorkspace() {
  const { courseId = "", templateId = "" } = useParams();
  const location = useLocation();
  return <Panel title={<h2>验证实验工作台</h2>}><EmptyState title="教师验证会话接口待接入" hint="现有学生工作台要求学生任务与会话凭证，不能直接复用于教师。已登记后端对接需求，接口提供后接入实验操作、报告保存和提交全过程。" /><p className="subtle">实验：{templateId} · 版本：{new URLSearchParams(location.search).get("version") ?? "当前版本"}</p><Link className="btn" to={`/courses/${courseId}/templates/${templateId}/edit`}>返回实验设计</Link></Panel>;
}
