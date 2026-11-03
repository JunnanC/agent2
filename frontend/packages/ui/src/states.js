import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { Icon } from "./icons";
import { Button } from "./controls";
export function LoadingState({ label = "正在加载" }) {
    return (_jsxs("div", { className: "skeleton", role: "status", "aria-live": "polite", "aria-label": label, children: [_jsx("span", { className: "skeleton-line title" }), _jsx("span", { className: "skeleton-line w60" }), _jsx("span", { className: "skeleton-line w40" }), _jsx("span", { className: "skeleton-line w60" })] }));
}
export function EmptyState({ title, hint, action, icon = "info" }) {
    return (_jsxs("div", { className: "state-block", children: [_jsx("span", { className: "state-block-icon", children: _jsx(Icon, { name: icon, size: 20 }) }), _jsx("strong", { children: title }), hint ? _jsx("p", { children: hint }) : null, action] }));
}
export function ErrorState({ error, onRetry, title = "读取失败" }) {
    const code = typeof error?.code === "string" ? error.code : undefined;
    const message = typeof error?.message === "string" && error.message
        ? error.message
        : "服务暂时无法处理请求，请稍后重试。";
    const trace = typeof error?.trace_id === "string" ? error.trace_id : undefined;
    return (_jsxs("div", { className: "state-block", role: "alert", children: [_jsx("span", { className: "state-block-icon", style: { background: "var(--red-soft)", color: "var(--red)" }, children: _jsx(Icon, { name: "alert-triangle", size: 20 }) }), _jsx("strong", { children: title }), _jsx("p", { children: message }), code ? _jsxs("small", { children: ["\u9519\u8BEF\u7801 ", code] }) : null, onRetry ? _jsx(Button, { onClick: onRetry, children: "\u91CD\u8BD5" }) : null, trace ? _jsxs("small", { children: ["Trace ID ", trace] }) : null] }));
}
const AUTH_ERROR_CODES = new Set(["PORTAL_ACCESS_DENIED", "TEACHER_QUALIFICATION_REQUIRED", "PLATFORM_ACCESS_REQUIRED"]);
export function RequestStateView({ loading, error, empty, emptyState, errorTitle, errorMessage, onRetry, forbidden, children, }) {
    if (loading)
        return _jsx(LoadingState, {});
    if (error != null) {
        const code = typeof error?.code === "string" ? error.code : undefined;
        if (forbidden || (code && AUTH_ERROR_CODES.has(code))) {
            return (_jsx(EmptyState, { title: "\u6CA1\u6709\u67E5\u770B\u6743\u9650", hint: "\u5F53\u524D\u8D26\u53F7\u6CA1\u6709\u8BBF\u95EE\u8FD9\u4E9B\u5185\u5BB9\u7684\u6743\u9650\u3002\u5982\u9700\u8981\uFF0C\u8BF7\u8054\u7CFB\u8BFE\u7A0B\u6559\u5E08\u6216\u5E73\u53F0\u7BA1\u7406\u5458\u8C03\u6574\u6743\u9650\u3002", icon: "shield" }));
        }
        return (_jsxs(_Fragment, { children: [_jsx(ErrorState, { error: error, onRetry: onRetry, title: errorTitle }), errorMessage] }));
    }
    if (empty)
        return _jsx(_Fragment, { children: emptyState });
    return _jsx(_Fragment, { children: children });
}
export { Button };
