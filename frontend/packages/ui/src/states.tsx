import type { ReactNode } from "react";
import { Icon } from "./icons";
import { Button, ButtonProps } from "./controls";

export interface AppError {
  code?: string;
  message: string;
  trace_id?: string;
}

export function LoadingState({ label = "正在加载" }: { label?: string }) {
  return (
    <div className="skeleton" role="status" aria-live="polite" aria-label={label}>
      <span className="skeleton-line title" />
      <span className="skeleton-line w60" />
      <span className="skeleton-line w40" />
      <span className="skeleton-line w60" />
    </div>
  );
}

export function EmptyState({ title, hint, action, icon = "info" }: {
  title: string;
  hint?: string;
  action?: ReactNode;
  icon?: Parameters<typeof Icon>[0]["name"];
}) {
  return (
    <div className="state-block">
      <span className="state-block-icon"><Icon name={icon} size={20} /></span>
      <strong>{title}</strong>
      {hint ? <p>{hint}</p> : null}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry, title = "读取失败" }: {
  error: AppError | Error | unknown;
  onRetry?: () => void;
  title?: string;
}) {
  const code = typeof (error as AppError)?.code === "string" ? (error as AppError).code : undefined;
  const message = typeof (error as AppError)?.message === "string" && (error as AppError).message
    ? (error as AppError).message
    : "服务暂时无法处理请求，请稍后重试。";
  const trace = typeof (error as AppError)?.trace_id === "string" ? (error as AppError).trace_id : undefined;
  return (
    <div className="state-block" role="alert">
      <span className="state-block-icon" style={{ background: "var(--red-soft)", color: "var(--red)" }}>
        <Icon name="alert-triangle" size={20} />
      </span>
      <strong>{title}</strong>
      <p>{message}</p>
      {code ? <small>错误码 {code}</small> : null}
      {onRetry ? <Button onClick={onRetry}>重试</Button> : null}
      {trace ? <small>Trace ID {trace}</small> : null}
    </div>
  );
}

export interface RequestStateViewProps {
  loading: boolean;
  error: unknown;
  empty: boolean;
  emptyState?: ReactNode;
  errorTitle?: string;
  errorMessage?: ReactNode;
  onRetry?: () => void;
  forbidden?: boolean;
  children?: ReactNode;
}

const AUTH_ERROR_CODES = new Set(["PORTAL_ACCESS_DENIED", "TEACHER_QUALIFICATION_REQUIRED", "PLATFORM_ACCESS_REQUIRED"]);

export function RequestStateView({
  loading, error, empty, emptyState, errorTitle, errorMessage, onRetry, forbidden, children,
}: RequestStateViewProps) {
  if (loading) return <LoadingState />;
  if (error != null) {
    const code = typeof (error as AppError)?.code === "string" ? (error as AppError).code : undefined;
    if (forbidden || (code && AUTH_ERROR_CODES.has(code))) {
      return (
        <EmptyState
          title="没有查看权限"
          hint="当前账号没有访问这些内容的权限。如需要，请联系课程教师或平台管理员调整权限。"
          icon="shield"
        />
      );
    }
    return (
      <>
        <ErrorState error={error} onRetry={onRetry} title={errorTitle} />
        {errorMessage}
      </>
    );
  }
  if (empty) return <>{emptyState}</>;
  return <>{children}</>;
}

export interface ButtonLikeProps extends Omit<ButtonProps, "variant"> {
  variant?: ButtonProps["variant"];
}

export { Button };
