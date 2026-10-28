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
  const retryRef = useRef<(() => void) | null>(null);

  function intercept(error: unknown, retry: () => void): boolean {
    if (!(error instanceof ApiError) || error.payload?.code !== RECENT_AUTH_CODE) return false;
    retryRef.current = retry;
    setPassword("");
    setOpen(true);
    return true;
  }

  async function confirm() {
    if (busy || !password) return;
    setBusy(true);
    try {
      await meApi.stepUpSession(password);
      setOpen(false);
      const retry = retryRef.current;
      retryRef.current = null;
      if (retry) retry();
    } catch (error) {
      toast.notify(apiErrorMessage(error), "error");
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  function close() {
    if (busy) return;
    setOpen(false);
    retryRef.current = null;
  }

  const dialog = (
    <Modal
      open={open}
      onClose={close}
      eyebrow="安全验证"
      title="该操作需要近期认证"
      actions={(
        <>
          <Button onClick={close} disabled={busy}>取消</Button>
          <Button variant="primary" disabled={busy || !password} onClick={() => void confirm()}>
            {busy ? "验证中…" : "验证并继续"}
          </Button>
        </>
      )}
    >
      <p className="subtle">敏感的管理操作要求最近 5 分钟内完成密码确认。请输入当前账号密码刷新认证状态。</p>
      <label className="form-label" htmlFor="recent-auth-password">当前账号密码</label>
      <input
        id="recent-auth-password"
        type="password"
        className="field"
        autoComplete="current-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") void confirm(); }}
      />
    </Modal>
  );

  return { intercept, dialog };
}