import { useState, type ReactNode } from "react";
import { Link, NavLink, useMatch, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { teachingApi } from "@edu/api-client";
import type { Announcement } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, Panel, RequestStateView, EmptyState, useToast } from "@edu/ui";

import { CourseMaterials } from "@/components/course-materials";
import { CourseInvitationActions } from "@/components/course-invitation";
import { COURSE_STATUS_LABEL, PUBLICATION_STATUS_LABEL } from "@/lib/format";

export function CourseLayout({ children }: { children: ReactNode }) {
  const { courseId } = useParams();
  const enrollmentsPage = useMatch("/courses/:courseId/enrollments");
  const course = useQuery({ queryKey: keys.teachingCourse(courseId ?? ""), queryFn: () => teachingApi.course(courseId!), enabled: Boolean(courseId) });
  return <>
    {courseId && <section className="course-context">
      <div><Link to="/courses">我的课程</Link><span> / {course.data?.title ?? "课程"}</span></div>
      <div className={enrollmentsPage ? "course-context-heading" : undefined}>
        <div>
          <h1>{course.data?.title ?? "课程教学空间"}</h1>
          <p className="subtle">{course.data?.code} · 学生、实验与教学数据</p>
        </div>
        {enrollmentsPage && <CourseInvitationActions key={courseId} courseId={courseId} />}
      </div>
      <nav aria-label="课程功能" className="course-tabs">
        {[["", "课程概况"], ["/enrollments", "成员与申请"], ["/students", "实验进度"], ["/templates", "实验设计"], ["/publishing", "实验发布"], ["/analytics", "教学分析"]].map(([path, label]) =>
          <NavLink key={path} end={path === ""} to={`/courses/${courseId}${path}`}>{label}</NavLink>)}
      </nav>
    </section>}
    {children}
  </>;
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
  return <RequestStateView loading={course.isLoading || publications.isLoading} error={course.error ?? publications.error} onRetry={() => { void course.refetch(); void publications.refetch(); }} empty={false} emptyState={null}><div className="page-actions">{course.data?.status === "DRAFT" ? <Button variant="primary" disabled={publish.isPending} onClick={() => publish.mutate()}>{publish.isPending ? "发布中…" : "发布课程"}</Button> : <span>课程状态：{COURSE_STATUS_LABEL[course.data?.status ?? ""] ?? course.data?.status}</span>}</div><div className="teacher-summary"><div><span>选课学生</span><strong>{course.data?.active_enrollment_count ?? "—"}</strong></div><div><span>实验发布</span><strong>{publications.data?.total ?? publications.data?.rows.length ?? "—"}</strong></div><div><span>课程容量</span><strong>{course.data?.capacity ?? "不限"}</strong></div></div><Panel title={<h2>课程实验</h2>}><div className="teacher-list">{(publications.data?.rows ?? []).map(p => <div className="item" key={p.public_id}><div><strong>{p.title}</strong><small>{PUBLICATION_STATUS_LABEL[p.status] ?? p.status} · {p.audience_count ?? 0} 名学生</small></div><Link className="btn" to={`/courses/${courseId}/publishing/${p.public_id}/reviews`}>报告与评审</Link></div>)}{publications.data?.rows.length === 0 && <EmptyState title="尚未发布实验" action={<Link to={`/courses/${courseId}/templates`}>设计第一个实验</Link>} />}</div></Panel><CourseAnnouncements courseId={courseId} /><CourseMaterials key={courseId} courseId={courseId} /></RequestStateView>;
}

export function StudentDetail() {
  const { courseId = "" } = useParams();
  return <Panel title={<h2>学生个人数据</h2>}><EmptyState title="个人汇总接口待接入" hint="需要使用稳定学生 ID 查询，不能以姓名关联。请在课程实验进度与发布评审中查看已有任务数据。" /><Link to={`/courses/${courseId}/students`}>返回实验进度</Link></Panel>;
}

export function CourseAnnouncements({ courseId }: { courseId: string }) {
  const toast = useToast();
  const client = useQueryClient();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [pinned, setPinned] = useState(false);
  const announcements = useQuery({
    queryKey: ["course-announcements", courseId],
    queryFn: () => teachingApi.courseResource<Announcement>(courseId, "announcements"),
  });
  const create = useMutation({
    mutationFn: async () => {
      const created = await teachingApi.createAnnouncement(courseId, {
        title: title.trim(), body: body.trim(), pinned,
      });
      await teachingApi.publishAnnouncement(courseId, created.public_id, String(created.row_version ?? "1"));
      return created;
    },
    onSuccess: () => {
      toast.notify("公告已发布，学生进入课程空间即可看到");
      setTitle(""); setBody(""); setPinned(false);
      void announcements.refetch();
      void client.invalidateQueries({ queryKey: ["course-announcements", courseId] });
    },
    onError: (error) => toast.notify(error instanceof Error ? error.message : "公告发布失败", "error"),
  });
  const rows = announcements.data?.rows ?? [];
  return <Panel title={<><h2>课程公告</h2><span className="subtle">发布后学生在课程空间看到</span></>}>
    {rows.length > 0 && <div className="teacher-list">
      {rows.map((item) => <div className="item" key={item.public_id}>
        <div>
          <strong>{item.title}</strong>
          <small>{item.status === "PUBLISHED" ? `已发布 · ${item.published_at ? new Date(item.published_at).toLocaleString("zh-CN") : ""}` : "草稿"}{item.pinned ? " · 置顶" : ""}</small>
        </div>
      </div>)}
    </div>}
    {!rows.length && !announcements.isLoading && <p className="subtle">还没有公告。学生不会收到任何课程通知。</p>}
    <label>公告标题<input className="field" value={title} maxLength={160} onChange={(e) => setTitle(e.target.value)} placeholder="例如：随堂练习 11 月 19 日截止" /></label>
    <label>公告正文<textarea className="field" rows={4} value={body} onChange={(e) => setBody(e.target.value)} placeholder="写清楚要做什么、什么时候截止、有问题找谁。" /></label>
    <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <input type="checkbox" checked={pinned} onChange={(e) => setPinned(e.target.checked)} /> 置顶这条公告
    </label>
    {(title.trim() || body.trim()) && <div className="section" aria-label="学生看到的预览">
      <p className="subtle">学生将看到：</p>
      <div className="panel" style={{ padding: 14 }}>
        <strong>{title.trim() || "（公告标题）"}</strong>
        <p style={{ whiteSpace: "pre-wrap", margin: "6px 0 0" }}>{body.trim() || "（公告正文）"}</p>
        <p className="subtle" style={{ margin: "6px 0 0" }}>数据结构与算法（Python） · 刚刚发布</p>
      </div>
    </div>}
    <Button variant="primary" disabled={!title.trim() || create.isPending} onClick={() => create.mutate()}>
      {create.isPending ? "发布中…" : "发布公告"}
    </Button>
  </Panel>;
}
