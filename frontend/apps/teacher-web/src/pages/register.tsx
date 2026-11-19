import { PlatformMark } from "@edu/ui";
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

  return <div className="auth-shell">
    <form className="auth-card" onSubmit={submit}>
      <div className="auth-brand">
        <span className="brand-mark"><PlatformMark size={26} /></span>
        <span className="brand-name">实验教学平台</span>
        <span className="auth-portal">教师门户</span>
      </div>
      <h1>{token ? "验证邮箱" : "注册教师账号"}</h1>
      {done ? <p className="auth-hint">{token ? "邮箱验证成功，教师资格待管理员审核。" : "验证邮件已发送，请查收。"}</p> : token ? <p className="auth-hint">确认邮箱后，教师资格将进入待审核状态。</p> : <>
        <label className="form-label" htmlFor="teacher-email">邮箱</label>
        <input className="field" id="teacher-email" name="email" type="email" autoComplete="email" required />
        <label className="form-label" htmlFor="teacher-username">用户名</label>
        <input className="field" id="teacher-username" name="username" minLength={3} maxLength={32} required />
        <label className="form-label" htmlFor="teacher-name">姓名</label>
        <input className="field" id="teacher-name" name="display_name" maxLength={64} required />
        <label className="form-label" htmlFor="teacher-password">密码</label>
        <input className="field" id="teacher-password" name="password" type="password" autoComplete="new-password" minLength={12} required />
      </>}
      {error ? <p className="field-error" role="alert">{error}</p> : null}
      {!done ? <button className="btn primary" type="submit" style={{ marginTop: 6 }} disabled={submitting}>{submitting ? "处理中…" : token ? "完成验证" : "发送验证邮件"}</button> : null}
      <div className="auth-footer"><Link to="/login">返回登录</Link></div>
    </form>
  </div>;
}
