import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { teachingApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import {
  Breadcrumbs, LineChart, Metric, Panel, RequestStateView, StatusBadge,
} from "@edu/ui";
import type { ChartSeries } from "@edu/ui";

const PERIOD_DAYS: Record<string, number> = { term: 56, month: 30 };

type DailyMetricRow = { period_start: string; metrics: Record<string, unknown> };

function completionRateOf(row: DailyMetricRow): number | null {
  const tasks = (row.metrics["tasks"] ?? {}) as Record<string, number>;
  const total = Number(row.metrics["task_total"] ?? 0);
  if (!total) return null;
  const done = (tasks["COMPLETED"] ?? 0) + (tasks["APPROVED"] ?? 0);
  return Math.round(((done / total) * 100));
}

export function Analytics() {
  const { courseId = "" } = useParams();
  const [period, setPeriod] = useState<"term" | "month">("term");
  const days = PERIOD_DAYS[period] ?? 28;

  const overview = useQuery({
    queryKey: keys.teachingAnalytics(courseId, "overview"),
    queryFn: () => teachingApi.analytics(courseId, "overview"),
  });
  const publications = useQuery({
    queryKey: keys.publications(courseId, {}),
    queryFn: () => teachingApi.publications(courseId, {}),
  });
  const progress = useQuery({
    queryKey: keys.teachingProgress(courseId, { scope: "all" }),
    queryFn: () => teachingApi.progress(courseId, { page_size: 100 }),
  });
  const series = useQuery({
    queryKey: keys.teachingAnalytics(courseId, "series", { days }),
    queryFn: () => teachingApi.analyticsSeries(courseId, days),
    staleTime: 60_000,
  });

  const overviewMetrics = (overview.data as { metrics?: Record<string, unknown> } | undefined)?.metrics ?? {};
  const rows = useMemo(() => progress.data?.rows ?? [], [progress.data]);

  const derived = useMemo(() => {
    let done = 0;
    let total = 0;
    for (const row of rows) {
      total += 1;
      if (row.status === "COMPLETED") done += 1;
    }
    const completion = total > 0 ? Math.round((done / total) * 100) : null;
    const perPublication = (publications.data?.rows ?? []).map((publication) => {
      const pubRows = rows.filter((row) => row.publication_id === publication.public_id);
      const pubDone = pubRows.filter((row) => row.status === "COMPLETED").length;
      const rate = pubRows.length ? Math.round((pubDone / pubRows.length) * 100) : null;
      return {
        key: publication.public_id,
        title: publication.title,
        students: publication.audience_count ?? pubRows.length,
        rate,
        attention: rate != null && rate < 60,
      };
    });
    return { completion, perPublication };
  }, [rows, publications.data]);

  const attentionCount = derived.perPublication.filter((item) => item.attention).length;

  const seriesRows = useMemo<DailyMetricRow[]>(
    () => (series.data?.series ?? []) as DailyMetricRow[],
    [series.data],
  );
  const trendLabels = seriesRows.map((row) => row.period_start.slice(5));
  const trendValues = seriesRows.map((row) => completionRateOf(row));
  const chartSeries: ChartSeries[] = [
    { name: "每日完成率（%）", color: "var(--teal)", data: trendValues },
  ];

  const durationMetric = typeof overviewMetrics["average_duration_minutes"] === "number"
    ? `${overviewMetrics["average_duration_minutes"]} min`
    : "—";
  const firstPass = typeof overviewMetrics["first_pass_rate"] === "number"
    ? `${overviewMetrics["first_pass_rate"]}%`
    : "—";

  return (
    <>
      <Breadcrumbs items={[{ label: "教师门户" }, { label: "课程" }]} current="教学分析" />
      <div className="page-actions align-end">
        <select className="field" style={{ width: 130 }} aria-label="统计周期" value={period}
          onChange={(event) => setPeriod(event.target.value === "month" ? "month" : "term")}>
          <option value="term">近 8 周</option>
          <option value="month">近 30 天</option>
        </select>
      </div>

      <Panel className="section">
        <RequestStateView loading={progress.isLoading && !rows.length}
          error={progress.error ?? publications.error}
          onRetry={() => { void progress.refetch(); void publications.refetch(); }}
          empty={false} emptyState={null}>
          <div className="metric-strip">
            <Metric label="平均完成率" value={derived.completion != null ? `${derived.completion}%` : "—"} icon="chart"
              sub="全部实验任务" />
            <Metric label="平均实验时长" value={durationMetric} icon="timer" sub="来自执行记录的每日聚合" />
            <Metric label="报告一次通过率" value={firstPass} icon="file-check"
              sub={firstPass === "—" ? "评审质量快照生成后展示" : "较上月"} />
            <Metric label="需要关注的实验" value={String(attentionCount)} icon="alert-triangle"
              sub="完成率低于 60%" />
          </div>
        </RequestStateView>
      </Panel>

      <div className="grid two section">
        <Panel title={<><h2>完成率趋势</h2><span className="subtle">{`最近 ${seriesRows.length} 天每日投影`}</span></>}>
          <RequestStateView loading={series.isLoading && !series.data}
            error={series.error}
            onRetry={() => void series.refetch()}
            empty={!seriesRows.length}
            emptyState={(
              <div className="state-block">
                <strong>暂无每日投影数据</strong>
                <p>每日分析投影生成后,这里将展示完成率趋势。</p>
              </div>
            )}>
            <LineChart labels={trendLabels.length ? trendLabels : ["—"]} series={chartSeries} unit="%"
              emptyHint="按每日投影生成,当前还没有历史数据" />
          </RequestStateView>
        </Panel>
        <Panel title={<h2>各实验完成情况</h2>}>
          <RequestStateView
            loading={publications.isLoading}
            error={publications.error}
            onRetry={() => void publications.refetch()}
            empty={!derived.perPublication.length}
            emptyState={(
              <div className="state-block">
                <strong>暂无实验发布</strong>
                <p>实验发布并产生任务后，这里按实验展示完成率。</p>
              </div>
            )}
          >
            <div>
              {derived.perPublication.map((item) => (
                <div className="item" key={item.key}>
                  <div style={{ minWidth: 0 }}>
                    <strong>{item.title}</strong>
                    <small>{item.students} 名学生{item.rate != null ? ` · ${item.rate}% 完成` : ""}</small>
                  </div>
                  <StatusBadge tone={item.attention ? "warn" : "good"}>
                    {item.attention ? "需关注" : "稳定"}
                  </StatusBadge>
                </div>
              ))}
            </div>
          </RequestStateView>
        </Panel>
      </div>
    </>
  );
}
