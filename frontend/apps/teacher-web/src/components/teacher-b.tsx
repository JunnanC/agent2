import { useEffect, useId, useRef, type ReactNode } from "react";

const paths = {
  brand: "M12 6c-3-2-6-2.5-10-2v14c4-.5 7 0 10 2 3-2 6-2.5 10-2V4c-4-.5-7 0-10 2Zm0 0v14M5.5 8l3 .8m7 .1 3-.8",
  bell: "M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9m-8 12a2 2 0 0 0 4 0",
  left: "m15 18-6-6 6-6",
  right: "m9 18 6-6-6-6",
  close: "m6 6 12 12M18 6 6 18",
  plus: "M12 5v14M5 12h14",
  upload: "M12 16V4m-4 4 4-4 4 4M4 16v4h16v-4",
  calendar: "M7 3v4m10-4v4M3 10h18m-13 4h2m4 0h2",
  flask: "M9 3h6m-5 0v7l-6 8a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3l-6-8V3M7 15h10",
  users: "M4 20v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2m1-15a3 3 0 0 1 0 6m1 3a4 4 0 0 1 3 4v2",
  chart: "M4 4v16h16M9 15v-3m5 3V8m5 7V5",
  terminal: "m7 9 3 3-3 3m6 0h4",
  copy: "M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2",
};

export type TeacherIconName = keyof typeof paths;

export function TeacherIcon({ name }: { name: TeacherIconName }) {
  return <svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {name === "calendar" && <rect x="3" y="5" width="18" height="16" rx="2" />}
    {name === "terminal" && <rect x="3" y="4" width="18" height="16" rx="2" />}
    {name === "users" && <circle cx="10" cy="8" r="3" />}
    {name === "copy" && <rect x="8" y="8" width="12" height="12" rx="2" />}
    <path d={paths[name]} />
  </svg>;
}

export function TeacherScrollFrame({ label, children }: { label: string; children: ReactNode }) {
  // Keyboard users can focus and scroll wide tables and timetables.
  // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
  return <div className="scroll-frame" role="region" tabIndex={0} aria-label={label}>{children}</div>;
}

export function TeacherDialog({ title, onClose, children, actions, busy = false }: {
  title: string; onClose: () => void; children: ReactNode; actions?: ReactNode; busy?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const element = dialog.current;
    const trigger = document.activeElement;
    element?.showModal?.();
    return () => {
      element?.close?.();
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus();
    };
  }, []);
  // The native dialog handles keyboard focus and Escape. The pointer handler closes its backdrop.
  /* eslint-disable jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions */
  return <dialog ref={dialog} aria-labelledby={id}
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}
    onClick={(event) => { if (event.target === event.currentTarget) {
      const { left, right, top, bottom } = event.currentTarget.getBoundingClientRect();
      if (!busy && (event.clientX < left || event.clientX > right || event.clientY < top || event.clientY > bottom)) onClose();
    } }}>
    <div className="dialog-head"><h2 id={id}>{title}</h2>
      <button type="button" className="btn square" aria-label="关闭" disabled={busy} onClick={onClose}><TeacherIcon name="close" /></button>
    </div>
    <div className="dialog-body">{children}{actions && <div className="actions">{actions}</div>}</div>
  </dialog>;
  /* eslint-enable jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions */
}
