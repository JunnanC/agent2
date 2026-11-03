import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { platformApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Breadcrumbs, Button, ConfirmDialog, Metric, Panel, RequestStateView, StatusBadge, useToast, } from "@edu/ui";
import { useState } from "react";
import { apiErrorMessage } from "@/lib/format";
export function Resources() {
    const toast = useToast();
    const [imageTarget, setImageTarget] = useState(null);
    const images = useQuery({ queryKey: keys.images({}), queryFn: () => platformApi.images({ page_size: 50 }) });
    const profiles = useQuery({ queryKey: keys.resourceProfiles({}), queryFn: () => platformApi.resourceProfiles({}) });
    const adapters = useQuery({ queryKey: keys.runtimeAdapters({}), queryFn: () => platformApi.runtimeAdapters() });
    const quotas = useQuery({ queryKey: keys.quotas({}), queryFn: () => platformApi.quotas({}) });
    const instances = useQuery({ queryKey: keys.instances({ status: "ACTIVE" }), queryFn: () => platformApi.instances({ status: "ACTIVE", page_size: 1 }) });
    const sessions = useQuery({ queryKey: keys.platformWorkspaceSessions({}), queryFn: () => platformApi.workspaceSessions({ page_size: 1 }) });
    const decideImage = useMutation({
        mutationFn: (input) => platformApi.decideImage(input.target.public_id, { decision: input.decision }, input.target.row_version),
        onSuccess: (_data, input) => {
            toast.notify(input.decision === "approve" ? "镜像已批准" : "已拒绝镜像");
            setImageTarget(null);
            void images.refetch();
        },
        onError: (error) => toast.notify(apiErrorMessage(error), "error"),
    });
    const imageRows = images.data?.rows ?? [];
    const profileRows = (profiles.data?.rows ?? []);
    const adapterRows = (adapters.data?.rows ?? []);
    const quotaRows = (quotas.data?.rows ?? []);
    const sessionTotal = typeof sessions.data?.total === "number"
        ? sessions.data?.total
        : (sessions.data?.rows.length ?? 0);
    const instanceTotal = typeof instances.data?.total === "number"
        ? instances.data?.total
        : (instances.data?.rows.length ?? 0);
    const approvedImages = imageRows.filter((image) => image.approval_status === "APPROVED" && image.scan_status === "CLEAN").length;
    const pendingImages = imageRows.filter((image) => image.approval_status !== "APPROVED").length;
    const quotaAlerts = quotaRows.filter((quota) => (quota.used_value ?? 0) / Math.max(1, quota.limit_value) > 0.8).length;
    const METRIC_LABEL = {
        cpu: "CPU",
        memory: "内存",
        storage: "对象存储",
        disk: "磁盘",
    };
    return (_jsxs(_Fragment, { children: [_jsx(Breadcrumbs, { items: [{ label: "平台管理" }], current: "\u8D44\u6E90\u6CBB\u7406" }), _jsxs("div", { className: "page-actions align-end", children: [_jsx(Link, { className: "btn", to: "/governance", children: "\u67E5\u770B\u6CBB\u7406\u544A\u8B66" }), _jsx("button", { type: "button", className: "btn primary", onClick: () => { void images.refetch(); void adapters.refetch(); void quotas.refetch(); void instances.refetch(); }, "aria-label": "\u5237\u65B0\u5DE1\u68C0\u5217\u8868", children: "\u5237\u65B0\u5DE1\u68C0" })] }), _jsx(Panel, { className: "section", children: _jsx(RequestStateView, { loading: images.isLoading && adapters.isLoading, error: images.error ?? adapters.error, onRetry: () => { void images.refetch(); void adapters.refetch(); }, empty: false, emptyState: null, children: _jsxs("div", { className: "metric-strip", children: [_jsx(Metric, { label: "\u8FD0\u884C\u4E2D\u5B9E\u4F8B", value: instanceTotal ? String(instanceTotal) : "—", icon: "boxes", sub: "\u5F53\u524D\u6D3B\u8DC3\u5B9E\u4F8B" }), _jsx(Metric, { label: "\u5DF2\u6CBB\u7406\u955C\u50CF", value: String(approvedImages), icon: "boxes", sub: "\u5168\u90E8\u901A\u8FC7\u626B\u63CF" }), _jsx(Metric, { label: "\u914D\u989D\u9884\u8B66", value: String(quotaAlerts), icon: "gauge", sub: "\u4F7F\u7528\u7387\u8D85\u8FC7 80%" }), _jsx(Metric, { label: "\u5DE5\u4F5C\u533A\u4F1A\u8BDD", value: sessionTotal ? String(sessionTotal) : "—", icon: "monitor", sub: "\u4F1A\u8BDD\u8BB0\u5F55" })] }) }) }), _jsxs("div", { className: "grid two section", children: [_jsx(Panel, { title: _jsxs(_Fragment, { children: [_jsx("h2", { children: "\u8FD0\u884C\u65F6\u5065\u5EB7" }), _jsx("span", { className: `status ${adapterRows.length && adapterRows.every((adapter) => adapter.health_status === "HEALTHY") ? "good" : adapterRows.length ? "warn" : "neutral"}`, children: adapterRows.length && adapterRows.every((adapter) => adapter.health_status === "HEALTHY") ? "全部正常" : adapterRows.length ? "存在关注项" : "—" })] }), children: _jsx(RequestStateView, { loading: adapters.isLoading, error: adapters.error, onRetry: () => void adapters.refetch(), empty: !adapterRows.length, emptyState: _jsx("div", { className: "state-block", children: _jsx("strong", { children: "\u6682\u65E0\u8FD0\u884C\u65F6" }) }), children: _jsx("div", { children: adapterRows.map((adapter) => {
                                    const cpuCapacity = adapter.capacity_cpu_millicores ?? 0;
                                    const cpuAvailable = adapter.available_cpu_millicores ?? 0;
                                    const usage = cpuCapacity > 0 ? Math.round(((cpuCapacity - cpuAvailable) / cpuCapacity) * 100) : null;
                                    const healthy = adapter.health_status === "HEALTHY";
                                    return (_jsxs("div", { className: "item", children: [_jsxs("div", { children: [_jsxs("strong", { children: [adapter.name, " \u00B7 ", adapter.code] }), _jsxs("small", { children: [adapter.driver, " \u00B7 \u8282\u70B9 ", adapter.node_count ?? "—"] })] }), _jsx(StatusBadge, { tone: healthy && (usage ?? 0) <= 80 ? "good" : "warn", children: healthy ? `健康 ${100 - (usage ?? 0)}%` : `容量 ${usage ?? "—"}%` })] }, adapter.public_id));
                                }) }) }) }), _jsx(Panel, { title: _jsxs(_Fragment, { children: [_jsx("h2", { children: "\u914D\u989D\u4E0E\u5B58\u50A8" }), _jsx("span", { className: "subtle", children: "\u5F53\u524D\u5B66\u671F" })] }), children: _jsx(RequestStateView, { loading: quotas.isLoading, error: quotas.error, onRetry: () => void quotas.refetch(), empty: !quotaRows.length, emptyState: _jsxs("div", { className: "state-block", children: [_jsx("strong", { children: "\u6682\u65E0\u914D\u989D\u914D\u7F6E" }), _jsx("p", { children: "\u5E73\u53F0\u914D\u7F6E CPU / \u5185\u5B58 / \u5BF9\u8C61\u5B58\u50A8\u914D\u989D\u540E\u5C55\u793A\u4F7F\u7528\u7387\u3002" })] }), children: _jsx("div", { children: quotaRows.map((quota) => {
                                    const percent = quota.limit_value
                                        ? Math.round(((quota.used_value ?? 0) / quota.limit_value) * 100)
                                        : 0;
                                    return (_jsxs("div", { className: "quota-line", children: [_jsx("span", { children: METRIC_LABEL[quota.metric] ?? quota.metric }), _jsx("div", { className: "progress", children: _jsx("span", { style: { width: `${percent}%` } }) }), _jsxs("strong", { children: [percent, "%"] })] }, quota.public_id));
                                }) }) }) })] }), _jsx(Panel, { className: "section", title: _jsxs(_Fragment, { children: [_jsx("h2", { children: "\u955C\u50CF\u4E0E\u8D44\u6E90\u5E93" }), pendingImages > 0
                            ? _jsx("span", { className: "status warn", children: `${pendingImages} 个待审批` })
                            : _jsx("span", { className: "status neutral", children: "\u53EA\u8BFB\u6C47\u603B" })] }), children: _jsx(RequestStateView, { loading: images.isLoading || adapters.isLoading || profiles.isLoading, error: images.error ?? adapters.error ?? profiles.error, onRetry: () => { void images.refetch(); void adapters.refetch(); void profiles.refetch(); }, empty: !imageRows.length && !adapterRows.length && !profileRows.length, emptyState: _jsxs("div", { className: "state-block", children: [_jsx("strong", { children: "\u6682\u65E0\u6CBB\u7406\u8D44\u6E90" }), _jsx("p", { children: "\u955C\u50CF\u3001\u8FD0\u884C\u65F6\u4E0E\u8D44\u6E90\u89C4\u683C\u4F1A\u5728\u8FD9\u91CC\u7EDF\u4E00\u6C47\u603B\u3002" })] }), children: _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u8D44\u6E90" }), _jsx("th", { children: "\u7248\u672C" }), _jsx("th", { children: "\u72B6\u6001" }), _jsx("th", { children: "\u6700\u8FD1\u68C0\u67E5" }), _jsx("th", { children: "\u4F7F\u7528" })] }) }), _jsxs("tbody", { children: [imageRows.map((image) => (_jsxs("tr", { children: [_jsxs("td", { children: [_jsx("strong", { children: image.display_tag }), _jsx("small", { style: { display: "block" }, children: image.registry })] }), _jsx("td", { children: _jsxs("small", { children: [(image.digest ?? "").slice(0, 18), "\u2026"] }) }), _jsx("td", { children: image.approval_status === "APPROVED"
                                                        ? _jsx(StatusBadge, { tone: "good", children: "\u5DF2\u6279\u51C6" })
                                                        : _jsx(Button, { size: "sm", variant: "primary", onClick: () => setImageTarget(image), children: "\u5BA1\u6279" }) }), _jsx("td", { children: image.scanned_at ?? "—" }), _jsx("td", { className: "subtle", children: "\u2014" })] }, image.public_id))), adapterRows.map((adapter) => (_jsxs("tr", { children: [_jsxs("td", { children: [_jsx("strong", { children: adapter.name }), _jsx("small", { style: { display: "block" }, children: adapter.driver })] }), _jsx("td", { children: _jsx("small", { children: adapter.code }) }), _jsx("td", { children: _jsx(StatusBadge, { tone: adapter.health_status === "HEALTHY" ? "good" : "warn", children: adapter.health_status === "HEALTHY" ? "在线" : adapter.health_status }) }), _jsx("td", { children: adapter.last_health_at ?? "—" }), _jsx("td", { children: sessionTotal ? `${sessionTotal} 会话` : "—" })] }, adapter.public_id))), profileRows.map((profile) => (_jsxs("tr", { children: [_jsxs("td", { children: [_jsx("strong", { children: profile.name }), _jsxs("small", { style: { display: "block" }, children: ["CPU ", profile.cpu_millicores, " m \u00B7 ", profile.memory_mb, " MB"] })] }), _jsx("td", { children: _jsx("small", { children: profile.code }) }), _jsx("td", { children: _jsx(StatusBadge, { tone: profile.status === "ACTIVE" ? "good" : "neutral", children: profile.status }) }), _jsx("td", { className: "subtle", children: "\u2014" }), _jsx("td", { className: "subtle", children: "\u2014" })] }, profile.public_id)))] })] }) }) }) }), _jsx(ConfirmDialog, { open: imageTarget != null, onClose: () => setImageTarget(null), onConfirm: () => { if (imageTarget)
                    decideImage.mutate({ target: imageTarget, decision: "approve" }); }, title: "\u6279\u51C6\u955C\u50CF\uFF1F", eyebrow: "\u955C\u50CF\u6CBB\u7406", busy: decideImage.isPending, confirmLabel: "\u6279\u51C6", description: _jsx("p", { children: "\u6279\u51C6\u540E\u6559\u5E08\u53EF\u5C06\u5176\u7EB3\u5165\u6A21\u677F\u7248\u672C\uFF1B\u62D2\u7EDD\u64CD\u4F5C\u53EF\u5728\u5217\u8868\u9875\u5BF9\u540C\u4E00\u955C\u50CF\u91CD\u65B0\u6267\u884C\u3002" }) })] }));
}
