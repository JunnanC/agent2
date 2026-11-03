import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
const ToastContext = createContext(null);
export function useToast() {
    const context = useContext(ToastContext);
    if (context)
        return context;
    return { notify: (message) => { if (import.meta.env.DEV)
            console.warn("toast outside provider:", message); } };
}
export function ToastProvider({ children }) {
    const [message, setMessage] = useState(null);
    const timer = useRef(undefined);
    const notify = useCallback((text, tone = "default") => {
        setMessage({ text, error: tone === "error" });
        clearTimeout(timer.current);
        timer.current = setTimeout(() => setMessage(null), 2600);
    }, []);
    const value = useMemo(() => ({ notify }), [notify]);
    return (_jsxs(ToastContext.Provider, { value: value, children: [children, _jsx("div", { className: message ? `toast ${message.error ? "error " : ""}show` : "toast", role: "status", "aria-live": "polite", children: message?.text ?? "" })] }));
}
