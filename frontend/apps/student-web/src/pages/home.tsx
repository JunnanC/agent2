import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { reportApi, studentApi, taskApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Breadcrumbs, DateCalendar, LineChart, Metric, Panel, RequestStateView, StatusBadge } from "@edu/ui";
import type { CalendarItem, ChartSeries } from "@edu/ui";
import { isTaskActionable, taskStatusLabel, taskStatusTone, formatDate } from "@/lib/task-format";
const TERMINAL_STATUSES = new Set(["COMPLETED", "WITHDRAWN"]);
const WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

export function Home() {
  const navigate = useNavigate();

  const tasksQuery = useQuery({ queryKey: keys.tasks({ scope: "my" }), queryFn: () => taskApi.list({ page_size: 50 }) });
  const enrollments = useQuery({ queryKey: keys.enrollments({ status: "ACTIVE" }), queryFn: () => studentApi.myEnrollments({ status: "ACTIVE", page_size: 50 }) });

  const tasks = useMemo(() => tasksQuery.data?.rows ?? [], [tasksQuery.data]);
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

  const series: ChartSeries[] = [
    {
      name: "学习时长（分钟）",
      color: "var(--teal)",
      data: weeklyStudy?.minutes_by_day ?? WEEKDAY_LABELS.map(() => null),
    },
  ];
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

  const pickedScore = (value: unknown): number | null => {
    if (value == null || typeof value !== "object") return null;
    for (const key of ["score", "score_total", "total_score", "final_score"]) {
      const candidate = (value as Record<string, unknown>)[key];
      if (typeof candidate === "number") return candidate;
    }
    return null;
  };
  const latestScore = (recentReviews.data ?? []).map(pickedScore).find((score) => score != null) ?? null;
  const reviewedSub = completedTasks.length === 0
    ? "尚未获得评审"
    : latestScore != null
      ? `最近一次评分 ${latestScore} 分`
      : `共 ${completedTasks.length} 个任务已完成评审`;

  /** 我的课程：按课程聚合任务进度与最近活动 */
  const courseRows = useMemo(() => {
    const rows = enrollments.data?.rows ?? [];
    return rows.map((enrollment) => {
      const courseTasks = tasks.filter((task) => task.course_id === enrollment.course_id);
      const completed = courseTasks.filter((task) => task.status === "COMPLETED").length;
      const latestTask = courseTasks
        .slice()
        .sort((a, b) => String(b.effective_deadline ?? "").localeCompare(String(a.effective_deadline ?? "")))[0];
      const progressText = courseTasks.length ? `${completed} / ${courseTasks.length} 个实验` : "暂无实验任务";
      const activity = latestTask
        ? `${taskStatusLabel(latestTask.status)} · 截止 ${formatDate(latestTask.effective_deadline)}`
        : "暂无任务动态";
      return {
        key: enrollment.public_id,
        courseId: enrollment.course_id,
        title: enrollment.course_title ?? enrollment.course_code ?? enrollment.course_id,
        progressText,
        percent: courseTasks.length ? Math.round((completed / courseTasks.length) * 100) : 0,
        activity,
        status: enrollment.status,
      };
    });
  }, [enrollments.data, tasks]);

  const calendarItems = useMemo<CalendarItem[]>(() => {
    const rows: CalendarItem[] = [];
    for (const task of tasks) {
      if (!isTaskActionable(task) || !task.effective_deadline) continue;
      rows.push({
        date: task.effective_deadline,
        title: task.title,
        subtitle: `完成度 ${task.progress}%`,
        statusLabel: taskStatusLabel(task.status),
        statusTone: taskStatusTone(task.status),
        onClick: () => navigate(task.allowed_actions.includes("enter") || task.allowed_actions.includes("view_workbench")
          ? `/experiments/${task.public_id}/workbench`
          : `/experiments/${task.public_id}`),
      });
    }
    return rows;
  }, [tasks, navigate]);

  const formatHours = (minutes: number) => (minutes >= 60 ? `${(minutes / 60).toFixed(1)} h` : `${minutes} min`);

  return (
    <>
      <Breadcrumbs items={[{ label: "学生门户" }]} current="概览" />

      {/* 四个数据卡片：条带式单块，列间分隔线，内容等距 */}
      <Panel className="section">
        <RequestStateView loading={tasksQuery.isLoading && !tasks.length}
          error={tasksQuery.error ?? enrollments.error}
          onRetry={() => { void tasksQuery.refetch(); void enrollments.refetch(); }}
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
        <Panel title={<><h2>任务日历</h2><span className="subtle">按截止日期查看待完成任务</span></>}>
          <RequestStateView loading={tasksQuery.isLoading} error={tasksQuery.error}
            onRetry={() => void tasksQuery.refetch()} empty={!calendarItems.length}
            emptyState={<div className="state-block"><strong>暂无截止任务</strong><p>实验发布后任务会出现在日历上。</p></div>}>
            <DateCalendar items={calendarItems} />
          </RequestStateView>
        </Panel>
        <Panel title={<><h2>本周学习节奏</h2><span className="subtle">{`${WEEKDAY_LABELS[0]} — ${WEEKDAY_LABELS[6]}`}</span></>}>
          <RequestStateView loading={dashboard.isLoading && !dashboard.data}
            error={dashboard.error}
            onRetry={() => void dashboard.refetch()}
            empty={false} emptyState={null}>
            <LineChart labels={WEEKDAY_LABELS} series={series} unit="min" emptyHint="本周还没有实验执行记录。" />
          </RequestStateView>
        </Panel>
      </div>

      <Panel className="section" title={<h2>我的课程</h2>} actions={<Link className="btn sm" to="/courses">全部课程</Link>}>
        <RequestStateView
          loading={enrollments.isLoading}
          error={enrollments.error}
          onRetry={() => void enrollments.refetch()}
          empty={!courseRows.length}
          emptyState={(
            <div className="state-block">
              <strong>还没有加入课程</strong>
              <p>可以在「加入课程」页面查看本学期开放课程并提交申请。</p>
              <Link className="btn primary" to="/courses/join">加入课程</Link>
            </div>
          )}
        >
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>课程名</th><th>进度</th><th>最近活动</th><th>状态</th><th /></tr></thead>
              <tbody>
                {courseRows.map((row) => (
                  <tr key={row.key}>
                    <td style={{ minWidth: 150 }}><strong>{row.title}</strong></td>
                    <td style={{ minWidth: 150 }}>
                      <div className="progress"><span style={{ width: `${row.percent}%` }} /></div>
                      <small style={{ display: "block", marginTop: 3 }}>{row.progressText}</small>
                    </td>
                    <td data-wrap style={{ maxWidth: 260 }}>{row.activity}</td>
                    <td><StatusBadge tone={row.status === "ACTIVE" ? "good" : "warn"}>
                      {row.status === "ACTIVE" ? "进行中" : taskStatusLabel(row.status)}
                    </StatusBadge></td>
                    <td className="table-actions">
                      <Link className="btn sm primary" to={`/courses/${row.courseId}`}>进入课程</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </RequestStateView>
      </Panel>
    </>
  );
}
