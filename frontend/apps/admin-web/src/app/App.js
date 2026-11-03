import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { configureRequestHooks } from "@edu/auth-client";
import { LoadingState, ToastProvider } from "@edu/ui";
import { queryClient } from "./providers";
import { AuthGuard, PortalSSEBridge } from "./guards";
import { Login } from "@/pages/login";
import { Users } from "@/pages/users";
import { Governance } from "@/pages/governance";
import { Resources } from "@/pages/resources";
import { Images } from "@/pages/images";
import { Incidents } from "@/pages/incidents";
import { Audit } from "@/pages/audit";
import { Agents } from "@/pages/agents";
import ManagementConsole from "../App";
export function App() {
    return (_jsx(QueryClientProvider, { client: queryClient, children: _jsx(ToastProvider, { children: _jsxs(BrowserRouter, { children: [_jsx(RequestHookBridge, {}), _jsx(PortalSSEBridge, {}), _jsxs(Routes, { children: [_jsx(Route, { path: "/login", element: _jsx(Login, {}) }), _jsx(Route, { element: _jsx(AuthGuard, { shell: false }), children: _jsx(Route, { path: "/", element: _jsx(ManagementConsole, {}) }) }), _jsxs(Route, { element: _jsx(AuthGuard, {}), children: [_jsx(Route, { path: "/users", element: _jsx(Users, {}) }), _jsx(Route, { path: "/governance", element: _jsx(Governance, {}) }), _jsx(Route, { path: "/resources", element: _jsx(Resources, {}) }), _jsx(Route, { path: "/images", element: _jsx(Images, {}) }), _jsx(Route, { path: "/incidents", element: _jsx(Incidents, {}) }), _jsx(Route, { path: "/audit", element: _jsx(Audit, {}) }), _jsx(Route, { path: "/agents", element: _jsx(Agents, {}) })] }), _jsx(Route, { path: "*", element: _jsx(Navigate, { to: "/", replace: true }) })] })] }) }) }));
}
function RequestHookBridge() {
    const navigate = useNavigate();
    useEffect(() => {
        configureRequestHooks({
            onAuthExpired: () => {
                queryClient.clear();
                navigate("/login", { replace: true });
            },
        });
    }, [navigate]);
    return null;
}
export function FullPageLoading() {
    return (_jsx("div", { style: { display: "grid", placeItems: "center", minHeight: "60vh", padding: 40 }, children: _jsx(LoadingState, { label: "\u6B63\u5728\u8F7D\u5165\u5E73\u53F0\u7BA1\u7406\u95E8\u6237" }) }));
}
