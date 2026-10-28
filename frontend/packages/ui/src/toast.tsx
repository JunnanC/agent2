import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

export interface ToastApi {
  notify: (message: string, tone?: "default" | "error") => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (context) return context;
  return { notify: (message) => { if (import.meta.env.DEV) console.warn("toast outside provider:", message); } };
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const notify = useCallback((text: string, tone: "default" | "error" = "default") => {
    setMessage({ text, error: tone === "error" });
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setMessage(null), 2600);
  }, []);

  const value = useMemo(() => ({ notify }), [notify]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className={message ? `toast ${message.error ? "error " : ""}show` : "toast"}
        role="status" aria-live="polite">
        {message?.text ?? ""}
      </div>
    </ToastContext.Provider>
  );
}
