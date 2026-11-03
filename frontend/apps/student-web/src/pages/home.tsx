import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { reportApi, studentApi, taskApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Breadcrumbs, DateCalendar, Metric, Panel, RequestStateView, StatusBadge } from "@edu/ui";
import type { CalendarItem } from "@edu/ui";
import { isTaskActionable, taskStatusLabel, taskStatusTone, formatDate } from "@/lib/task-format";
const TERMINAL_STATUSES = new Set(["COMPLETED", "WITHDRAWN"]);

export function Home() {
  const navigate = useNavigate();
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  const tasksQuery = useQuery({ queryKey: keys.tasks({ scope: "my" }), queryFn: () => taskApi.list({ page_size: 50 }) });
  const enrollmentsQuery = useQuery({ queryKey: keys.enrollments({ status: "ACTIVE" }), queryFn: () => studentApi.myEnrollments({ status: "ACTIVE", page_size: 100 }) });

  const tasks = useMemo(() => tasksQuery.data?.rows ?? [], [tasksQuery.data]);
  const courseNames = useMemo(() => new Map((enrollmentsQuery.data?.rows ?? []).map((enrollment) => [
    enrollment.course_id,
    enrollment.course_title || enrollment.course_code || enrollment.course_id,
  ])), [enrollmentsQuery.data]);
  const activeTasks = useMemo(() => tasks.filter((task) => !TERMINAL_STATUSES.has(task.status)), [tasks]);
  const draftCount = tasks.filter((task) => task.status === "REPORT_DRAFT").length;
  const inProgressCount = tasks.filter((task) => ["PROVISIONING", "READY", "IN_PROGRESS", "REPORT_DRAFT"].includes(task.status)).length;
  const completedTasks = useMemo(() => tasks.filter((task) => task.status === "COMPLETED"), [tasks]);
  const earliestDeadline = activeTasks
    .map((task) => task.effective_deadline)
    .filter((deadline): deadline is string => Boolean(deadline))
    .sort()[0];

  /** 最近一次评分：取已完成评审任务的 review-result（最多查 3 个） */
  const completedKey = completedTasks.map((task) => task.public_id).join("|");
  const recentReviews = useQuery({
    queryKey: ["recent-review-scores", completedKey],
    queryFn: async () => {
      const targets = completedTasks.slice(0, 3);
      return Promise.all(targets.map((task) => reportApi.reviewResult(task.public_id).catch(() => null)));
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
    for (const task of tasks) {
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
          onClick: () => navigate(task.allowed_actions.includes("enter") || task.allowed_actions.includes("view_workbench")
            ? `/experiments/${task.public_id}/workbench`
            : `/experiments/${task.public_id}`),
        });
        cursor.setDate(cursor.getDate() + 1);
      }
    }
    return rows;
  }, [tasks, courseNames, navigate]);

  const firstTaskDate = useMemo(
    () => calendarItems.map((item) => item.date).sort()[0] ?? null,
    [calendarItems],
  );

  useEffect(() => {
    if (!selectedDate && firstTaskDate) setSelectedDate(firstTaskDate);
  }, [firstTaskDate, selectedDate]);

  const focusedItems = selectedDate ? calendarItems.filter((item) => item.date === selectedDate) : [];

  const formatHours = (minutes: number) => (minutes >= 60 ? `${(minutes / 60).toFixed(1)} h` : `${minutes} min`);

  return (
    <>
      <Breadcrumbs items={[{ label: "学生门户" }]} current="概览" />

      {/* 四个数据卡片：条带式单块，列间分隔线，内容等距 */}
      <Panel className="section">
        <RequestStateView loading={tasksQuery.isLoading && !tasks.length}
          error={tasksQuery.error}
          onRetry={() => { void tasksQuery.refetch(); }}
          empty={false} emptyState={null}>
          <div className="metric-strip">
            <Metric label="进行中的实验" value={String(inProgressCount)} icon="flask"
              sub={draftCount > 0 ? `其中 ${draftCount} 个待提交` : "暂无待提交"} />
            <Metric label="本周学习时长" value={formatHours(totalMinutes)} icon="clock" sub={weeklySub} />
            <Metric label="待完成任务" value={String(activeTasks.length)} icon="calendar-clock"
              sub={earliestDeadline ? `最近截止 ${formatDate(earliestDeadline)}` : "暂无截止日期"} />
            <Metric label="已获评审" value={String(completedTasks.length)} icon="file-check" sub={reviewedSub} />
          </div>
        </RequestStateView>
      </Panel>

      <div className="grid two section">
        <Panel title={<><h2>任务日历</h2><span className="subtle">按实验开放区间查看每日待办</span></>}>
          <RequestStateView loading={tasksQuery.isLoading} error={tasksQuery.error}
            onRetry={() => void tasksQuery.refetch()} empty={!calendarItems.length}
            emptyState={<div className="state-block"><strong>暂无待办任务</strong><p>实验发布后，开放区间内每天都会显示对应待办。</p></div>}>
            <DateCalendar items={calendarItems} selectedDate={selectedDate} onDateSelect={setSelectedDate} showPopover={false} />
          </RequestStateView>
        </Panel>
        <Panel title={<><h2>待完成任务</h2><span className="subtle">点击左侧日期查看当天待办</span></>}>
          {selectedDate ? (
            focusedItems.length ? (
              <div className="calendar-focus-list" aria-live="polite">
                <div className="eyebrow">{formatDate(selectedDate)} · {focusedItems.length} 项待办</div>
                {focusedItems.map((item, index) => (
                  <button key={`${item.title}-${index}`} type="button" className="calendar-focus-task" onClick={item.onClick}>
                    <span><small className="calendar-focus-course">{item.context || "未归属课程"}</small><strong>{item.title}</strong><small>{item.subtitle}</small></span>
                    <StatusBadge tone={item.statusTone ?? "neutral"}>{item.statusLabel}</StatusBadge>
                  </button>
                ))}
              </div>
            ) : <div className="state-block"><strong>当天没有待办</strong><p>请选择日历中的其他日期。</p></div>
          ) : <div className="state-block"><strong>选择一个日期</strong><p>日期内的任务会在这里放大显示。</p></div>}
        </Panel>
      </div>
    </>
  );
}
