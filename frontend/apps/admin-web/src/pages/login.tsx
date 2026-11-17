import { PlatformMark } from "@edu/ui";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { authFlow } from "@edu/auth-client";
import { meApi } from "@edu/api-client";
import { queryClient } from "@/app/providers";
import { keys } from "@edu/query-keys";

export function Login() {
  const navigate = useNavigate();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
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
    } catch {
      setError("登录失败，请确认账号密码或稍后重试。");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 20, background: "var(--paper)" }}>
      <form className="panel" style={{ width: "min(420px, 94vw)", display: "grid", gap: 10, padding: 24 }} onSubmit={submit} noValidate>
        <div className="brand-lockup" style={{ marginBottom: 4 }}>
          <span className="brand-mark"><PlatformMark size={26} /></span>
          <span className="brand-name">Edu Agent Platform</span>
          <span className="context-dot" />
          <span className="context-label">admin.localhost · 平台管理</span>
        </div>
        <h1 style={{ fontSize: 22, margin: "4px 0 2px" }}>登录平台管理</h1>
        <p className="subtle" style={{ margin: 0 }}>管理教学账号、课程与镜像，查看平台服务及资源状态。</p>
        <label className="form-label" htmlFor="a-identifier">账号 / 邮箱</label>
        <input id="a-identifier" className="field" autoComplete="username"
          value={identifier} onChange={(event) => setIdentifier(event.target.value)} />
        <label className="form-label" htmlFor="a-password">密码</label>
        <input id="a-password" type="password" className="field" autoComplete="current-password"
          value={password} onChange={(event) => setPassword(event.target.value)} />
        {error ? <div className="field-error" role="alert">{error}</div> : null}
        <button type="submit" className="btn primary" style={{ marginTop: 10, justifyContent: "center" }} disabled={submitting}>
          {submitting ? "登录中…" : "登录平台管理"}
        </button>
        <small>平台操作会记录操作日志并支持 Trace 检索。</small>
      </form>
    </div>
  );
}
