import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { assessmentTeachingApi, teachingApi } from "@edu/api-client";
import type { Publication } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import {
  Breadcrumbs, LineChart, Metric, Panel, RequestStateView, StatusBadge,
} from "@edu/ui";
import type { ChartSeries } from "@edu/ui";
import { COURSE_STATUS_LABEL, PUBLICATION_STATUS_LABEL } from "@/lib/format";

interface PendingReviewRow {
  public_id: string;
  status: string;
  auto_check_result?: string | null;
}

/** 近 7 天日期标签（与原型一致：MM/DD） */
function lastSevenDayLabels(): string[] {
  const labels: string[] = [];
  for (let offset = -6; offset <= 0; offset += 1) {
    const date = new Date();
    date.setDate(date.getDate() + offset);
    labels.push(`${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")}`);
  }
  return labels;
}

function lastSevenIsoDays(): string[] {
  return Array.from({ length: 7 }, (_, index) => {
    const date = new Date();
    date.setDate(date.getDate() - 6 + index);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  });
}

interface TodoItem {
  key: string;
  title: string;
  sub: string;
  actionLabel: string;
  action: "enter" | "view" | "publish";
  href: string;
  primary?: boolean;
}

export function Home() {
  const courses = useQuery({ queryKey: keys.teachingCourses(), queryFn: () => teachingApi.courses({ page_size: 50 }) });
  const rows = courses.data?.rows ?? [];

  /** 聚合：各课程发布 / 待评审 / 任务完成度，一次并行拉取 */
  const overview = useQuery({
    queryKey: [...keys.teachingCourses(), "overview-summary"],
    queryFn: async () => {
      const targets = courses.data?.rows ?? [];
      return Promise.all(targets.map(async (course) => {
        const [publications, pendingReviews, progress, trend] = await Promise.all([
          teachingApi.publications(course.public_id, {}).catch(() => ({ rows: [], page: 1, pageSize: 20, total: 0 })),
          assessmentTeachingApi.reviews(course.public_id).then(rows => ({ rows: rows.filter(row => row.kind === "PROGRAMMING" && row.review_status === "PENDING"), total: rows.filter(row => row.kind === "PROGRAMMING" && row.review_status === "PENDING").length })).catch(() => ({ rows: [], total: 0 })),
          teachingApi.progress(course.public_id, {}).catch(() => ({ rows: [], page: 1, pageSize: 20, total: 0 })),
          teachingApi.analyticsSeries?.(course.public_id, 7).catch(() => null) ?? Promise.resolve(null),
        ]);
        return { course, publications: publications.rows as Publication[], pendingReviews: pendingReviews as { rows: PendingReviewRow[]; total: number }, progress, trend };
      }));
    },
    enabled: rows.length > 0,
  });

  const perCourse = useMemo(() => overview.data ?? [], [overview.data]);

  const publishedCount = perCourse.reduce((sum, item) =>
    sum + item.publications.filter((publication) => publication.status === "PUBLISHED").length, 0);
  const pendingPublishCount = perCourse.reduce((sum, item) =>
    sum + item.publications.filter((publication) => ["DRAFT", "PRECHECK", "READY"].includes(publication.status)).length, 0);
  const pendingReviewTotal = perCourse.reduce((sum, item) => {
    const total = typeof item.pendingReviews.total === "number" ? item.pendingReviews.total : item.pendingReviews.rows.length;
    return sum + total;
  }, 0);
  const activeCourses = rows.filter((course) => course.status !== "ARCHIVED").length;

  const completionPercent = useMemo(() => {
    let done = 0;
    let total = 0;
    for (const item of perCourse) {
      const rowsList = (item.progress.rows ?? []) as Array<{ status: string }>;
      for (const row of rowsList) {
        total += 1;
        if (["COMPLETED", "APPROVED"].includes(row.status)) done += 1;
      }
    }
    return total > 0 ? Math.round((done / total) * 100) : null;
  }, [perCourse]);

  /** 需要你处理：待审核选课 + 待预检/待发布，取前 4 项 */
  const todoItems = useMemo<TodoItem[]>(() => {
    const items: TodoItem[] = [];
    for (const item of perCourse) {
      const pendingEnroll = item.course.pending_enrollments ?? 0;
      if (pendingEnroll > 0) {
        items.push({
          key: `enroll-${item.course.public_id}`,
          title: `${item.course.title} · 选课审核`,
          sub: `${pendingEnroll} 个学生提交申请`,
          actionLabel: "进入",
          action: "enter",
          href: `/courses/${item.course.public_id}/enrollments`,
        });
      }
      for (const publication of item.publications
        .filter((row) => ["DRAFT", "PRECHECK", "READY"].includes(row.status))
        .slice(0, 2)) {
        const canPublish = (publication.allowed_actions ?? []).includes("publish");
        items.push({
          key: `pub-${publication.public_id}`,
          title: `${publication.template_name ?? publication.title} · ${publication.status === "READY" ? "发布窗口" : "版本预检"}`,
          sub: publication.status === "READY" ? "预检已完成，等待发布" : `${PUBLICATION_STATUS_LABEL[publication.status] ?? publication.status} · 配置完成后发布`,
          actionLabel: canPublish ? "发布" : "查看",
          action: canPublish ? "publish" : "view",
          href: `/courses/${item.course.public_id}/publishing`,
          primary: canPublish,
        });
      }
    }
    return items.slice(0, 4);
  }, [perCourse]);

  const chartSeries: ChartSeries[] = useMemo(() => {
    const days = lastSevenIsoDays();
    const buckets = new Map(days.map((day) => [day, { done: 0, total: 0 }]));
    for (const item of perCourse) {
      for (const row of item.trend?.series ?? []) {
        const bucket = buckets.get(row.period_start.slice(0, 10));
        if (!bucket) continue;
        const metrics = row.metrics as { tasks?: Record<string, number>; task_total?: number };
        bucket.done += (metrics.tasks?.APPROVED ?? 0) + (metrics.tasks?.COMPLETED ?? 0);
        bucket.total += metrics.task_total ?? 0;
      }
    }
    const data = days.map((day) => {
      const bucket = buckets.get(day)!;
      return bucket.total > 0 ? Math.round((bucket.done / bucket.total) * 100) : null;
    });
    return [{ name: "班级实验完成率（%）", color: "var(--teal)", data }];
  }, [perCourse]);
  const hasChartData = chartSeries.some((series) => series.data.some((value) => value != null));

  return (
    <>
      <Breadcrumbs items={[{ label: "教师门户" }]} current="教学概览" />
      <div className="overview-heading">
        <h1>教学概览</h1>
        <div className="page-actions align-end">
          <Link className="btn" to={rows.length > 0 ? `/courses/${rows[0]!.public_id}/analytics` : "/courses"}>查看教学分析</Link>
          <Link className="btn primary" to="/courses">新建实验模板</Link>
        </div>
      </div>

      <Panel className="section">
        <RequestStateView loading={courses.isLoading && !rows.length}
          error={courses.error}
          onRetry={() => void courses.refetch()}
          empty={false} emptyState={null}>
          <div className="metric-strip">
            <Metric label="授课课程" value={String(activeCourses)} icon="book" sub={`共 ${rows.length} 门`} />
            <Metric label="进行中实验" value={String(publishedCount)} icon="flask"
              sub={pendingPublishCount > 0 ? `${pendingPublishCount} 个版本待发布` : "暂无待发布版本"} />
            <Metric label="待评审报告" value={String(pendingReviewTotal)} icon="file-check"
              sub={pendingReviewTotal > 0 ? "需要你处理" : "暂无待评审"} />
            <Metric label="班级完成率" value={completionPercent != null ? `${completionPercent}%` : "—"} icon="chart"
              sub="本学期累计" />
          </div>
        </RequestStateView>
      </Panel>

      <div className="grid equal section">
        <Panel title={<><h2>班级实验进度</h2><span className="subtle">近 7 天</span></>}>
          <RequestStateView loading={overview.isLoading && !perCourse.length}
            error={overview.error}
            onRetry={() => void overview.refetch()}
            empty={false} emptyState={null}>
            {hasChartData ? (
              <LineChart labels={lastSevenDayLabels()} series={chartSeries} unit="%"
                emptyHint="完成率按课程的每日聚合生成，当前还没有历史数据" />
            ) : (
              <div className="chart-empty" role="status">
                <strong>暂无历史数据</strong>
                <p>完成率按课程的每日聚合生成，积累一天学习记录后显示。</p>
              </div>
            )}
          </RequestStateView>
        </Panel>
        <Panel title={<><h2>需要你处理</h2>
          {todoItems.length ? <StatusBadge tone="warn">{todoItems.length} 项</StatusBadge> : null}
        </>}>
          <RequestStateView loading={overview.isLoading && !perCourse.length}
            error={overview.error}
            onRetry={() => void overview.refetch()}
            empty={!todoItems.length}
            emptyState={<div className="state-block overview-todos-empty"><strong>暂无需要处理的事务</strong><p>选课审核与发布待办会集中显示在这里。</p></div>}>
            <div>
              {todoItems.map((item) => (
                <div className="item" key={item.key}>
                  <div style={{ minWidth: 0 }}>
                    <strong>{item.title}</strong>
                    <small>{item.sub}</small>
                  </div>
                  {item.primary
                    ? <Link className="btn sm primary" to={item.href}>{item.actionLabel}</Link>
                    : <Link className="btn sm" to={item.href}>{item.actionLabel}</Link>}
                </div>
              ))}
            </div>
          </RequestStateView>
        </Panel>
      </div>

      <Panel className="section" title={<h2>近期课程</h2>}
        actions={<Link className="btn sm" to="/courses">全部课程</Link>}>
        <RequestStateView
          loading={courses.isLoading}
          error={courses.error}
          onRetry={() => void courses.refetch()}
          empty={!rows.length}
          emptyState={(
            <div className="state-block">
              <strong>还没有授课课程</strong>
              <p>在「我的课程」创建课程，然后完善实验模板与发布。</p>
            </div>
          )}
        >
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>课程</th><th>学生</th><th>实验完成率</th><th>待评审</th><th>状态</th></tr></thead>
              <tbody>
                {rows.map((course) => {
                  const item = perCourse.find((entry) => entry.course.public_id === course.public_id);
                  const done = ((item?.progress.rows ?? []) as Array<{ status: string }>).filter((progress) => ["COMPLETED", "APPROVED"].includes(progress.status)).length;
                  const total = ((item?.progress.rows ?? []) as Array<{ status: string }>).length;
                  const rate = total > 0 ? Math.round((done / total) * 100) : null;
                  const pending = item ? (typeof item.pendingReviews.total === "number" ? item.pendingReviews.total : item.pendingReviews.rows.length) : 0;
                  return (
                    <tr key={course.public_id}>
                      <td>
                        <strong>{course.title}</strong>
                        <small style={{ display: "block" }}>{course.code}</small>
                      </td>
                      <td>{course.active_enrollment_count ?? "—"}</td>
                      <td>{rate != null ? `${rate}%` : "—"}</td>
                      <td>{pending > 0 ? `${pending} 份` : "0 份"}</td>
                      <td>
                        <StatusBadge tone={course.status === "PUBLISHED" ? "good"
                          : course.status === "DRAFT" ? "warn" : "neutral"}>
                          {COURSE_STATUS_LABEL[course.status] ?? course.status}
                        </StatusBadge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </RequestStateView>
      </Panel>
    </>
  );
}
