import { Component, type ErrorInfo, type FormEvent, type InputHTMLAttributes, type ReactNode } from 'react'
import {
  Activity,
  ArrowRight,
  BookOpen,
  CircleAlert,
  Clock3,
  Copy,
  LoaderCircle,
  LockKeyhole,
  Mail,
  RefreshCw,
  SearchX,
  Server,
  ShieldX,
  UserRound,
  TriangleAlert,
} from 'lucide-react'

export type PortalTone = 'user' | 'teacher' | 'admin'

export interface ReleaseInfo {
  version: string
  openapiRevision: string
  gitRevision: string
  buildTime: string
}

export function PortalLayout({
  title,
  tone,
  release,
  children,
  nav,
  actions,
  variant = 'default',
}: {
  title: string
  tone: PortalTone
  release: ReleaseInfo
  children: ReactNode
  nav?: Array<{ href: string; label: string }>
  actions?: ReactNode
  variant?: 'default' | 'workbench' | 'immersive'
}) {
  return (
    <div className={`portal portal--${tone} portal--${variant}`}>
      <header className="portal__header">
        <a className="brand" href="/health" aria-label={`${title}首页`}>
          <span className="brand__mark"><BookOpen size={19} aria-hidden="true" /></span>
          <span>
            <strong>教学云实验平台</strong>
            <small>{title}</small>
          </span>
        </a>
        <div className="portal__header-actions">
          <nav className="portal__nav" aria-label="主导航">
            {(nav ?? [{ href: '/login', label: '登录' }]).map((item) => (
              <a href={item.href} key={item.href}>{item.label}</a>
            ))}
          </nav>
          {actions}
        </div>
      </header>
      <main className="portal__main">{children}</main>
      <footer className="portal__footer">
        <span>v{release.version}</span>
        <span>API {release.openapiRevision}</span>
        <span title={release.buildTime}>{release.gitRevision}</span>
      </footer>
    </div>
  )
}

export function TextField({ label, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  const id = props.id ?? props.name
  const Icon = props.type === 'password' ? LockKeyhole : props.type === 'email' ? Mail : UserRound
  return (
    <label className="field" htmlFor={id}>
      <span>{label}</span>
      <span className="field__control">
        <Icon size={18} aria-hidden="true" />
        <input id={id} {...props} />
      </span>
    </label>
  )
}

export function LoginForm({
  title,
  busy,
  error,
  onSubmit,
}: {
  title: string
  busy: boolean
  error: string
  onSubmit: (identifier: string, password: string) => void
}) {
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    onSubmit(String(data.get('identifier') ?? ''), String(data.get('password') ?? ''))
  }
  return (
    <section className="auth-layout" aria-labelledby="login-title">
      <div className="auth-layout__context">
        <span className="eyebrow">EDU LAB CLOUD</span>
        <h1 id="login-title">{title}</h1>
        <p>使用平台账号继续。</p>
        <div className="context-signal"><Server size={18} /> 独立安全会话</div>
      </div>
      <form className="login-form" onSubmit={submit}>
        <h2>账号登录</h2>
        <TextField label="邮箱或用户名" name="identifier" autoComplete="username" required />
        <TextField label="密码" name="password" type="password" autoComplete="current-password" required />
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <button className="primary-button" type="submit" disabled={busy}>
          <span>{busy ? '正在登录' : '登录'}</span>
          <ArrowRight size={18} aria-hidden="true" />
        </button>
      </form>
    </section>
  )
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string
  title: string
  description?: string
  actions?: ReactNode
}) {
  return (
    <header className="page-header">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
      </div>
      {actions ? <div className="page-header__actions">{actions}</div> : null}
    </header>
  )
}

export function StatusBadge({ status }: { status: string }) {
  const tone = ['ACTIVE', 'APPROVED'].includes(status)
    ? 'success'
    : ['DISABLED', 'REVOKED', 'REJECTED'].includes(status)
      ? 'danger'
      : ['SUSPENDED', 'SUBMITTED'].includes(status)
        ? 'warning'
        : 'neutral'
  return <span className={`status-badge status-badge--${tone}`}>{status}</span>
}

