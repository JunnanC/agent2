import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { platformApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Breadcrumbs, EmptyState, Panel, RequestStateView, StatusBadge, useToast, } from "@edu/ui";
import { exportCsv } from "@/lib/csv";
import { Button } from "@edu/ui";
const RESULT_LABEL = {
    SUCCESS: { label: "成功", tone: "good" },
    NEED_REVIEW: { label: "需复核", tone: "warn" },
    FAILED: { label: "失败", tone: "neutral" },
};
export function Audit() {
    const toast = useToast();
    const [search, setSearch] = useState("");
    const [range, setRange] = useState("7");
    const logs = useQuery({ queryKey: keys.operationLogs({}), queryFn: () => platformApi.operationLogs({ page_size: 50 }) });
    const rows = useMemo(() => {
        const query = search.trim().toLowerCase();
        const cutoff = range === "all" ? 0 : Date.now() - Number(range) * 86_400_000;
        return (logs.data?.rows ?? []).filter((row) => {
            const withinRange = !cutoff || !row.occurred_at || new Date(row.occurred_at).getTime() >= cutoff;
            const matches = !query
                || `${row.action} ${row.target} ${row.actor_name ?? ""} ${row.trace_id ?? ""}`.toLowerCase().includes(query);
            return withinRange && matches;
        });
    }, [logs.data, search, range]);
    const exportLogs = () => {
        exportCsv(`操作日志-${new Date().toISOString().slice(0, 10)}.csv`, [
            ["时间", "操作者", "动作", "对象", "结果", "Trace ID"],
            ...rows.map((row) => [
                row.occurred_at ?? "",
                row.actor_name ?? row.actor ?? "系统",
                row.action,
                row.target,
                RESULT_LABEL[row.result]?.label ?? row.result,
                row.trace_id ?? "",
            ]),
        ]);
        toast.notify("日志已导出");
    };
    return (_jsxs(_Fragment, { children: [_jsx(Breadcrumbs, { items: [{ label: "平台管理" }], current: "\u5F02\u5E38\u4E0E\u5BA1\u8BA1" }), _jsxs("div", { className: "page-actions align-end", children: [_jsxs("select", { className: "field", style: { width: 110 }, "aria-label": "\u65F6\u95F4\u8303\u56F4", value: range, onChange: (event) => setRange(event.target.value), children: [_jsx("option", { value: "3", children: "\u8FD1 3 \u5929" }), _jsx("option", { value: "7", children: "\u8FD1 7 \u5929" }), _jsx("option", { value: "30", children: "\u8FD1 30 \u5929" }), _jsx("option", { value: "all", children: "\u5168\u90E8" })] }), _jsx(Button, { onClick: exportLogs, children: "\u5BFC\u51FA\u65E5\u5FD7" })] }), _jsx(Panel, { title: _jsxs(_Fragment, { children: [_jsx("h2", { children: "\u64CD\u4F5C\u65E5\u5FD7" }), _jsxs("span", { className: "subtle", children: [rows.length, " \u6761\u8BB0\u5F55"] })] }), actions: (_jsx("input", { className: "field", style: { width: 240 }, type: "search", placeholder: "\u641C\u7D22\u64CD\u4F5C\u3001\u7528\u6237\u6216\u8D44\u6E90", "aria-label": "\u641C\u7D22\u65E5\u5FD7", value: search, onChange: (event) => setSearch(event.target.value) })), children: _jsx(RequestStateView, { loading: logs.isLoading, error: logs.error, onRetry: () => void logs.refetch(), empty: !rows.length, emptyState: _jsx(EmptyState, { title: "\u6682\u65E0\u64CD\u4F5C\u65E5\u5FD7", hint: "\u5F53\u524D\u65F6\u95F4\u8303\u56F4\u5185\u6CA1\u6709\u5E73\u53F0\u5173\u952E\u64CD\u4F5C\u3002" }), children: _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u65F6\u95F4" }), _jsx("th", { children: "\u64CD\u4F5C\u8005" }), _jsx("th", { children: "\u52A8\u4F5C" }), _jsx("th", { children: "\u5BF9\u8C61" }), _jsx("th", { children: "\u7ED3\u679C" })] }) }), _jsx("tbody", { children: rows.map((row) => {
                                        const result = RESULT_LABEL[row.result] ?? { label: row.result, tone: "neutral" };
                                        return (_jsxs("tr", { children: [_jsx("td", { children: row.occurred_at }), _jsx("td", { children: _jsx("strong", { children: row.actor_name ?? row.actor ?? "系统" }) }), _jsx("td", { children: row.action }), _jsx("td", { "data-wrap": true, children: row.target }), _jsxs("td", { children: [_jsx(StatusBadge, { tone: result.tone, children: result.label }), row.trace_id ? _jsxs("small", { style: { display: "block", color: "var(--muted)" }, children: ["Trace ", row.trace_id] }) : null] })] }, row.id));
                                    }) })] }) }) }) })] }));
}
