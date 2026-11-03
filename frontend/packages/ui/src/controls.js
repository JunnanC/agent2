import { jsx as _jsx } from "react/jsx-runtime";
export function Button({ children, onClick, variant = "default", size = "md", type = "button", disabled, className, title, ariaLabel, style, }) {
    const classes = [variant === "default" ? "btn" : `btn ${variant}`,
        size === "sm" ? "sm" : "", className].filter(Boolean).join(" ");
    return (_jsx("button", { type: type, className: classes, onClick: onClick, disabled: disabled, title: title, "aria-label": ariaLabel, style: style, children: children }));
}
import { Icon } from "./icons";
export function IconButton({ name, label, onClick, size, className }) {
    return (_jsx("button", { type: "button", className: className ? `icon-btn ${className}` : "icon-btn", "aria-label": label, title: label, onClick: onClick, children: _jsx(Icon, { name: name, size: size }) }));
}
