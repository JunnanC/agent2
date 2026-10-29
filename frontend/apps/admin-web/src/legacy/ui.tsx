import type { ReactNode } from "react";
import * as ui from "../../../../packages/ui/src/index";

export * from "../../../../packages/ui/src/index";

export function PageHeader(props: {
  title: string;
  subtitle?: string;
  eyebrow?: string;
  description?: string;
  actions?: ReactNode;
}) {
  const subtitle = [props.eyebrow, props.description].filter(Boolean).join(" / ") || props.subtitle;
  return <ui.PageHeader title={props.title} subtitle={subtitle} actions={props.actions} />;
}

export function StatusBadge({ status, tone, children }: {
  status?: string;
  tone?: "good" | "warn" | "blue" | "bad" | "neutral";
  children?: ReactNode;
}) {
  const badgeTone = tone ?? (/ACTIVE|APPROVED|HEALTHY|PASSED|RESOLVED/i.test(status ?? "")
    ? "good"
    : /FAILED|REJECTED|BLOCKED|CRITICAL/i.test(status ?? "") ? "bad" : "neutral");
  return <ui.StatusBadge tone={badgeTone}>{children ?? status}</ui.StatusBadge>;
}

type LegacyRequestStateProps = Omit<ui.RequestStateViewProps, "loading" | "error" | "empty"> & Partial<Pick<ui.RequestStateViewProps, "loading" | "error" | "empty">> & {
  state?: "loading" | "error" | "empty" | "forbidden" | "conflict" | "precondition";
  message?: ReactNode;
  traceId?: string;
};

export function RequestStateView(props: LegacyRequestStateProps) {
  if (!props.state) return <ui.RequestStateView loading={props.loading ?? false} error={props.error ?? null} empty={props.empty ?? false} emptyState={props.emptyState} errorTitle={props.errorTitle} errorMessage={props.errorMessage} onRetry={props.onRetry} forbidden={props.forbidden}>{props.children}</ui.RequestStateView>;
  if (props.state === "loading") return <ui.LoadingState />;
  if (props.state === "empty") return <ui.EmptyState title="暂无数据" />;
  const error = props.message ?? (props.traceId ? `Trace ID ${props.traceId}` : "请求暂时不可用。");
  return <ui.ErrorState error={error} onRetry={props.onRetry} title={props.state === "forbidden" ? "没有查看权限" : "请求失败"} />;
}

export function TextField({ label, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return <label className="field"><span>{label}</span><input {...props} /></label>;
}