export function HealthView({
  title,
  status,
  detail,
  traceId,
  retry,
}: {
  title: string
  status: 'loading' | 'ok' | 'error'
  detail: string
  traceId?: string
  retry: () => void
}) {
  return (
    <section className="status-page" aria-labelledby="status-title">
      <div>
        <span className="eyebrow">SYSTEM STATUS</span>
        <h1 id="status-title">{title}</h1>
        <p className="status-page__lead">基础服务状态</p>
      </div>
      <div className="status-row">
        <span className={`status-dot status-dot--${status}`} aria-hidden="true" />
        <div>
          <strong>{status === 'loading' ? '正在检查' : status === 'ok' ? '服务正常' : '服务异常'}</strong>
          <p>{detail}</p>
        </div>
        <Activity size={22} aria-hidden="true" />
      </div>
      {traceId ? <p className="trace">Trace ID <code>{traceId}</code></p> : null}
      {status === 'error' ? <button className="secondary-button" onClick={retry}>重新检查</button> : null}
    </section>
  )
}

export function ErrorView({ code, title, message }: { code: string; title: string; message: string }) {
  return (
    <section className="error-page">
      <span className="error-page__code">{code}</span>
      <h1>{title}</h1>
      <p>{message}</p>
      <a className="secondary-button" href="/health">返回状态页</a>
    </section>
  )
}

export type RequestState =
  | 'loading'
  | 'empty'
  | 'error'
  | 'forbidden'
  | 'conflict'
  | 'stale'
  | 'precondition'
  | 'rate-limited'

const requestStateDefaults = {
  loading: { title: '正在加载', Icon: LoaderCircle },
  empty: { title: '暂无数据', Icon: SearchX },
  error: { title: '请求失败', Icon: CircleAlert },
  forbidden: { title: '无权访问', Icon: ShieldX },
  conflict: { title: '当前状态已发生变化', Icon: RefreshCw },
  stale: { title: '内容已被更新', Icon: RefreshCw },
  precondition: { title: '缺少更新条件', Icon: TriangleAlert },
  'rate-limited': { title: '请求过于频繁', Icon: Clock3 },
} as const

export function RequestStateView({
  state,
  title,
  message,
  traceId,
  onRetry,
}: {
  state: RequestState
  title?: string
  message?: string
  traceId?: string
  onRetry?: () => void
}) {
  const defaults = requestStateDefaults[state]
  const Icon = defaults.Icon
  const copyTrace = () => {
    if (traceId && navigator.clipboard) void navigator.clipboard.writeText(traceId)
  }
  return (
    <section className={`request-state request-state--${state}`} aria-live="polite">
      <span className="request-state__icon" aria-hidden="true">
        <Icon size={24} />
      </span>
      <div className="request-state__body">
        <h2>{title ?? defaults.title}</h2>
        {message ? <p>{message}</p> : null}
        {traceId ? (
          <div className="request-state__trace">
            <span>Trace ID</span>
            <code>{traceId}</code>
            <button type="button" onClick={copyTrace} title="复制 Trace ID" aria-label="复制 Trace ID">
              <Copy size={15} aria-hidden="true" />
            </button>
          </div>
        ) : null}
      </div>
      {onRetry && state !== 'loading' ? (
        <button className="secondary-button" type="button" onClick={onRetry}>
          <RefreshCw size={16} aria-hidden="true" />
          <span>重试</span>
        </button>
      ) : null}
    </section>
  )
}

export class AppErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Application render failed', { error: error.message, componentStack: info.componentStack })
  }

  render() {
    if (this.state.failed) {
      return <ErrorView code="500" title="页面加载失败" message="请求未完成，请稍后重试。" />
    }
    return this.props.children
  }
}
