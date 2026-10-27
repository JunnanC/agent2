import type { ReactNode } from "react";
import { Icon } from "./icons";

export interface BreadcrumbsProps {
  items: Array<{ label: string; onClick?: () => void }>;
  current: string;
}

export function Breadcrumbs({ items, current }: BreadcrumbsProps) {
  return (
    <nav className="crumb" aria-label="面包屑">
      {items.map((item, index) => (
        <span key={`${item.label}-${index}`}>
          <span
            className={item.onClick ? "crumb-link" : undefined}
            onClick={item.onClick}
            role={item.onClick ? "link" : undefined}
            tabIndex={item.onClick ? 0 : undefined}
            onKeyDown={item.onClick
              ? (event) => { if (event.key === "Enter") item.onClick?.(); }
              : undefined}
          >
            {item.label}
          </span>
          {"　/　"}
        </span>
      ))}
      <b>{current}</b>
    </nav>
  );
}

export interface PageHeaderProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}

export function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  return (
    <div className="head">
      <div>
        <h1>{title}</h1>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {actions ? <div className="actions">{actions}</div> : null}
    </div>
  );
}

export function Panel({ className, title, actions, children, id, style }: {
  className?: string;
  title?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  id?: string;
  style?: React.CSSProperties;
}) {
  return (
    <section className={className ? `panel ${className}` : "panel"} id={id} style={style}>
      {title != null || actions != null ? (
        <div className="panel-title">
          <div>{title}</div>
          {actions ? <div className="actions">{actions}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function StatusBadge({ tone, children }: {
  tone: "good" | "warn" | "blue" | "bad" | "neutral";
  children: ReactNode;
}) {
  return <span className={`status ${tone}`}>{children}</span>;
}

export function Metric({ label, value, sub, icon }: {
  label: string;
  value: ReactNode;
  sub?: string;
  icon?: Parameters<typeof Icon>[0]["name"];
}) {
  return (
    <div className="metric">
      <div className="mrow">
        <span>{label}</span>
        {icon ? <span className="metric-icon"><Icon name={icon} /></span> : null}
      </div>
      <strong>{value}</strong>
      {sub ? <span className="subtle">{sub}</span> : null}
    </div>
  );
}

export function ProgressBar({ value, large }: { value: number; large?: boolean }) {
  const width = Math.max(0, Math.min(100, value));
  return (
    <div className={large ? "progress large" : "progress"} role="progressbar"
      aria-valuemin={0} aria-valuemax={100} aria-valuenow={width}>
      <span style={{ width: `${width}%` }} />
    </div>
  );
}
