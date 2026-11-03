import { jsx as _jsx } from "react/jsx-runtime";
import { useRef } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { AppShell, EmptyState, LoadingState } from "@edu/ui";
import { useSession } from "./session";
import { usePortalEvents } from "./providers";
const ADMIN_NAV = [
    { label: "平台概览", path: "/" },
    { label: "用户与授权", path: "/users" },
    { label: "治理工作", path: "/governance" },
    { label: "资源治理", path: "/resources" },
    { label: "镜像目录", path: "/images" },
    { label: "Agent 治理", path: "/agents" },
    { label: "异常中心", path: "/incidents" },
    { label: "异常与审计", path: "/audit" },
];
export function PortalSSEBridge() {
    const session = useSession();
    const streamRef = useRef(null);
    usePortalEvents({ enabled: session.me != null, streamRef });
    return null;
}
export function AuthGuard({ shell = true }) {
    const session = useSession();
    const navigate = useNavigate();
    const location = useLocation();
    if (session.loading || session.error?.kind === "auth") {
        return _jsx("div", { className: "app-shell", children: _jsx(LoadingState, { label: "\u6B63\u5728\u786E\u8BA4\u5E73\u53F0\u4F1A\u8BDD" }) });
    }
    if (session.error) {
        return (_jsx("div", { className: "app-shell", children: _jsx(EmptyState, { title: "\u65E0\u6CD5\u8FDB\u5165\u5E73\u53F0\u7BA1\u7406\u95E8\u6237", hint: session.error.payload?.message ?? session.error.message, action: _jsx("button", { type: "button", className: "btn", onClick: session.reload, children: "\u91CD\u65B0\u52A0\u8F7D" }) }) }));
    }
    if (!session.me)
        return _jsx("div", { className: "app-shell", children: _jsx(LoadingState, { label: "\u6B63\u5728\u786E\u8BA4\u5E73\u53F0\u4F1A\u8BDD" }) });
    if (session.me.portal !== "PLATFORM" && !session.me.eligible_portals.includes("PLATFORM")) {
        return (_jsx("div", { className: "app-shell", children: _jsx(EmptyState, { title: "\u5F53\u524D\u8D26\u53F7\u6CA1\u6709\u5E73\u53F0\u7BA1\u7406\u6743\u9650", hint: "\u9700\u8981\u5E73\u53F0\u7BA1\u7406\u5458\u6388\u6743\uFF1B\u8BF7\u901A\u8FC7\u5E73\u53F0\u7BA1\u7406\u5458\u8EAB\u4EFD\u8BBF\u95EE admin.localhost\u3002", icon: "shield" }) }));
    }
    if (!shell)
        return _jsx(Outlet, {});
    const { me, logout } = session;
    const displayName = me.display_name || me.username;
    return (_jsx("div", { className: "app-shell", children: _jsx(AppShell, { domainLabel: "admin.localhost", nav: ADMIN_NAV, activePath: location.pathname, onNavigate: navigate, avatar: { name: displayName, role: "平台管理员", badge: displayName.slice(0, 1) }, avatarItems: [
                { label: "退出登录", icon: "log-out", onClick: () => { void logout().then(() => navigate("/login", { replace: true })); } },
            ], children: _jsx(Outlet, {}) }) }));
}
