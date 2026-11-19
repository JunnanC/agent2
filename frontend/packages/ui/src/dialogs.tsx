import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";
import { Icon } from "./icons";
import { Button } from "./controls";

function useModalFocus(open: boolean, onClose: () => void) {
  const containerRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  /* onClose 用 ref 存：页面常传内联函数，若作为依赖会让本 effect 在每次父级重渲染时重跑，
     反复抢焦点并把弹窗/抽屉滚动位置拉回顶部 */
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const container = containerRef.current;
    container?.querySelector<HTMLElement>("button, input, select, textarea, [tabindex]")?.focus({ preventScroll: true });
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { onCloseRef.current(); return; }
      if (event.key !== "Tab" || !container) return;
      const focusable = container.querySelectorAll<HTMLElement>(
        "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex='-1'])",
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (first == null || last == null) return;
      if (event.shiftKey && (document.activeElement === first)) {
        event.preventDefault(); last.focus({ preventScroll: true });
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus({ preventScroll: true });
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = "";
      previouslyFocused.current?.focus();
    };
  }, [open]);

  return containerRef;
}

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  eyebrow?: string;
  children: ReactNode;
  actions?: ReactNode;
  wide?: boolean;
  labelledBy?: string;
}

export function Modal({ open, onClose, title, eyebrow, children, actions, wide }: ModalProps) {
  const titleId = useId();
  const containerRef = useModalFocus(open, onClose);
  if (!open) return null;
  return (
    <div role="presentation" className="modal-backdrop open" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className={wide ? "modal wide" : "modal"} role="dialog" aria-modal="true" aria-labelledby={titleId} ref={containerRef}>
        <div className="modal-head">
          {eyebrow ? <div className="modal-eyebrow">{eyebrow}</div> : null}
          <h2 id={titleId}>{title}</h2>
        </div>
        <div className="modal-body">{children}</div>
        {actions ? <div className="modal-actions">{actions}</div> : null}
      </div>
    </div>
  );
}

export interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  eyebrow?: string;
  description: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "primary" | "danger";
  busy?: boolean;
}

export function ConfirmDialog({
  open, onClose, onConfirm, title, eyebrow, description,
  confirmLabel = "确认", cancelLabel = "取消", tone = "primary", busy,
}: ConfirmDialogProps) {
  return (
    <Modal open={open} onClose={onClose} title={title} eyebrow={eyebrow} actions={(
      <>
        <Button onClick={onClose} disabled={busy}>{cancelLabel}</Button>
        <Button variant={tone} onClick={onConfirm} disabled={busy}>
          {busy ? "处理中…" : confirmLabel}
        </Button>
      </>
    )}>
      <div className="section">{description}</div>
    </Modal>
  );
}

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}

export function Drawer({ open, onClose, title, children }: DrawerProps) {
  const titleId = useId();
  const containerRef = useModalFocus(open, onClose);
  if (!open) return null;
  return (
    <div role="presentation" className="drawer-backdrop" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={containerRef}>
        <div className="panel-title">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭抽屉">
            <Icon name="x" />
          </button>
        </div>
        {children}
      </aside>
    </div>
  );
}
