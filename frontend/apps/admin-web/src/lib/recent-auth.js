import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { meApi } from "@edu/api-client";
import { ApiError } from "@edu/auth-client";
import { Button, Modal, useToast } from "@edu/ui";
import { useRef, useState } from "react";
import { apiErrorMessage } from "@/lib/format";
const RECENT_AUTH_CODE = "RECENT_AUTHENTICATION_REQUIRED";
/* 平台端敏感写操作超 5 分钟后要求重新输入密码（RECENT_AUTHENTICATION_REQUIRED），
   拦截后弹出密码确认，成功自动重试原操作 */
export function useRecentAuthGuard() {
    const toast = useToast();
    const [open, setOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const [password, setPassword] = useState("");
    const retryRef = useRef(null);
    function intercept(error, retry) {
        if (!(error instanceof ApiError) || error.payload?.code !== RECENT_AUTH_CODE)
            return false;
        retryRef.current = retry;
        setPassword("");
        setOpen(true);
        return true;
    }
    async function confirm() {
        if (busy || !password)
            return;
        setBusy(true);
        try {
            await meApi.stepUpSession(password);
            setOpen(false);
            const retry = retryRef.current;
            retryRef.current = null;
            if (retry)
                retry();
        }
        catch (error) {
            toast.notify(apiErrorMessage(error), "error");
            setPassword("");
        }
        finally {
            setBusy(false);
        }
    }
    function close() {
        if (busy)
            return;
        setOpen(false);
        retryRef.current = null;
    }
    const dialog = (_jsxs(Modal, { open: open, onClose: close, eyebrow: "\u5B89\u5168\u9A8C\u8BC1", title: "\u8BE5\u64CD\u4F5C\u9700\u8981\u8FD1\u671F\u8BA4\u8BC1", actions: (_jsxs(_Fragment, { children: [_jsx(Button, { onClick: close, disabled: busy, children: "\u53D6\u6D88" }), _jsx(Button, { variant: "primary", disabled: busy || !password, onClick: () => void confirm(), children: busy ? "验证中…" : "验证并继续" })] })), children: [_jsx("p", { className: "subtle", children: "\u654F\u611F\u7684\u7BA1\u7406\u64CD\u4F5C\u8981\u6C42\u6700\u8FD1 5 \u5206\u949F\u5185\u5B8C\u6210\u5BC6\u7801\u786E\u8BA4\u3002\u8BF7\u8F93\u5165\u5F53\u524D\u8D26\u53F7\u5BC6\u7801\u5237\u65B0\u8BA4\u8BC1\u72B6\u6001\u3002" }), _jsx("label", { className: "form-label", htmlFor: "recent-auth-password", children: "\u5F53\u524D\u8D26\u53F7\u5BC6\u7801" }), _jsx("input", { id: "recent-auth-password", type: "password", className: "field", autoComplete: "current-password", value: password, onChange: (event) => setPassword(event.target.value), onKeyDown: (event) => { if (event.key === "Enter")
                    void confirm(); } })] }));
    return { intercept, dialog };
}
