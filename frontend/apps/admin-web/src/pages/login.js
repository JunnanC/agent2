import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { authFlow } from "@edu/auth-client";
import { meApi } from "@edu/api-client";
import { queryClient } from "@/app/providers";
import { keys } from "@edu/query-keys";
import { Icon } from "@edu/ui";
export function Login() {
    const navigate = useNavigate();
    const [identifier, setIdentifier] = useState("");
    const [password, setPassword] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState(null);
    const submit = async (event) => {
        event.preventDefault();
        if (!identifier.trim() || !password) {
            setError("请输入账号与密码。");
            return;
        }
        setSubmitting(true);
        setError(null);
        try {
            await authFlow.initCsrf();
            await authFlow.login(identifier.trim(), password);
            const me = await meApi.retrieve();
            if (me.portal !== "PLATFORM" && !me.eligible_portals.includes("PLATFORM")) {
                setError("此账号没有平台管理员权限，无法登录平台管理门户。");
                return;
            }
            queryClient.setQueryData([...keys.me(), "current"], me);
            queryClient.invalidateQueries();
            navigate("/", { replace: true });
        }
        catch {
            setError("登录失败，请确认账号密码或稍后重试。");
        }
        finally {
            setSubmitting(false);
        }
    };
    return (_jsx("div", { style: { minHeight: "100vh", display: "grid", placeItems: "center", padding: 20, background: "var(--paper)" }, children: _jsxs("form", { className: "panel", style: { width: "min(420px, 94vw)", display: "grid", gap: 10, padding: 24 }, onSubmit: submit, noValidate: true, children: [_jsxs("div", { className: "brand-lockup", style: { marginBottom: 4 }, children: [_jsx("span", { className: "brand-mark", children: _jsx(Icon, { name: "layers", size: 16 }) }), _jsx("span", { className: "brand-name", children: "Edu Agent Platform" }), _jsx("span", { className: "context-dot" }), _jsx("span", { className: "context-label", children: "admin.localhost \u00B7 \u5E73\u53F0\u7BA1\u7406" })] }), _jsx("h1", { style: { fontSize: 22, margin: "4px 0 2px" }, children: "\u767B\u5F55\u5E73\u53F0\u7BA1\u7406" }), _jsx("p", { className: "subtle", style: { margin: 0 }, children: "\u5E73\u53F0\u7BA1\u7406\u5458\u56F4\u7ED5\u6CBB\u7406\u3001\u8FD0\u884C\u3001\u5B89\u5168\u4E0E\u5BA1\u8BA1\u7EC4\u7EC7\u5DE5\u4F5C\u3002" }), _jsx("label", { className: "form-label", htmlFor: "a-identifier", children: "\u8D26\u53F7 / \u90AE\u7BB1" }), _jsx("input", { id: "a-identifier", className: "field", autoComplete: "username", value: identifier, onChange: (event) => setIdentifier(event.target.value) }), _jsx("label", { className: "form-label", htmlFor: "a-password", children: "\u5BC6\u7801" }), _jsx("input", { id: "a-password", type: "password", className: "field", autoComplete: "current-password", value: password, onChange: (event) => setPassword(event.target.value) }), error ? _jsx("div", { className: "field-error", role: "alert", children: error }) : null, _jsx("button", { type: "submit", className: "btn primary", style: { marginTop: 10, justifyContent: "center" }, disabled: submitting, children: submitting ? "登录中…" : "登录平台管理" }), _jsx("small", { children: "\u5E73\u53F0\u64CD\u4F5C\u4F1A\u8BB0\u5F55\u64CD\u4F5C\u65E5\u5FD7\u5E76\u652F\u6301 Trace \u68C0\u7D22\u3002" })] }) }));
}
