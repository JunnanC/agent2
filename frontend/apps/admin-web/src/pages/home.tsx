import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { platformApi } from "@edu/api-client";
import type { Anomaly } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import {
  BarChart, Breadcrumbs, ChartLegend, EmptyState, LineChart, Metric, Panel, RequestStateView, StatusBadge,
} from "@edu/ui";
import { lastDayLabels } from "@/lib/csv";

export function Home() {
  const overview = useQuery({ queryKey: keys.operationsOverview(), queryFn: () => platformApi.operationsOverview() });
  const alerts = useQuery({ queryKey: keys.governanceAlerts({}), queryFn: () => platformApi.governanceAlerts({}) });
  const adapters = useQuery({ queryKey: keys.runtimeAdapters({}), queryFn: () => platformApi.runtimeAdapters() });
  const anomalies = useQuery({ queryKey: keys.anomalies({ page_size: 100 }), queryFn: () => platformApi.anomalies({ page_size: 100 }) });
  const scanAnomalies = useQuery({ queryKey: keys.scanAnomalies({ page_size: 50 }), queryFn: () => platformApi.scanAnomalies({ page_size: 50 }) });

  const summary = overview.data as { counts?: Record<string, number>; health?: Array<{ name: string; status: string; detail?: string }> } | undefined;
  const counts = summary?.counts ?? {};

  const adapterRows = adapters.data?.rows ?? [];
  const cpuAvailable = adapterRows.reduce((sum, row) => sum + (row.available_cpu_millicores ?? 0), 0);
  const cpuCapacity = adapterRows.reduce((sum, row) => sum + (row.capacity_cpu_millicores ?? 0), 0);
  const cpuUsage = cpuCapacity > 0 ? Math.round(((cpuCapacity - cpuAvailable) / cpuCapacity) * 100) : null;

  const allAnomalies = useMemo<Anomaly[]>(() => [
    ...(anomalies.data?.rows ?? []),
    ...(scanAnomalies.data?.rows ?? []),
  ], [anomalies.data, scanAnomalies.data]);
  const anomaliesByDay = useMemo(() => {
    const labels = lastDayLabels(7);
    const counts = labels.map(() => 0);
    for (const anomaly of allAnomalies) {
      if (!anomaly.occurred_at) continue;
      const occurred = new Date(anomaly.occurred_at);
      const todayMidnight = new Date();
      todayMidnight.setHours(0, 0, 0, 0);
      occurred.setHours(0, 0, 0, 0);
      const diffDays = Math.floor((todayMidnight.getTime() - occurred.getTime()) / 86_400_000);
      if (diffDays >= 0 && diffDays < 7) counts[6 - diffDays] = (counts[6 - diffDays] ?? 0) + 1;
    }
    return { labels, counts };
  }, [allAnomalies]);

  return (
    <>
      <Breadcrumbs items={[]} current="平台概览" />
      <div className="page-actions align-end">
        <Link className="btn" to="/audit">查看操作日志</Link>
      </div>

      <Panel className="section">
        <RequestStateView loading={overview.isLoading && adapters.isLoading}
          error={overview.error ?? adapters.error}
          onRetry={() => { void overview.refetch(); void adapters.refetch(); }}
          empty={false} emptyState={null}>
          <div className="metric-strip">
            <Metric label="运行工作区" value={String(counts["active_workspaces"] ?? "—")} icon="boxes"
              sub={`总数 ${counts["instances"] ?? "—"} 实例`} />
            <Metric label="CPU 使用率" value={cpuUsage != null ? `${cpuUsage}%` : "—"} icon="cpu"
              sub={`集群总量 ${Math.round(cpuCapacity / 1000)} vCPU`} />
            <Metric label="治理告警" value={String(alerts.data?.rows.length ?? 0)} icon="shield"
              sub={`${(alerts.data?.rows ?? []).filter((alert) => alert.level === "HIGH").length} 项高优先级`} />
            <Metric label="异常事项" value={String(allAnomalies.length)} icon="alert-triangle"
              sub="任务与资源" />
          </div>
        </RequestStateView>
      </Panel>

      <div className="grid two section">
        <Panel title={<><h2>资源使用趋势</h2><span className="subtle">最近 24 小时</span></>}>
          <ChartLegend items={[{ name: "CPU", color: "var(--teal)" }, { name: "内存", color: "#9b7d54" }]} />
          <RequestStateView loading={false} error={null} empty={false} emptyState={null}>
            <LineChart labels={["00", "04", "08", "12", "16", "20", "24"]} unit="%"
              series={[
                { name: "CPU", color: "var(--teal)", data: [null, null, null, null, null, null, null] },
                { name: "内存", color: "#9b7d54", data: [null, null, null, null, null, null, null] },
              ]}
              emptyHint="按小时聚合接入后展示曲线" />
          </RequestStateView>
        </Panel>
        <Panel title={<><h2>待处理治理事项</h2><span className="status warn">{(alerts.data?.rows ?? []).length} 项</span></>}
          actions={<Link className="btn sm" to="/governance">查看全部</Link>}>
          <RequestStateView loading={alerts.isLoading} error={alerts.error}
            onRetry={() => void alerts.refetch()}
            empty={!alerts.data?.rows.length}
            emptyState={<EmptyState title="暂无治理告警" />}>
            <div>
              {(alerts.data?.rows ?? []).slice(0, 3).map((alert) => (
                <div className="item" key={alert.public_id}>
                  <div style={{ minWidth: 0 }}>
                    <strong>{alert.message}</strong>
                    <small>{alert.target_ref} · {alert.kind}</small>
                  </div>
                  <StatusBadge tone={alert.level === "HIGH" ? "bad" : alert.level === "MEDIUM" ? "warn" : "blue"}>
                    {alert.level}
                  </StatusBadge>
                </div>
              ))}
            </div>
          </RequestStateView>
        </Panel>
      </div>

      <div className="grid two section">
        <Panel title={<><h2>运行与异常趋势</h2><span className="subtle">近 7 天</span></>}>
          <BarChart labels={anomaliesByDay.labels} data={anomaliesByDay.counts} unit="项"
            emptyHint="近 7 天没有异常记录" />
        </Panel>
        <Panel title={<><h2>平台服务健康</h2><span className="subtle">来自平台运维快照</span></>}>
          {summary?.health?.length ? (
            <div>
              {summary.health.map((item, index) => (
                <div className="item" key={index}>
                  <div><strong>{item.name}</strong><small>{item.detail}</small></div>
                  <StatusBadge tone={item.status === "healthy" ? "good" : item.status === "degraded" ? "warn" : "neutral"}>
                    {item.status === "healthy" ? "健康" : item.status}
                  </StatusBadge>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="暂无健康快照" hint="健康数据来自 /platform/operations/overview。" />
          )}
        </Panel>
      </div>
    </>
  );
}
