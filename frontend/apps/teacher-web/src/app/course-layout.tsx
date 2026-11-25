import { useState, type ReactNode } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { teachingApi, timetableApi } from "@edu/api-client";
import type { Announcement } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, Panel, RequestStateView, EmptyState, useToast } from "@edu/ui";
import { CourseMaterials } from "@/components/course-materials";
import { CourseInvitationActions } from "@/components/course-invitation";
import { ClassAgendaWeek } from "@/components/teaching-agenda";
import { ClassExperiments, type ExperimentRow } from "@/components/class-experiments";
import { LabDesignDialog } from "@/components/lab-design";
import { TeacherIcon, type TeacherIconName } from "@/components/teacher-b";
import { PUBLICATION_STATUS_LABEL } from "@/lib/format";
import { copyText } from "@/lib/clipboard";
import { asAgendaSlots, isReportPublication, reviewLink, schoolDateTime, schoolToday, useAgendaPublications, usePublicationReports } from "@/lib/teaching-agenda";

const courseTabs: Array<{ suffix: string; label: string; icon: TeacherIconName }> = [
  { suffix: "", label: "实验列表", icon: "flask" },
  { suffix: "/enrollments", label: "学生名单", icon: "users" },
  { suffix: "?tab=schedule", label: "班级课表", icon: "calendar" },
  { suffix: "/analytics", label: "成绩分析", icon: "chart" },
];

function CourseCode({ courseId }: { courseId: string }) {
  const toast = useToast();
  const invitations = useQuery({ queryKey: keys.invitations(courseId), queryFn: () => teachingApi.invitations(courseId) });
  const code = invitations.data?.rows.find((item) => item.recoverable && item.code &&
    ["ACTIVE", "ENABLED"].includes(item.status) && (!item.expires_at || Date.parse(item.expires_at) > Date.now()) &&
    (item.usage_limit == null || (item.used_count ?? 0) < item.usage_limit))?.code;
  return <div className="class-code"><span>课程码</span><strong>{code ?? "—"}</strong>
    {code ? <button type="button" className="text-button" onClick={() => {
      void copyText(code).then((copied) => toast.notify(copied ? "课程码已复制" : "请选中课程码手动复制"));
    }}><TeacherIcon name="copy" />复制</button> :
      <Link className="text-button" to={`/courses/${courseId}/enrollments#course-invitation`}>管理邀请码</Link>}
  </div>;
}

export function CourseLayout({ children, home = "/" }: { children: ReactNode; home?: string }) {
  const { courseId = "" } = useParams();
  const { pathname, hash } = useLocation();
  const [params] = useSearchParams();
  const course = useQuery({ queryKey: keys.teachingCourse(courseId), queryFn: () => teachingApi.course(courseId) });
  const publications = useAgendaPublications(courseId);
  const base = `/courses/${courseId}`;
  const active = pathname === base + "/enrollments" ? "/enrollments" :
    pathname === base + "/analytics" ? "/analytics" :
      pathname === base && params.get("tab") === "schedule" ? "?tab=schedule" : "";
  return <>
    <header className="page-heading">
      <div><Link className="back" to={home}><TeacherIcon name="left" />返回教师工作台</Link>
        <h1>{course.data?.title ?? "课程教学空间"}</h1>
        <p className="meta">{course.data?.term_name && <span>{course.data.term_name}</span>}
          <span>{course.data?.active_enrollment_count ?? "—"} 名学生</span><span>{publications.data?.length ?? "—"} 个实验</span></p>
      </div>
      {course.isSuccess && <CourseCode key={courseId} courseId={courseId} />}
    </header>
    <div className="class-grid">
      <nav className="class-nav" aria-label="教学班功能">{courseTabs.map(({ suffix, label, icon }) =>
        <Link key={label} to={base + suffix} aria-current={active === suffix ? "page" : undefined}><TeacherIcon name={icon} />{label}</Link>)}</nav>
      <div>
        {course.isError ? <RequestStateView loading={false} error={course.error} onRetry={() => void course.refetch()} empty={false} /> : children}
        {active === "/enrollments" && course.isSuccess && <details className="course-tools" id="course-invitation" open={hash === "#course-invitation" ? true : undefined}>
          <summary>管理课程邀请码</summary><CourseInvitationActions key={courseId} courseId={courseId} />
        </details>}
        {course.isSuccess && active !== "?tab=schedule" && <details className="course-tools">
          <summary>教学班管理</summary>
          <div className="actions"><Link className="btn" to={base + "/students"}>实验进度</Link>
            <Link className="btn" to={base + "/publishing"}>实验发布</Link>
            <Link className="btn" to={base + "/templates"}>实验模板</Link>
            <Link className="btn" to="/courses">管理教学班</Link></div>
          <CourseResources courseId={courseId} />
        </details>}
      </div>
    </div>
  </>;
}

