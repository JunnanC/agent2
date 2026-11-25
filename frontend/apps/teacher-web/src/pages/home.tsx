import { useState, type ReactNode } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { teachingApi, timetableApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { TimetableImport } from "@/components/timetable-import";
import { LabEnvironments } from "@/components/lab-environments";
import { TeacherDialog } from "@/components/teacher-b";
import { TeachingAgenda, type AgendaClass, type AgendaTodo } from "@/components/teaching-agenda";
import { allPages } from "@/lib/all-pages";
import { asAgendaSlots, isReportPublication, publicationQuery, releaseQuery, reportsQuery, reviewLink, schoolToday } from "@/lib/teaching-agenda";

function queryState(loading: boolean, error: unknown, label: string, retry: () => void): ReactNode {
  if (error) return <p className="empty" role="alert">无法读取{label}。 <button className="text-button" type="button" onClick={retry}>重试</button></p>;
  if (loading) return <p className="empty" role="status">正在读取{label}…</p>;
  return null;
}

export function Home() {
  const [params, setParams] = useSearchParams();
  const termParam = params.get("term") || undefined;
  const [modal, setModal] = useState<"import" | "environments" | null>(null);
  const [environmentCourse, setEnvironmentCourse] = useState("");
  const timetable = useQuery({
    queryKey: keys.teachingTimetable(termParam),
    queryFn: () => timetableApi.teaching(termParam ? { term_id: termParam } : undefined),
    placeholderData: (previous) => previous,
  });
  const courses = useQuery({
    queryKey: keys.teachingCourses({ scope: "agenda" }),
    queryFn: () => allPages((page) => teachingApi.courses({ page, page_size: 100 })),
  });
  const data = timetable.isPlaceholderData ? undefined : timetable.data;
  const selectedTerm = data?.term ?? timetable.data?.terms.find((item) => item.public_id === termParam);
  const term = {
    id: selectedTerm?.public_id ?? termParam ?? "",
    label: selectedTerm?.name ?? "学期",
    calendar: selectedTerm?.calendar,
  };
  const courseRows = (courses.data ?? []).filter((course) =>
    data && (course.term_id === data.term.public_id || data.classes.some((entry) => entry.course_id === course.public_id)));
  const publications = useQueries({ queries: courseRows.map((course) => publicationQuery(course.public_id)) });
  const byId = new Map<string, AgendaClass>(courseRows.map((course, index) => [course.public_id, {
    id: course.public_id, title: course.title, students: course.active_enrollment_count ?? course.student_count,
    experiments: publications[index]?.data?.length,
  }]));
  for (const course of data?.classes ?? []) {
    if (!byId.has(course.course_id)) byId.set(course.course_id, { id: course.course_id, title: course.course_title, students: undefined, experiments: undefined });
  }
  const classes = [...byId.values()];
  const now = Date.now();
  const reviewTargets = courseRows.flatMap((course, index) => (publications[index]?.data ?? [])
    .filter((publication) => !publication.grades_published_at && ["PUBLISHED", "CLOSED"].includes(publication.status))
    .map((publication) => ({ course, publication, direct: publication.direct_assessment ?? !publication.template_version_id })));
  const release = useQueries({ queries: reviewTargets.map(({ course, publication, direct }) => ({
    ...releaseQuery(course.public_id, publication.public_id), enabled: direct,
  })) });
  const reports = useQueries({ queries: reviewTargets.map(({ course, publication, direct }) => ({
    ...reportsQuery(course.public_id, publication.public_id), enabled: !direct && isReportPublication(publication),
  })) });
  const todos: AgendaTodo[] = [];
  reviewTargets.forEach(({ course, publication, direct }, index) => {
    const releaseStatus = release[index]?.data;
    if (releaseStatus?.grades_published_at) return;
    const legacy = reports[index]?.data;
    const pending = direct ? releaseStatus?.pending_reports : legacy?.filter((row) => row.status === "SUBMITTED" && row.review_status !== "READY").length;
    const publishable = releaseStatus && pending === 0 && releaseStatus.pending_runs === 0 && releaseStatus.open_redos === 0 &&
      new Date(releaseStatus.deadline).getTime() <= now;
    if (!pending && !publishable) return;
    todos.push({ key: publication.public_id, href: reviewLink(course.public_id, publication.public_id),
      label: pending ? "批阅实验报告" : "发布实验成绩", meta: `${course.title} · ${publication.title}`,
      count: pending ? `${pending}${!direct && legacy?.length === 500 ? "+" : ""} 份` : "可发布" });
  });
  for (const course of courseRows) {
    if (course.pending_enrollments) todos.push({
      key: `enroll-${course.public_id}`, href: `/courses/${course.public_id}/enrollments`, label: "审核入班申请",
      meta: course.title, count: `${course.pending_enrollments} 人`,
    });
  }
  const todoRequests = [...publications, ...release, ...reports];
  function selectTerm(id: string) {
    const next = new URLSearchParams(params);
    next.set("term", id);
    setParams(next);
  }
  const selectedEnvironment = classes.find(({ id }) => id === environmentCourse);

  return <>
    <TeachingAgenda term={term}
      terms={(timetable.data?.terms ?? []).map((item) => ({ id: item.public_id, label: item.name }))}
      classes={classes} slots={asAgendaSlots(data?.schedules ?? [], classes)} todos={todos} today={schoolToday()}
      onTerm={selectTerm} onImport={() => setModal("import")} onEnvironments={() => { setEnvironmentCourse(""); setModal("environments"); }}
      classActions={<Link className="text-button class-management" to="/courses">管理教学班</Link>}
      scheduleState={queryState(timetable.isPending || timetable.isPlaceholderData, timetable.error, "课表", () => void timetable.refetch())}
      classesState={queryState(courses.isPending || timetable.isPending || timetable.isPlaceholderData, courses.error ?? timetable.error, "教学班", () => { void courses.refetch(); if (timetable.isError) void timetable.refetch(); })}
      todosState={queryState(todoRequests.some((query) => query.isLoading),
        todoRequests.find((query) => query.isError)?.error, "部分教学待办",
        () => { for (const query of todoRequests) if (query.isError) void query.refetch(); })}
    />
    {modal === "import" && data && <TeacherDialog title="导入课表" onClose={() => setModal(null)}><TimetableImport termId={data.term.public_id} /></TeacherDialog>}
    {modal === "environments" && !selectedEnvironment && <TeacherDialog title="实验环境" onClose={() => setModal(null)}>
      {classes.length ? <label className="fields">请选择教学班<select value="" onChange={(event) => setEnvironmentCourse(event.target.value)}>
        <option value="">选择教学班</option>{classes.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}
      </select></label> : <p>本学期暂无教学班。<Link className="text-button" to="/courses">管理教学班</Link></p>}
    </TeacherDialog>}
    {modal === "environments" && selectedEnvironment && <LabEnvironments courseId={selectedEnvironment.id} onClose={() => setModal(null)} />}
  </>;
}
