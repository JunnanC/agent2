import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { platformApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { BarChart, Breadcrumbs, ChartLegend, EmptyState, LineChart, Metric, Panel, RequestStateView, StatusBadge, } from "@edu/ui";
import { lastDayLabels } from "@/lib/csv";
export function Home() {
    const overview = useQuery({ queryKey: keys.operationsOverview(), queryFn: () => platformApi.operationsOverview() });
    const alerts = useQuery({ queryKey: keys.governanceAlerts({}), queryFn: () => platformApi.governanceAlerts({}) });
    const adapters = useQuery({ queryKey: keys.runtimeAdapters({}), queryFn: () => platformApi.runtimeAdapters() });
    const anomalies = useQuery({ queryKey: keys.anomalies({ page_size: 100 }), queryFn: () => platformApi.anomalies({ page_size: 100 }) });
    const scanAnomalies = useQuery({ queryKey: keys.scanAnomalies({ page_size: 50 }), queryFn: () => platformApi.scanAnomalies({ page_size: 50 }) });
    const summary = overview.data;
    const counts = summary?.counts ?? {};
    const adapterRows = adapters.data?.rows ?? [];
    const cpuAvailable = adapterRows.reduce((sum, row) => sum + (row.available_cpu_millicores ?? 0), 0);
    const cpuCapacity = adapterRows.reduce((sum, row) => sum + (row.capacity_cpu_millicores ?? 0), 0);
    const cpuUsage = cpuCapacity > 0 ? Math.round(((cpuCapacity - cpuAvailable) / cpuCapacity) * 100) : null;
    const allAnomalies = useMemo(() => [
        ...(anomalies.data?.rows ?? []),
        ...(scanAnomalies.data?.rows ?? []),
    ], [anomalies.data, scanAnomalies.data]);
    const anomaliesByDay = useMemo(() => {
        const labels = lastDayLabels(7);
        const counts = labels.map(() => 0);
        for (const anomaly of allAnomalies) {
            if (!anomaly.occurred_at)
                continue;
            const occurred = new Date(anomaly.occurred_at);
            const todayMidnight = new Date();
            todayMidnight.setHours(0, 0, 0, 0);
            occurred.setHours(0, 0, 0, 0);
            const diffDays = Math.floor((todayMidnight.getTime() - occurred.getTime()) / 86_400_000);
            if (diffDays >= 0 && diffDays < 7)
                counts[6 - diffDays] = (counts[6 - diffDays] ?? 0) + 1;
        }
        return { labels, counts };
    }, [allAnomalies]);
    return (_jsxs(_Fragment, { children: [_jsx(Breadcrumbs, { items: [], current: "\u5E73\u53F0\u6982\u89C8" }), _jsx("div", { className: "page-actions align-end", children: _jsx(Link, { className: "btn", to: "/audit", children: "\u67E5\u770B\u64CD\u4F5C\u65E5\u5FD7" }) }), _jsx(Panel, { className: "section", children: _jsx(RequestStateView, { loading: overview.isLoading && adapters.isLoading, error: overview.error ?? adapters.error, onRetry: () => { void overview.refetch(); void adapters.refetch(); }, empty: false, emptyState: null, children: _jsxs("div", { className: "metric-strip", children: [_jsx(Metric, { label: "\u8FD0\u884C\u5DE5\u4F5C\u533A", value: String(counts["active_workspaces"] ?? "—"), icon: "boxes", sub: `总数 ${counts["instances"] ?? "—"} 实例` }), _jsx(Metric, { label: "CPU \u4F7F\u7528\u7387", value: cpuUsage != null ? `${cpuUsage}%` : "—", icon: "cpu", sub: `集群总量 ${Math.round(cpuCapacity / 1000)} vCPU` }), _jsx(Metric, { label: "\u6CBB\u7406\u544A\u8B66", value: String(alerts.data?.rows.length ?? 0), icon: "shield", sub: `${(alerts.data?.rows ?? []).filter((alert) => alert.level === "HIGH").length} 项高优先级` }), _jsx(Metric, { label: "\u5F02\u5E38\u4E8B\u9879", value: String(allAnomalies.length), icon: "alert-triangle", sub: "\u4EFB\u52A1\u4E0E\u8D44\u6E90" })] }) }) }), _jsxs("div", { className: "grid two section", children: [_jsxs(Panel, { title: _jsxs(_Fragment, { children: [_jsx("h2", { children: "\u8D44\u6E90\u4F7F\u7528\u8D8B\u52BF" }), _jsx("span", { className: "subtle", children: "\u6700\u8FD1 24 \u5C0F\u65F6" })] }), children: [_jsx(ChartLegend, { items: [{ name: "CPU", color: "var(--teal)" }, { name: "内存", color: "#9b7d54" }] }), _jsx(RequestStateView, { loading: false, error: null, empty: false, emptyState: null, children: _jsx(LineChart, { labels: ["00", "04", "08", "12", "16", "20", "24"], unit: "%", series: [
                                        { name: "CPU", color: "var(--teal)", data: [null, null, null, null, null, null, null] },
                                        { name: "内存", color: "#9b7d54", data: [null, null, null, null, null, null, null] },
                                    ], emptyHint: "\u6309\u5C0F\u65F6\u805A\u5408\u63A5\u5165\u540E\u5C55\u793A\u66F2\u7EBF" }) })] }), _jsx(Panel, { title: _jsxs(_Fragment, { children: [_jsx("h2", { children: "\u5F85\u5904\u7406\u6CBB\u7406\u4E8B\u9879" }), _jsxs("span", { className: "status warn", children: [(alerts.data?.rows ?? []).length, " \u9879"] })] }), actions: _jsx(Link, { className: "btn sm", to: "/governance", children: "\u67E5\u770B\u5168\u90E8" }), children: _jsx(RequestStateView, { loading: alerts.isLoading, error: alerts.error, onRetry: () => void alerts.refetch(), empty: !alerts.data?.rows.length, emptyState: _jsx(EmptyState, { title: "\u6682\u65E0\u6CBB\u7406\u544A\u8B66" }), children: _jsx("div", { children: (alerts.data?.rows ?? []).slice(0, 3).map((alert) => (_jsxs("div", { className: "item", children: [_jsxs("div", { style: { minWidth: 0 }, children: [_jsx("strong", { children: alert.message }), _jsxs("small", { children: [alert.target_ref, " \u00B7 ", alert.kind] })] }), _jsx(StatusBadge, { tone: alert.level === "HIGH" ? "bad" : alert.level === "MEDIUM" ? "warn" : "blue", children: alert.level })] }, alert.public_id))) }) }) })] }), _jsxs("div", { className: "grid two section", children: [_jsx(Panel, { title: _jsxs(_Fragment, { children: [_jsx("h2", { children: "\u8FD0\u884C\u4E0E\u5F02\u5E38\u8D8B\u52BF" }), _jsx("span", { className: "subtle", children: "\u8FD1 7 \u5929" })] }), children: _jsx(BarChart, { labels: anomaliesByDay.labels, data: anomaliesByDay.counts, unit: "\u9879", emptyHint: "\u8FD1 7 \u5929\u6CA1\u6709\u5F02\u5E38\u8BB0\u5F55" }) }), _jsx(Panel, { title: _jsxs(_Fragment, { children: [_jsx("h2", { children: "\u5E73\u53F0\u670D\u52A1\u5065\u5EB7" }), _jsx("span", { className: "subtle", children: "\u6765\u81EA\u5E73\u53F0\u8FD0\u7EF4\u5FEB\u7167" })] }), children: summary?.health?.length ? (_jsx("div", { children: summary.health.map((item, index) => (_jsxs("div", { className: "item", children: [_jsxs("div", { children: [_jsx("strong", { children: item.name }), _jsx("small", { children: item.detail })] }), _jsx(StatusBadge, { tone: item.status === "healthy" ? "good" : item.status === "degraded" ? "warn" : "neutral", children: item.status === "healthy" ? "健康" : item.status })] }, index))) })) : (_jsx(EmptyState, { title: "\u6682\u65E0\u5065\u5EB7\u5FEB\u7167", hint: "\u5065\u5EB7\u6570\u636E\u6765\u81EA /platform/operations/overview\u3002" })) })] })] }));
}
