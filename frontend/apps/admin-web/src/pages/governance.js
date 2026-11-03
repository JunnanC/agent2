import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useMutation, useQuery } from "@tanstack/react-query";
import { platformApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { ApiError } from "@edu/auth-client";
import { Button, ConfirmDialog, Panel, RequestStateView, StatusBadge, useToast, } from "@edu/ui";
import { apiErrorMessage } from "@/lib/format";
import { useState } from "react";
function governanceActionError(error, fallback) {
    if (error instanceof ApiError && error.payload?.code === "FEATURE_NOT_AVAILABLE") {
        return "该治理能力尚未在当前后端开放(接口返回 501)。";
    }
    if (error instanceof ApiError)
        return apiErrorMessage(error);
    return fallback;
}
export function Governance() {
    const toast = useToast();
    const [freezeTarget, setFreezeTarget] = useState(null);
    const [unfreezeTarget, setUnfreezeTarget] = useState(null);
    const [message, setMessage] = useState("");
    const courses = useQuery({ queryKey: keys.courses({ platform: true }), queryFn: () => platformApi.courses({ page_size: 50 }) });
    const alerts = useQuery({ queryKey: keys.governanceAlerts({}), queryFn: () => platformApi.governanceAlerts({}) });
    const freeze = useMutation({
        mutationFn: (target) => platformApi.freezeCourse(target.public_id, { reason: message }, target.row_version),
        onSuccess: (course) => {
            toast.notify(`已冻结课程「${course.title ?? ""}」`);
            setFreezeTarget(null);
            setMessage("");
            void courses.refetch();
        },
        onError: (error) => toast.notify(governanceActionError(error, "冻结操作失败，请检查权限"), "error"),
    });
    const unfreeze = useMutation({
        mutationFn: (target) => platformApi.freezeCourse(target.public_id, { reason: "解冻" }, target.row_version),
        onSuccess: () => {
            toast.notify("已解冻");
            setUnfreezeTarget(null);
            void courses.refetch();
        },
        onError: (error) => toast.notify(governanceActionError(error, "解冻失败"), "error"),
    });
    const rows = courses.data?.rows ?? [];
    const alertRows = alerts.data?.rows ?? [];
    return (_jsxs(_Fragment, { children: [_jsx(Panel, { title: _jsxs(_Fragment, { children: [_jsx("h2", { children: "\u5F85\u5904\u7406\u6CBB\u7406\u544A\u8B66" }), _jsxs("span", { className: "subtle", children: [alertRows.length, " \u9879"] })] }), children: _jsx(RequestStateView, { loading: alerts.isLoading, error: alerts.error, onRetry: () => void alerts.refetch(), empty: !alertRows.length, emptyState: _jsx("div", { className: "state-block", children: _jsx("strong", { children: "\u6682\u65E0\u6CBB\u7406\u544A\u8B66" }) }), children: _jsx("div", { children: alertRows.map((alert) => (_jsxs("div", { className: "item", children: [_jsxs("div", { children: [_jsx("strong", { children: alert.message }), _jsxs("small", { children: [alert.kind, " \u00B7 ", alert.target_ref, " \u00B7 ", alert.occurred_at] })] }), _jsxs("div", { style: { display: "flex", gap: 8, alignItems: "center" }, children: [_jsx(StatusBadge, { tone: alert.level === "HIGH" ? "bad" : alert.level === "MEDIUM" ? "warn" : "blue", children: alert.level }), alert.assignee ? _jsxs("span", { className: "subtle", children: ["\u8D1F\u8D23\u4EBA ", alert.assignee] }) : null] })] }, alert.public_id))) }) }) }), _jsx(Panel, { className: "section", title: _jsx("h2", { children: "\u8BFE\u7A0B\u51BB\u7ED3\u72B6\u6001" }), children: _jsx(RequestStateView, { loading: courses.isLoading, error: courses.error, onRetry: () => void courses.refetch(), empty: !rows.length, emptyState: _jsx("div", { className: "state-block", children: _jsx("strong", { children: "\u6682\u65E0\u8BFE\u7A0B" }) }), children: _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u8BFE\u7A0B" }), _jsx("th", { children: "\u9009\u8BFE\u65B9\u5F0F" }), _jsx("th", { children: "\u4EBA\u6570" }), _jsx("th", { children: "\u72B6\u6001" }), _jsx("th", {})] }) }), _jsx("tbody", { children: rows.map((course) => (_jsxs("tr", { children: [_jsxs("td", { children: [_jsx("strong", { children: course.title }), _jsx("small", { style: { display: "block" }, children: course.code })] }), _jsx("td", { children: course.enrollment_mode === "OPEN" ? "直接加入" : "需要审核" }), _jsxs("td", { children: [course.active_enrollment_count, course.capacity ? ` / ${course.capacity}` : ""] }), _jsx("td", { children: _jsx(StatusBadge, { tone: course.status === "ACTIVE" ? "good" : course.status === "FROZEN" ? "bad" : "neutral", children: course.status === "ACTIVE" ? "正常" : course.status === "FROZEN" ? "已冻结" : course.status }) }), _jsx("td", { className: "table-actions", children: course.status === "FROZEN"
                                                    ? _jsx(Button, { size: "sm", onClick: () => setUnfreezeTarget(course), children: "\u89E3\u51BB" })
                                                    : _jsx(Button, { size: "sm", variant: "danger", onClick: () => setFreezeTarget(course), children: "\u51BB\u7ED3" }) })] }, course.public_id))) })] }) }) }) }), _jsx(ConfirmDialog, { open: freezeTarget != null, onClose: () => setFreezeTarget(null), onConfirm: () => { if (freezeTarget)
                    freeze.mutate(freezeTarget); }, title: `冻结课程「${freezeTarget?.title ?? ""}」？`, eyebrow: "\u8BFE\u7A0B\u6CBB\u7406", tone: "danger", busy: freeze.isPending, confirmLabel: "\u786E\u8BA4\u51BB\u7ED3", description: (_jsxs(_Fragment, { children: [_jsxs("label", { className: "form-label", htmlFor: "freeze-reason", children: ["\u51BB\u7ED3\u539F\u56E0 ", _jsx("span", { children: "\u5FC5\u586B" })] }), _jsx("textarea", { id: "freeze-reason", className: "field", rows: 2, value: message, onChange: (event) => setMessage(event.target.value) })] })) }), _jsx(ConfirmDialog, { open: unfreezeTarget != null, onClose: () => setUnfreezeTarget(null), onConfirm: () => { if (unfreezeTarget)
                    unfreeze.mutate(unfreezeTarget); }, title: `解冻课程「${unfreezeTarget?.title ?? ""}」？`, eyebrow: "\u8BFE\u7A0B\u6CBB\u7406", busy: unfreeze.isPending, description: _jsx("p", { children: "\u89E3\u51BB\u540E\u8BFE\u7A0B\u6062\u590D\u6B63\u5E38\u6559\u5B66\u8FD0\u884C\u3002" }) })] }));
}
