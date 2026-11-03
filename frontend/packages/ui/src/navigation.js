import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { Icon } from "./icons";
function isGroup(item) {
    return "items" in item;
}
export function AppShell({ brand = "Edu Agent Platform", domainLabel, nav, activePath, onNavigate, avatar, avatarItems = [], actions, children, maxWidth, navigationPosition = "top", }) {
    const [openGroup, setOpenGroup] = useState(null);
    const [avatarOpen, setAvatarOpen] = useState(false);
    useEffect(() => {
        const closeAvatar = () => setAvatarOpen(false);
        document.addEventListener("click", closeAvatar);
        return () => document.removeEventListener("click", closeAvatar);
    }, []);
    const groupActive = (group) => group.items.some((item) => item.path === activePath);
    return (_jsxs("div", { className: `shell-layout${navigationPosition === "side" ? " side-nav-shell" : ""}`, children: [_jsxs("header", { className: "topbar", children: [_jsxs("div", { className: "brand-lockup", children: [_jsx("span", { className: "brand-mark", "aria-hidden": "true", children: _jsx(Icon, { name: "layers", size: 16 }) }), _jsx("span", { className: "brand-name", children: brand }), _jsx("span", { className: "context-dot", "aria-hidden": "true" }), _jsx("span", { className: "context-label", children: domainLabel })] }), _jsx("nav", { className: "primary-nav", "aria-label": "\u4E00\u7EA7\u5BFC\u822A", children: nav.map((item) => {
                            if (!isGroup(item)) {
                                return (_jsx("button", { type: "button", className: `nav-item${activePath === item.path ? " active" : ""}`, "aria-current": activePath === item.path ? "page" : undefined, onClick: () => onNavigate(item.path), children: item.label }, item.path));
                            }
                            const isOpen = openGroup === item.label;
                            return (_jsxs("div", { className: "nav-group", children: [_jsxs("button", { type: "button", className: `nav-item${groupActive(item) ? " active" : ""}`, "aria-expanded": isOpen, "aria-haspopup": "menu", onClick: () => setOpenGroup(isOpen ? null : item.label), children: [item.label, " ", _jsx(Icon, { name: "chevron-down", size: 12 })] }), isOpen ? (_jsx("div", { className: "nav-group-menu", role: "menu", children: item.items.map((child) => (_jsx("button", { type: "button", role: "menuitem", className: activePath.startsWith(child.path) ? "active" : undefined, onClick: () => { setOpenGroup(null); onNavigate(child.path); }, children: child.label }, child.path))) })) : null] }, item.label));
                        }) }), _jsxs("div", { className: "topbar-actions", children: [actions, _jsxs("div", { className: "profile-menu-wrap", children: [_jsxs("button", { type: "button", className: "profile-trigger", "aria-haspopup": "menu", "aria-expanded": avatarOpen, "aria-label": "\u6253\u5F00\u4E2A\u4EBA\u83DC\u5355", onClick: (event) => { event.stopPropagation(); setAvatarOpen((open) => !open); }, children: [_jsx("span", { className: "avatar", children: avatar.badge ?? avatar.name.slice(0, 1) }), _jsxs("span", { className: "profile-trigger-text", children: [_jsx("strong", { children: avatar.name }), _jsx("small", { children: avatar.role })] }), _jsx(Icon, { name: "chevron-down", size: 13 })] }), avatarOpen ? (_jsxs("div", { className: "profile-popover", role: "menu", children: [_jsxs("div", { className: "profile-popover-heading", children: [_jsx("strong", { children: avatar.name }), _jsx("small", { children: avatar.role })] }), avatarItems.map((item) => (_jsxs("button", { type: "button", role: "menuitem", onClick: (event) => { event.stopPropagation(); setAvatarOpen(false); item.onClick?.(); }, children: [item.icon ? _jsx(Icon, { name: item.icon, size: 14 }) : null, _jsx("span", { children: item.label })] }, item.label)))] })) : null] })] })] }), _jsx("main", { className: "main-content", style: maxWidth ? { maxWidth } : undefined, children: children })] }));
}
export function AppShellRoot({ children }) {
    return _jsx("div", { className: "app-shell", children: children });
}
