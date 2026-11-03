import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import * as ui from "../../../../packages/ui/src/index";
export * from "../../../../packages/ui/src/index";
export function PageHeader(props) {
    const subtitle = [props.eyebrow, props.description].filter(Boolean).join(" / ") || props.subtitle;
    return _jsx(ui.PageHeader, { title: props.title, subtitle: subtitle, actions: props.actions });
}
export function StatusBadge({ status, tone, children }) {
    const badgeTone = tone ?? (/ACTIVE|APPROVED|HEALTHY|PASSED|RESOLVED/i.test(status ?? "")
        ? "good"
        : /FAILED|REJECTED|BLOCKED|CRITICAL/i.test(status ?? "") ? "bad" : "neutral");
    return _jsx(ui.StatusBadge, { tone: badgeTone, children: children ?? status });
}
export function RequestStateView(props) {
    if (!props.state)
        return _jsx(ui.RequestStateView, { loading: props.loading ?? false, error: props.error ?? null, empty: props.empty ?? false, emptyState: props.emptyState, errorTitle: props.errorTitle, errorMessage: props.errorMessage, onRetry: props.onRetry, forbidden: props.forbidden, children: props.children });
    if (props.state === "loading")
        return _jsx(ui.LoadingState, {});
    if (props.state === "empty")
        return _jsx(ui.EmptyState, { title: "\u6682\u65E0\u6570\u636E" });
    const error = props.message ?? (props.traceId ? `Trace ID ${props.traceId}` : "请求暂时不可用。");
    return _jsx(ui.ErrorState, { error: error, onRetry: props.onRetry, title: props.state === "forbidden" ? "没有查看权限" : "请求失败" });
}
export function TextField({ label, ...props }) {
    return _jsxs("label", { className: "field", children: [_jsx("span", { children: label }), _jsx("input", { ...props })] });
}