function CourseResources({ courseId }: { courseId: string }) {
  const [opened, setOpened] = useState(false);
  return <details onToggle={(event) => setOpened(event.currentTarget.open)}>
    <summary>课程公告与章节资料</summary>
    {opened && <><CourseAnnouncements key={courseId} courseId={courseId} /><CourseMaterials key={courseId} courseId={courseId} /></>}
  </details>;
}

export function CourseOverview() {
  const { courseId = "" } = useParams();
  const [params] = useSearchParams();
  const showSchedule = params.get("tab") === "schedule";
  const course = useQuery({ queryKey: keys.teachingCourse(courseId), queryFn: () => teachingApi.course(courseId) });
  return showSchedule ? <CourseSchedule key={courseId} courseId={courseId} title={course.data?.title ?? "教学班"}
    termName={course.data?.term_name ?? ""} termId={course.data?.term_id ?? ""} /> : <CourseExperimentList key={courseId} courseId={courseId} />;
}

function CourseSchedule({ courseId, title, termName, termId }: { courseId: string; title: string; termName: string; termId: string }) {
  const schedule = useQuery({ queryKey: keys.teachingCourseTimetable(courseId), queryFn: () => timetableApi.teachingCourse(courseId) });
  const classes = [{ id: courseId, title }];
  return <RequestStateView loading={schedule.isLoading} error={schedule.error} onRetry={() => void schedule.refetch()} empty={false}>
    <ClassAgendaWeek term={{ id: termId, label: termName, calendar: schedule.data?.term?.calendar }}
      slots={asAgendaSlots(schedule.data?.schedules ?? [], classes)} classes={classes} today={schoolToday()} />
  </RequestStateView>;
}

