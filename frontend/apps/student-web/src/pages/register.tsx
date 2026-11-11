import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { authFlow } from "@edu/auth-client";

export function Register() {
  const [params] = useSearchParams();
  const token = params.get("token");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      if (token) {
        await authFlow.verifyEmail(token);
      } else {
        const values = Object.fromEntries(new FormData(event.currentTarget));
        await authFlow.register(values as { email: string; username: string; display_name: string; password: string });
      }
      setDone(true);
    } catch {
      setError(token ? "验证链接无效或已过期，请重新注册。" : "注册未完成，请检查填写内容后重试。");
    } finally {
      setSubmitting(false);
    }
  };

  return <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 20, background: "var(--paper)" }}>
    <form className="panel" style={{ width: "min(420px, 94vw)", display: "grid", gap: 10, padding: 24 }} onSubmit={submit}>
      <h1 style={{ fontSize: 22, margin: 0 }}>{token ? "验证邮箱" : "注册学生账号"}</h1>
      {done ? <p>{token ? "邮箱验证成功，现在可以登录学生端。" : "若邮箱可用于注册，验证邮件已发送，请查收。"}</p> : token ? <p>确认邮箱后即可使用学生端。</p> : <>
        <label className="form-label" htmlFor="student-email">邮箱</label>
        <input className="field" id="student-email" name="email" type="email" autoComplete="email" required />
        <label className="form-label" htmlFor="student-username">用户名</label>
        <input className="field" id="student-username" name="username" minLength={3} maxLength={32} required />
        <label className="form-label" htmlFor="student-name">姓名</label>
        <input className="field" id="student-name" name="display_name" maxLength={64} required />
        <label className="form-label" htmlFor="student-password">密码</label>
        <input className="field" id="student-password" name="password" type="password" autoComplete="new-password" minLength={12} required />
      </>}
      {error ? <p className="field-error" role="alert">{error}</p> : null}
      {!done ? <button className="btn primary" type="submit" disabled={submitting}>{submitting ? "处理中…" : token ? "完成验证" : "发送验证邮件"}</button> : null}
      <Link to="/login">返回登录</Link>
    </form>
  </div>;
}
