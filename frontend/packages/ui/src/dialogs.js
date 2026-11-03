import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useId, useRef } from "react";
import { Icon } from "./icons";
import { Button } from "./controls";
function useModalFocus(open, onClose) {
    const containerRef = useRef(null);
    const previouslyFocused = useRef(null);
    /* onClose 用 ref 存：页面常传内联函数，若作为依赖会让本 effect 在每次父级重渲染时重跑，
       反复抢焦点并把弹窗/抽屉滚动位置拉回顶部 */
    const onCloseRef = useRef(onClose);
    onCloseRef.current = onClose;
    useEffect(() => {
        if (!open)
            return;
        previouslyFocused.current = document.activeElement;
        const container = containerRef.current;
        container?.querySelector("button, input, select, textarea, [tabindex]")?.focus({ preventScroll: true });
        document.body.style.overflow = "hidden";
        const onKeyDown = (event) => {
            if (event.key === "Escape") {
                onCloseRef.current();
                return;
            }
            if (event.key !== "Tab" || !container)
                return;
            const focusable = container.querySelectorAll("button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex='-1'])");
            if (!focusable.length)
                return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (first == null || last == null)
                return;
            if (event.shiftKey && (document.activeElement === first)) {
                event.preventDefault();
                last.focus({ preventScroll: true });
            }
            else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus({ preventScroll: true });
            }
        };
        document.addEventListener("keydown", onKeyDown);
        return () => {
            document.removeEventListener("keydown", onKeyDown);
            document.body.style.overflow = "";
            previouslyFocused.current?.focus();
        };
    }, [open]);
    return containerRef;
}
export function Modal({ open, onClose, title, eyebrow, children, actions, wide }) {
    const titleId = useId();
    const containerRef = useModalFocus(open, onClose);
    if (!open)
        return null;
    return (_jsx("div", { className: "modal-backdrop open", onClick: (event) => { if (event.target === event.currentTarget)
            onClose(); }, children: _jsxs("div", { className: wide ? "modal wide" : "modal", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId, ref: containerRef, children: [eyebrow ? _jsx("div", { className: "modal-eyebrow", children: eyebrow }) : null, _jsx("h2", { id: titleId, children: title }), children, actions ? _jsx("div", { className: "modal-actions", children: actions }) : null] }) }));
}
export function ConfirmDialog({ open, onClose, onConfirm, title, eyebrow, description, confirmLabel = "确认", cancelLabel = "取消", tone = "primary", busy, }) {
    return (_jsx(Modal, { open: open, onClose: onClose, title: title, eyebrow: eyebrow, actions: (_jsxs(_Fragment, { children: [_jsx(Button, { onClick: onClose, disabled: busy, children: cancelLabel }), _jsx(Button, { variant: tone, onClick: onConfirm, disabled: busy, children: busy ? "处理中…" : confirmLabel })] })), children: _jsx("div", { className: "section", children: description }) }));
}
export function Drawer({ open, onClose, title, children }) {
    const titleId = useId();
    const containerRef = useModalFocus(open, onClose);
    if (!open)
        return null;
    return (_jsx("div", { className: "drawer-backdrop", onClick: (event) => { if (event.target === event.currentTarget)
            onClose(); }, children: _jsxs("aside", { className: "drawer", role: "dialog", "aria-modal": "true", "aria-labelledby": titleId, ref: containerRef, children: [_jsxs("div", { className: "panel-title", children: [_jsx("h2", { children: title }), _jsx("button", { type: "button", className: "icon-btn", onClick: onClose, "aria-label": "\u5173\u95ED\u62BD\u5C49", children: _jsx(Icon, { name: "x" }) })] }), children] }) }));
}
