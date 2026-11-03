import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { platformApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { ApiError } from "@edu/auth-client";
import { Breadcrumbs, Button, Drawer, EmptyState, Metric, Modal, Panel, RequestStateView, StatusBadge, useToast, } from "@edu/ui";
import { apiErrorMessage } from "@/lib/format";
import { exportCsv } from "@/lib/csv";
const KIND_LABEL = {
    task: "实验任务异常",
    "report-scan": "报告扫描",
    precheck: "模板预检",
    instance: "实例异常",
};
const LEVEL_LABEL = {
    HIGH: "高",
    MEDIUM: "中",
    LOW: "低",
    INFO: "低",
};
export function Incidents() {
    const toast = useToast();
    const [range, setRange] = useState("7");
    const taskAnomalies = useQuery({ queryKey: keys.anomalies({ page_size: 100 }), queryFn: () => platformApi.anomalies({ page_size: 100 }) });
    const scanAnomalies = useQuery({ queryKey: keys.scanAnomalies({ page_size: 50 }), queryFn: () => platformApi.scanAnomalies({ page_size: 50 }) });
    const rows = useMemo(() => [
        ...(taskAnomalies.data?.rows ?? []),
        ...(scanAnomalies.data?.rows ?? []),
    ].sort((a, b) => String(b.occurred_at ?? "").localeCompare(String(a.occurred_at ?? ""))), [taskAnomalies.data, scanAnomalies.data]);
    const filtered = useMemo(() => {
        if (range === "all")
            return rows;
        const days = Number(range);
        const cutoff = Date.now() - days * 86_400_000;
        return rows.filter((row) => !row.occurred_at || new Date(row.occurred_at).getTime() >= cutoff);
    }, [rows, range]);
    const pending = filtered.filter((row) => !["RESOLVED", "CLOSED"].includes(row.status));
    const highPriority = filtered.filter((row) => row.level === "HIGH");
    const resolvedToday = filtered.filter((row) => {
        if (!["RESOLVED", "CLOSED"].includes(row.status) || !row.occurred_at)
            return false;
        return new Date(row.occurred_at).getTime() >= Date.now() - 86_400_000;
    }).length;
    const [search, setSearch] = useState("");
    const [detailRow, setDetailRow] = useState(null);
    const [retryTarget, setRetryTarget] = useState(null);
    const [retryReason, setRetryReason] = useState("");
    const visible = useMemo(() => {
        const query = search.trim().toLowerCase();
        return filtered.filter((row) => !query
            || `${row.target_ref} ${row.message} ${row.trace_id ?? ""}`.toLowerCase().includes(query));
    }, [filtered, search]);
    const compensations = useQuery({
        queryKey: [...keys.anomalies({ scope: "compensations" }), "failed"],
        queryFn: () => platformApi.compensations({ status: "" }),
        refetchInterval: 8000,
    });
    const retryable = (compensations.data?.rows ?? []).filter((row) => !["DONE", "RETRYING"].includes(row.status));
    const retryMutation = useMutation({
        mutationFn: (target) => platformApi.retryCompensation(target.public_id, { reason: retryReason.trim() }, target.row_version),
        onSuccess: () => {
            toast.notify("补偿重试已进队列");
            setRetryTarget(null);
            setRetryReason("");
            void compensations.refetch();
        },
        onError: (error) => toast.notify(error instanceof ApiError ? apiErrorMessage(error) : apiErrorMessage(error), "error"),
    });
    const exportList = () => {
        exportCsv(`处理清单-${new Date().toISOString().slice(0, 10)}.csv`, [
            ["类型", "对象", "级别", "发生时间", "负责人", "状态", "说明", "Trace ID"],
            ...visible.map((row) => [
                KIND_LABEL[row.kind] ?? row.kind,
                row.target_ref,
                LEVEL_LABEL[row.level] ?? row.level,
                row.occurred_at ?? "",
                row.assignee ?? "未分配",
                row.status,
                row.message,
                row.trace_id ?? "",
            ]),
        ]);
        toast.notify("处理清单已导出");
    };
    return (_jsxs(_Fragment, { children: [_jsx(Breadcrumbs, { items: [{ label: "平台管理" }], current: "\u5F02\u5E38\u4E2D\u5FC3" }), _jsxs("div", { className: "page-actions align-end", children: [_jsxs("select", { className: "field", style: { width: 110 }, "aria-label": "\u65F6\u95F4\u8303\u56F4", value: range, onChange: (event) => setRange(event.target.value), children: [_jsx("option", { value: "7", children: "\u8FD1 7 \u5929" }), _jsx("option", { value: "30", children: "\u8FD1 30 \u5929" }), _jsx("option", { value: "all", children: "\u5168\u90E8" })] }), _jsx(Button, { variant: "primary", onClick: exportList, children: "\u5BFC\u51FA\u5904\u7406\u6E05\u5355" })] }), _jsx(Panel, { className: "section", children: _jsx(RequestStateView, { loading: taskAnomalies.isLoading && scanAnomalies.isLoading, error: taskAnomalies.error ?? scanAnomalies.error, onRetry: () => { void taskAnomalies.refetch(); void scanAnomalies.refetch(); }, empty: false, emptyState: null, children: _jsxs("div", { className: "metric-strip", children: [_jsx(Metric, { label: "\u5F85\u5904\u7406", value: String(pending.length), icon: "alert-triangle", sub: "\u8DE8\u4EFB\u52A1\u4E0E\u8D44\u6E90" }), _jsx(Metric, { label: "\u9AD8\u4F18\u5148\u7EA7", value: String(highPriority.length), icon: "alert-triangle", sub: "\u9700\u8981\u5FEB\u901F\u54CD\u5E94" }), _jsx(Metric, { label: "\u5F85\u8865\u507F", value: String(pending.filter((row) => row.kind === "task").length), icon: "refresh", sub: "\u5931\u8D25\u4F5C\u4E1A" }), _jsx(Metric, { label: "\u5DF2\u95ED\u73AF", value: String(resolvedToday), icon: "circle-check", sub: "\u8FD1 24 \u5C0F\u65F6" })] }) }) }), _jsx(Panel, { title: _jsxs(_Fragment, { children: [_jsx("h2", { children: "\u5F02\u5E38\u961F\u5217" }), _jsxs("span", { className: "subtle", children: [visible.length, " \u6761\u8BB0\u5F55"] })] }), actions: (_jsx("input", { className: "field", style: { width: 240 }, type: "search", placeholder: "\u641C\u7D22\u4EFB\u52A1\u3001Trace \u6216\u8D44\u6E90", "aria-label": "\u641C\u7D22\u5F02\u5E38", value: search, onChange: (event) => setSearch(event.target.value) })), children: _jsx(RequestStateView, { loading: taskAnomalies.isLoading || scanAnomalies.isLoading, error: taskAnomalies.error ?? scanAnomalies.error, onRetry: () => { void taskAnomalies.refetch(); void scanAnomalies.refetch(); }, empty: !visible.length, emptyState: _jsx(EmptyState, { title: "\u6682\u65E0\u5F02\u5E38\u8BB0\u5F55", hint: "\u5F53\u524D\u7B5B\u9009\u8303\u56F4\u5185\u5E73\u53F0\u8FD0\u884C\u5E73\u7A33\u3002" }), children: _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u7C7B\u578B" }), _jsx("th", { children: "\u5BF9\u8C61" }), _jsx("th", { children: "\u7EA7\u522B" }), _jsx("th", { children: "\u53D1\u751F\u65F6\u95F4" }), _jsx("th", { children: "\u8D1F\u8D23\u4EBA" }), _jsx("th", { children: "\u5904\u7406" })] }) }), _jsx("tbody", { children: visible.map((row) => (_jsxs("tr", { children: [_jsx("td", { children: _jsx("strong", { children: KIND_LABEL[row.kind] ?? row.kind }) }), _jsx("td", { "data-wrap": true, children: row.target_ref }), _jsx("td", { children: _jsx(StatusBadge, { tone: row.level === "HIGH" ? "bad" : row.level === "MEDIUM" ? "warn" : "neutral", children: LEVEL_LABEL[row.level] ?? row.level }) }), _jsx("td", { children: row.occurred_at ?? "—" }), _jsx("td", { children: row.assignee ?? "待分派" }), _jsx("td", { className: "table-actions", children: _jsx(Button, { size: "sm", onClick: () => setDetailRow(row), children: "\u67E5\u770B\u8BE6\u60C5" }) })] }, row.public_id))) })] }) }) }) }), _jsx(Drawer, { open: detailRow != null, onClose: () => setDetailRow(null), title: detailRow ? `异常详情 · ${KIND_LABEL[detailRow.kind] ?? detailRow.kind}` : "异常详情", children: detailRow ? (_jsxs("div", { style: { display: "grid", gap: 10 }, children: [_jsxs("div", { className: "status-line", children: [_jsx("strong", { children: "\u5BF9\u8C61\uFF1A" }), detailRow.target_ref] }), _jsxs("div", { className: "status-line", children: [_jsx("strong", { children: "\u72B6\u6001\uFF1A" }), detailRow.status] }), _jsxs("div", { className: "status-line", children: [_jsx("strong", { children: "\u8BF4\u660E\uFF1A" }), detailRow.message] }), detailRow.code ? _jsxs("div", { className: "status-line", children: [_jsx("strong", { children: "\u9519\u8BEF\u7801\uFF1A" }), detailRow.code] }) : null, detailRow.trace_id ? _jsxs("div", { className: "status-line", children: [_jsx("strong", { children: "Trace\uFF1A" }), detailRow.trace_id] }) : null, _jsxs("div", { className: "status-line", children: [_jsx("strong", { children: "\u53D1\u751F\u65F6\u95F4\uFF1A" }), detailRow.occurred_at ?? "—"] }), detailRow.payload && Object.keys(detailRow.payload).length ? (_jsxs(_Fragment, { children: [_jsx("strong", { children: "Payload" }), _jsx("div", { className: "report-submission-copy", style: { whiteSpace: "pre-wrap" }, children: JSON.stringify(detailRow.payload, null, 2) })] })) : null] })) : null }), _jsxs("div", { className: "grid two section", children: [_jsx(Panel, { title: _jsxs(_Fragment, { children: [_jsx("h2", { children: "\u8865\u507F\u4F5C\u4E1A" }), _jsxs("span", { className: `status ${retryable.length ? "warn" : "neutral"}`, children: [retryable.length, " \u4E2A\u5F85\u91CD\u8BD5"] })] }), children: compensations.isLoading && !compensations.data ? (_jsx("p", { className: "subtle", children: "\u8F7D\u5165\u8865\u507F\u961F\u5217\u2026" })) : retryable.length ? (retryable.slice(0, 8).map((row) => (_jsxs("div", { className: "status-line", style: { display: "flex", gap: 10, alignItems: "center" }, children: [_jsxs("span", { style: { flex: 1 }, children: [_jsx("strong", { children: row.task_type }), _jsxs("small", { style: { display: "block" }, children: [row.subject_type, " #", row.subject_ref, " \u00B7 \u5C1D\u8BD5 ", row.attempt_count, "/", row.max_attempts, row.error_code ? ` · ${row.error_code}` : ""] })] }), _jsx(Button, { size: "sm", onClick: () => { setRetryTarget(row); setRetryReason(""); }, children: "\u91CD\u8BD5" })] }, row.public_id)))) : (_jsx("p", { className: "subtle", style: { margin: 0 }, children: "\u8865\u507F\u961F\u5217\u4E3A\u7A7A;\u5F52\u6863\u56DE\u6536\u3001\u5B9E\u4F8B\u9500\u6BC1\u5931\u8D25\u4F1A\u8FDB\u5165\u8FD9\u91CC,\u53EF\u624B\u5DE5\u91CD\u8BD5\u3002" })) }), _jsx(Panel, { title: _jsxs(_Fragment, { children: [_jsx("h2", { children: "\u5B89\u5168\u4E0E\u5BA1\u8BA1" }), _jsx("span", { className: `status ${highPriority.length ? "warn" : "good"}`, children: highPriority.length ? "存在高风险" : "无高风险" })] }), children: _jsx("div", { className: "section", children: _jsx("p", { className: "subtle", style: { margin: 0 }, children: highPriority.length
                                    ? `当前范围 ${highPriority.length} 条 HIGH 级异常待响应,请在上表处理。`
                                    : "当前没有需要升级的安全告警；安全策略与网络白名单的明细在审计日志中留痕。" }) }) })] }), _jsx(Modal, { open: retryTarget != null, onClose: () => setRetryTarget(null), eyebrow: "\u8865\u507F\u4F5C\u4E1A", title: "\u53D1\u8D77\u8865\u507F\u91CD\u8BD5", actions: (_jsxs(_Fragment, { children: [_jsx(Button, { onClick: () => setRetryTarget(null), children: "\u53D6\u6D88" }), _jsx(Button, { variant: "primary", disabled: !retryReason.trim() || retryMutation.isPending, onClick: () => retryTarget && retryMutation.mutate(retryTarget), children: retryMutation.isPending ? "提交中…" : "确认重试" })] })), children: retryTarget ? (_jsxs("div", { style: { display: "grid", gap: 10 }, children: [_jsxs("p", { className: "subtle", style: { margin: 0 }, children: ["\u76EE\u6807:", retryTarget.task_type, " \u00B7 ", retryTarget.subject_type, " #", retryTarget.subject_ref, "(\u5DF2\u5C1D\u8BD5 ", retryTarget.attempt_count, "/", retryTarget.max_attempts, ")"] }), _jsxs("label", { className: "form-label", htmlFor: "retry-reason", children: ["\u91CD\u8BD5\u539F\u56E0 ", _jsx("span", { children: "\u5FC5\u586B" })] }), _jsx("textarea", { id: "retry-reason", className: "field", rows: 3, value: retryReason, onChange: (event) => setRetryReason(event.target.value), placeholder: "\u8BB0\u5F55\u672C\u6B21\u624B\u5DE5\u91CD\u8BD5\u7684\u539F\u56E0,\u5199\u5165\u5BA1\u8BA1\u65E5\u5FD7" })] })) : null })] }));
}
