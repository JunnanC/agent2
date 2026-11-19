import { PlatformMark } from "@edu/ui";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { authFlow } from "@edu/auth-client";
import { queryClient, meApiFn } from "@/app/api";
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
      const me = await meApiFn();
      if (me.portal !== "USER" && !me.eligible_portals.includes("USER")) {
        setError("此账号属于教师或平台门户，请通过对应门户登录。");
        return;
      }
      queryClient.setQueryData([...keys.me(), "current"], me);
      queryClient.invalidateQueries();
      navigate("/", { replace: true });
    } catch (caught) {
      const status = (caught as { status?: number }).status;
      setError(status === 401
        ? "账号或密码不正确，请重试。"
        : "登录失败，请稍后重试。");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={submit} noValidate>
        <div className="auth-brand">
          <span className="brand-mark"><PlatformMark size={26} /></span>
          <span className="brand-name">实验教学平台</span>
          <span className="auth-portal">学生门户</span>
        </div>
        <h1>登录学生门户</h1>

        <label className="form-label" htmlFor="login-identifier">学号 / 账号 / 邮箱</label>
        <input id="login-identifier" className="field" autoComplete="username"
          value={identifier} onChange={(event) => setIdentifier(event.target.value)} />

        <label className="form-label" htmlFor="login-password">密码</label>
        <input id="login-password" type="password" className="field" autoComplete="current-password"
          value={password} onChange={(event) => setPassword(event.target.value)} />

        {error ? <div className="field-error" role="alert">{error}</div> : null}

        <button type="submit" className="btn primary" style={{ marginTop: 6, justifyContent: "center" }} disabled={submitting}>
          {submitting ? "登录中…" : "登录"}
        </button>
        <div className="auth-footer"><Link to="/register">注册学生账号</Link></div>
      </form>
    </div>
  );
}