function CourseExperimentList({ courseId }: { courseId: string }) {
  const [design, setDesign] = useState(false);
  const client = useQueryClient();
  const toast = useToast();
  const course = useQuery({ queryKey: keys.teachingCourse(courseId), queryFn: () => teachingApi.course(courseId) });
  const publications = useAgendaPublications(courseId);
  const experiments = publications.data ?? [];
  const reports = usePublicationReports(courseId, experiments);
  const publish = useMutation({
    mutationFn: () => teachingApi.publishCourse(courseId, String(course.data?.row_version ?? "")),
    onSuccess: () => { void client.invalidateQueries({ queryKey: keys.teachingCourses() }); toast.notify("课程已发布，学生可申请加入"); },
    onError: (error) => toast.notify(error.message, "error"),
  });
  const rows = experiments.map((publication, index): ExperimentRow => {
    const released = Boolean(publication.grades_published_at);
    const deadline = publication.window_end ?? publication.assignment_deadline;
    const underway = publication.status === "PUBLISHED" && (!deadline || Date.parse(deadline) > Date.now());
    const published = ["PUBLISHED", "CLOSED"].includes(publication.status);
    const awaiting = published && !underway && (publication.direct_assessment ?? !publication.template_version_id);
    const queue = reports[index]?.data;
    const count = queue?.filter((item) => ["SUBMITTED", "GRADED", "RETURNED"].includes(item.status)).length;
    return {
      id: publication.public_id, title: publication.title, deadline: schoolDateTime(deadline),
      status: released ? "成绩已发布" : underway ? "进行中" : awaiting ? "待审阅" : PUBLICATION_STATUS_LABEL[publication.status] ?? publication.status,
      tone: released ? "good" : underway ? "info" : awaiting ? "warn" : undefined,
      submitted: isReportPublication(publication) && count != null ? `${count}${queue?.length === 500 ? "+" : ""} / ${publication.audience_count ?? "—"}` : "—",
      href: published || released ? reviewLink(courseId, publication.public_id) : `/courses/${courseId}/publishing`,
      action: released ? "查看结果" : "查看实验",
    };
  });
  return <>
    {course.data?.status === "DRAFT" && <div className="page-actions"><Button variant="primary" disabled={publish.isPending} onClick={() => publish.mutate()}>
      {publish.isPending ? "发布中…" : "发布课程"}</Button></div>}
    <ClassExperiments rows={rows} actions={<button type="button" className="btn primary" onClick={() => setDesign(true)}>
      <TeacherIcon name="plus" />新建实验</button>}
      state={publications.isPending ? <p className="empty" role="status">正在读取实验…</p> :
        publications.isError ? <p className="empty" role="alert">无法读取实验。 <button type="button" className="text-button" onClick={() => void publications.refetch()}>重试</button></p> : undefined} />
    {reports.some((query) => query.isError) && <p className="empty" role="alert">部分报告提交数暂不可用。 <button type="button" className="text-button"
      onClick={() => reports.forEach((query) => { if (query.isError) void query.refetch(); })}>重试</button></p>}
    {design && <LabDesignDialog courseId={courseId} publicationId="" onClose={() => setDesign(false)}
      onSaved={() => { setDesign(false); void client.invalidateQueries({ queryKey: keys.publications(courseId) }); }} />}
  </>;
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
  return <Panel title={<h2>课程公告</h2>}>
    {rows.length > 0 && <div className="teacher-list">
      {rows.map((item) => <div className="item" key={item.public_id}>
        <div>
          <strong>{item.title}</strong>
          <small>{item.status === "PUBLISHED" ? `已发布 · ${item.published_at ? new Date(item.published_at).toLocaleString("zh-CN") : ""}` : "草稿"}{item.pinned ? " · 置顶" : ""}</small>
        </div>
      </div>)}
    </div>}
    {!rows.length && !announcements.isLoading && <p className="subtle">还没有公告。学生不会收到任何课程通知。</p>}
    <label style={{ display: "block", maxWidth: 680 }}>公告标题<input className="field" value={title} maxLength={160} onChange={(e) => setTitle(e.target.value)} placeholder="例如：随堂练习 11 月 19 日截止" /></label>
    <label style={{ display: "block", maxWidth: 680 }}>公告正文<textarea className="field" rows={4} value={body} onChange={(e) => setBody(e.target.value)} placeholder="写清楚要做什么、什么时候截止、有问题找谁。" /></label>
    <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <input type="checkbox" checked={pinned} onChange={(e) => setPinned(e.target.checked)} /> 置顶这条公告
    </label>
    {(title.trim() || body.trim()) ? <div className="section" aria-label="学生看到的预览">
      <p className="subtle">学生将看到：</p>
      <div className="panel" style={{ padding: 14 }}>
        <strong>{title.trim() || "（公告标题）"}</strong>
        <p style={{ whiteSpace: "pre-wrap", margin: "6px 0 0" }}>{body.trim() || "（公告正文）"}</p>
      </div>
    </div> : null}
    <Button variant="primary" disabled={!title.trim() || create.isPending} onClick={() => create.mutate()}>
      {create.isPending ? "发布中…" : "发布公告"}
    </Button>
  </Panel>;
}
