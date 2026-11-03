import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Icon } from "./icons";
export function Breadcrumbs({ items, current }) {
    return (_jsxs("nav", { className: "crumb", "aria-label": "\u9762\u5305\u5C51", children: [items.map((item, index) => (_jsxs("span", { children: [_jsx("span", { className: item.onClick ? "crumb-link" : undefined, onClick: item.onClick, role: item.onClick ? "link" : undefined, tabIndex: item.onClick ? 0 : undefined, onKeyDown: item.onClick
                            ? (event) => { if (event.key === "Enter")
                                item.onClick?.(); }
                            : undefined, children: item.label }), "　/　"] }, `${item.label}-${index}`))), _jsx("b", { children: current })] }));
}
export function PageHeader({ title, subtitle, actions }) {
    return (_jsxs("div", { className: "head", children: [_jsxs("div", { children: [_jsx("h1", { children: title }), subtitle ? _jsx("p", { children: subtitle }) : null] }), actions ? _jsx("div", { className: "actions", children: actions }) : null] }));
}
export function Panel({ className, title, actions, children, id, style }) {
    return (_jsxs("section", { className: className ? `panel ${className}` : "panel", id: id, style: style, children: [title != null || actions != null ? (_jsxs("div", { className: "panel-title", children: [_jsx("div", { children: title }), actions ? _jsx("div", { className: "actions", children: actions }) : null] })) : null, children] }));
}
export function StatusBadge({ tone, children }) {
    return _jsx("span", { className: `status ${tone}`, children: children });
}
export function Metric({ label, value, sub, icon }) {
    return (_jsxs("div", { className: "metric", children: [_jsxs("div", { className: "mrow", children: [_jsx("span", { children: label }), icon ? _jsx("span", { className: "metric-icon", children: _jsx(Icon, { name: icon }) }) : null] }), _jsx("strong", { children: value }), sub ? _jsx("span", { className: "subtle", children: sub }) : null] }));
}
export function ProgressBar({ value, large }) {
    const width = Math.max(0, Math.min(100, value));
    return (_jsx("div", { className: large ? "progress large" : "progress", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": width, children: _jsx("span", { style: { width: `${width}%` } }) }));
}
