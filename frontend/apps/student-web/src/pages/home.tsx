import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { assessmentApi, studentApi, taskApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, Metric, Panel, RequestStateView, StatusBadge } from "@edu/ui";
import type { CalendarItem } from "@edu/ui";
import { isTaskActionable, taskStatusLabel, taskStatusTone, formatDate } from "@/lib/task-format";
import { StudentJournal } from "@/components/student-journal";
import { useStudentTimetable } from "@/lib/use-student-timetable";

const TERMINAL_STATUSES = new Set(["COMPLETED", "WITHDRAWN"]);
const UNFINISHED_STATUSES = new Set(["ASSIGNED", "IN_PROGRESS", "REPORT_DRAFT", "REJECTED", "FAILED"]);
const FOCUSED_TASKS_PAGE_SIZE = 3;

export function Home() {
  const navigate = useNavigate();
  const [dateChoice, setDateChoice] = useState<{ term?: string; date: string } | null>(null);
  const [taskPagination, setTaskPagination] = useState<{ date: string | null; page: number }>({ date: null, page: 1 });
  const schedule = useStudentTimetable();

  const tasksQuery = useQuery({ queryKey: keys.tasks({ scope: "my" }), queryFn: () => taskApi.list({ page_size: 50 }) });
  const enrollmentsQuery = useQuery({ queryKey: keys.enrollments({ status: "ACTIVE" }), queryFn: () => studentApi.myEnrollments({ status: "ACTIVE", page_size: 100 }) });

  const tasks = useMemo(() => tasksQuery.data?.rows ?? [], [tasksQuery.data]);
  const courseNames = useMemo(() => new Map((enrollmentsQuery.data?.rows ?? []).map((enrollment) => [
    enrollment.course_id,
    enrollment.course_title || enrollment.course_code || enrollment.course_id,
  ])), [enrollmentsQuery.data]);
  const courseNamesLoaded = enrollmentsQuery.isSuccess;
  const activeTasks = useMemo(() => tasks.filter((task) => !TERMINAL_STATUSES.has(task.status)), [tasks]);
  const draftCount = tasks.filter((task) => task.status === "REPORT_DRAFT").length;
  const inProgressCount = tasks.filter((task) => ["IN_PROGRESS", "REPORT_DRAFT"].includes(task.status)).length;
  const completedTasks = useMemo(() => tasks.filter((task) => task.status === "COMPLETED"), [tasks]);
  const earliestDeadline = activeTasks
    .map((task) => task.effective_deadline)
    .filter((deadline): deadline is string => Boolean(deadline))
    .sort()[0];

  /** 最近一次评分：取已公开的分卷总成绩（最多查 3 个） */
  const completedKey = completedTasks.map((task) => task.public_id).join("|");
  const recentReviews = useQuery({
    queryKey: ["recent-review-scores", completedKey],
    queryFn: async () => {
      const targets = completedTasks.slice(0, 3);
      return Promise.all(targets.map(async task => {
        const assessment = await assessmentApi.get(task.public_id).catch(() => null);
        if (!assessment?.sections.length || assessment.sections.some(section => section.score == null)) return null;
        return { score: assessment.sections.reduce((sum, section) => sum + Number(section.score), 0) };
      }));
    },
    enabled: completedTasks.length > 0,
    staleTime: 60_000,
  });

  /** 本周学习节奏：服务端 /me/dashboard 聚合本周判题执行时长(分钟) */
  const dashboard = useQuery({ queryKey: keys.studentDashboard(), queryFn: () => studentApi.dashboard(), staleTime: 60_000 });
  const weeklyStudy = dashboard.data?.weekly_study;

  const totalMinutes = weeklyStudy?.total_minutes ?? 0;
  const lastWeekMinutes = weeklyStudy?.last_week_minutes ?? 0;
  const weeklySub = dashboard.data == null
    ? "统计加载中"
    : (!weeklyStudy?.has_records
      ? "本周还没有学习记录"
      : lastWeekMinutes > 0
        ? totalMinutes >= lastWeekMinutes
          ? `比上周多 ${totalMinutes - lastWeekMinutes} 分钟`
          : `比上周少 ${lastWeekMinutes - totalMinutes} 分钟`
        : "上周没有执行记录");

  const latestScore = (recentReviews.data ?? []).find(review => review?.score != null)?.score ?? null;
  const reviewedSub = completedTasks.length === 0
    ? "尚未获得评审"
    : latestScore != null
      ? `最近一次评分 ${latestScore} 分`
      : `共 ${completedTasks.length} 个任务已完成评审`;

  const calendarItems = useMemo<CalendarItem[]>(() => {
    const rows: CalendarItem[] = [];
    const classes = schedule.timetable.data?.classes;
    if (!classes) return rows;
    const courseIds = new Set(classes.map(course => course.course_id));
    for (const task of tasks) {
      if (!courseIds.has(task.course_id)) continue;
      const deadline = task.effective_deadline || task.window_end;
      if (!isTaskActionable(task) || !deadline) continue;
      const dateKey = (value: string) => {
        const parsed = new Date(value.length === 10 ? `${value}T12:00:00` : value);
        return Number.isNaN(parsed.getTime()) ? "" : `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, "0")}-${String(parsed.getDate()).padStart(2, "0")}`;
      };
      const start = dateKey(task.window_start || deadline);
      const end = dateKey(deadline);
      if (!start || !end) continue;
      const cursor = new Date(`${start}T12:00:00`);
      const last = new Date(`${end}T12:00:00`);
      for (let guard = 0; cursor <= last && guard < 366; guard += 1) {
        const date = `${cursor.getFullYear()}-${String(cursor.getMonth() + 1).padStart(2, "0")}-${String(cursor.getDate()).padStart(2, "0")}`;
        rows.push({
          date,
          title: task.title,
          context: courseNames.get(task.course_id),
          subtitle: `完成度 ${task.progress}% · 截止 ${formatDate(deadline)}`,
          statusLabel: taskStatusLabel(task.status),
          statusTone: taskStatusTone(task.status),
          done: !UNFINISHED_STATUSES.has(task.status),
          onClick: () => navigate(task.assessment_available
            ? `/experiments/${task.public_id}/assessment`
            : `/experiments/${task.public_id}`),
        });
        cursor.setDate(cursor.getDate() + 1);
      }
    }
    return rows;
  }, [tasks, courseNames, navigate, schedule.timetable.data]);

  const todayKey = useMemo(() => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  }, []);

  const focusDate = useMemo(() => {
    const dates = [...new Set(calendarItems.filter((item) => !item.done).map((item) => item.date))].sort();
    return dates.find((date) => date >= todayKey) ?? dates[0] ?? null;
  }, [calendarItems, todayKey]);

  const termId = schedule.timetable.data?.term.public_id;
  const selectedDate = (dateChoice && (dateChoice.term == null || dateChoice.term === termId) ? dateChoice.date : null) ?? focusDate ?? todayKey;
  const selectDate = (date: string) => {
    setDateChoice({ term: termId, date });
    setTaskPagination({ date, page: 1 });
  };
  const selectTerm = (id: string) => {
    setDateChoice(null);
    setTaskPagination({ date: null, page: 1 });
    schedule.selectTerm(id);
  };

  const focusedItems = calendarItems.filter((item) => item.date === selectedDate);
  const taskPageCount = Math.max(1, Math.ceil(focusedItems.length / FOCUSED_TASKS_PAGE_SIZE));
  const taskPage = taskPagination.date === selectedDate ? Math.min(taskPagination.page, taskPageCount) : 1;
  const visibleItems = focusedItems.slice((taskPage - 1) * FOCUSED_TASKS_PAGE_SIZE, taskPage * FOCUSED_TASKS_PAGE_SIZE);

  const formatHours = (minutes: number) => (minutes >= 60 ? `${(minutes / 60).toFixed(1)} h` : `${minutes} min`);

  return (
    <>
      <StudentJournal schedule={{ ...schedule, selectTerm }} date={selectedDate} items={calendarItems} onSelect={selectDate}>
        <RequestStateView loading={tasksQuery.isLoading || schedule.timetable.isPending} error={tasksQuery.error || schedule.timetable.error}
          onRetry={() => { void tasksQuery.refetch(); void schedule.timetable.refetch(); }}
          empty={!focusedItems.length}
          emptyState={<p className="agenda-empty">{calendarItems.length ? "当天没有待办" : "暂无待办任务"}</p>}>
          <div className="calendar-focus-list" aria-live="polite">
            <div className="eyebrow">{formatDate(selectedDate)} · {focusedItems.length} 项待办</div>
            {visibleItems.map((item, index) => (
              <button key={`${item.title}-${index}`} type="button" className="calendar-focus-task" onClick={item.onClick}>
                <span><small className="calendar-focus-course">{item.context ?? (courseNamesLoaded ? "未归属课程" : "")}</small><strong>{item.title}</strong><small>{item.subtitle}</small></span>
                <StatusBadge tone={item.statusTone ?? "neutral"}>{item.statusLabel}</StatusBadge>
              </button>
            ))}
            {taskPageCount > 1 && (
              <nav aria-label="待完成任务分页" style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", flexWrap: "wrap", gap: 8 }}>
                <Button size="sm" disabled={taskPage === 1}
                  onClick={() => setTaskPagination({ date: selectedDate, page: taskPage - 1 })}>上一页</Button>
                <span className="subtle">第 {taskPage} / {taskPageCount} 页</span>
                <Button size="sm" disabled={taskPage === taskPageCount}
                  onClick={() => setTaskPagination({ date: selectedDate, page: taskPage + 1 })}>下一页</Button>
              </nav>
            )}
          </div>
        </RequestStateView>
      </StudentJournal>
      <Panel className="section agenda-metrics" title={<><h2>学习概览</h2><span className="subtle">全部课程</span></>}>
        <RequestStateView loading={tasksQuery.isLoading && !tasks.length}
          error={tasksQuery.error}
          onRetry={() => { void tasksQuery.refetch(); }}
          empty={false} emptyState={null}>
          <div className="metric-strip">
            <Metric label="进行中的实验" value={String(inProgressCount)}
              sub={draftCount > 0 ? `其中 ${draftCount} 个待提交` : "暂无待提交"} />
            <Metric label="本周学习时长" value={formatHours(totalMinutes)} sub={weeklySub} />
            <Metric label="待完成任务" value={String(activeTasks.length)}
              sub={earliestDeadline ? `最近截止 ${formatDate(earliestDeadline)}` : "暂无截止日期"} />
            <Metric label="已获评审" value={String(completedTasks.length)} sub={reviewedSub} />
          </div>
        </RequestStateView>
      </Panel>
    </>
  );
}
