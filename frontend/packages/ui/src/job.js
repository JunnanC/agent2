import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Icon } from "./icons";
const STATUS_LABEL = {
    submitted: "已提交",
    processing: "处理中",
    succeeded: "成功",
    failed: "失败",
    unknown: "未知状态",
};
const STATUS_TONE = {
    submitted: "blue",
    processing: "blue",
    succeeded: "good",
    failed: "bad",
    unknown: "neutral",
};
export function AsyncJobProgress({ status, stages, failureReason, onRetry }) {
    return (_jsxs("div", { className: "job-progress", role: "status", "aria-live": "polite", children: [_jsx("div", { className: "panel-title", style: { marginBottom: 4 }, children: _jsx("span", { className: `status ${STATUS_TONE[status]}`, children: STATUS_LABEL[status] }) }), stages.map((stage) => (_jsxs("div", { className: `job-stage ${stage.state}`, children: [_jsx("span", { "aria-hidden": "true", children: stage.state === "done" ? "✓" : stage.state === "failed"
                            ? _jsx(Icon, { name: "alert-triangle", size: 12 }) : stage.state === "running" ? "…" : "" }), _jsxs("span", { style: { minWidth: 0 }, children: [_jsx("strong", { style: { fontWeight: 600 }, children: stage.label }), stage.detail ? _jsx("small", { style: { display: "block" }, children: stage.detail }) : null] })] }, stage.key))), status === "failed" ? (_jsxs("div", { className: "job-stage failed", children: [_jsx("span", { "aria-hidden": "true", children: "!" }), _jsxs("span", { children: [failureReason ?? "任务失败，可重试。", onRetry ? _jsx("button", { type: "button", className: "btn sm", style: { marginLeft: 8 }, onClick: onRetry, children: "\u91CD\u8BD5" }) : null] })] })) : null] }));
}
