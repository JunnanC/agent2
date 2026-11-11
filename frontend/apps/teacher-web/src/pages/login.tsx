import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
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
      if (me.portal !== "TEACHING" && !me.eligible_portals.includes("TEACHING")) {
        setError("此账号没有教师门户资格；请使用完成教师认证的账号，或走资格申请流程。");
        return;
      }
      queryClient.setQueryData([...keys.me(), "current"], me);
      queryClient.invalidateQueries();
      navigate("/", { replace: true });
    } catch (caught) {
      const status = (caught as { status?: number }).status;
      setError(status === 403
        ? "教师资格仍在审核中或未获批准。"
        : "登录失败，请确认账号密码或稍后重试。");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 20, background: "var(--paper)" }}>
      <form className="panel" style={{ width: "min(420px, 94vw)", display: "grid", gap: 10, padding: 24 }} onSubmit={submit} noValidate>
        <div className="brand-lockup" style={{ marginBottom: 4 }}>
          <span className="brand-mark"><Icon name="layers" size={16} /></span>
          <span className="brand-name">Edu Agent Platform</span>
          <span className="context-dot" />
          <span className="context-label">teacher.localhost · 教师门户</span>
        </div>
        <h1 style={{ fontSize: 22, margin: "4px 0 2px" }}>登录教师门户</h1>
        <p className="subtle" style={{ margin: 0 }}>
          教师门户围绕课程建设、实验发布与学生评审组织。
        </p>
        <label className="form-label" htmlFor="t-identifier">账号 / 邮箱</label>
        <input id="t-identifier" className="field" autoComplete="username"
          value={identifier} onChange={(event) => setIdentifier(event.target.value)} />
        <label className="form-label" htmlFor="t-password">密码</label>
        <input id="t-password" type="password" className="field" autoComplete="current-password"
          value={password} onChange={(event) => setPassword(event.target.value)} />
        {error ? <div className="field-error" role="alert">{error}</div> : null}
        <button type="submit" className="btn primary" style={{ marginTop: 10, justifyContent: "center" }} disabled={submitting}>
          {submitting ? "登录中…" : "登录教师门户"}
        </button>
        <Link to="/register">注册教师账号</Link>
        <small>完成邮箱验证后，教师资格需经管理员审核。</small>
      </form>
    </div>
  );
}
