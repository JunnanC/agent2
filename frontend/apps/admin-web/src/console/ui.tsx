import { useEffect, useRef, useState, type ReactNode } from "react";

export function Status({ value }: { value?: string }) {
  const labels: Record<string, string> = {
    ACTIVE: "正常",
    DISABLED: "已禁用",
    PUBLISHED: "进行中",
    DRAFT: "草稿",
    CLOSED: "已结束",
    ARCHIVED: "已归档",
    APPROVED: "启用",
    RETIRED: "停用",
    REJECTED: "未启用",
    PENDING: "待就绪",
    CLEAN: "扫描通过",
    INFECTED: "扫描未通过",
    FAILED: "失败",
    HEALTHY: "正常",
    UNHEALTHY: "异常",
    UNKNOWN: "未知",
    SUCCESS: "成功",
    DENIED: "未执行",
    RUNNING: "运行中",
    ENABLED: "启用",
    AVAILABLE: "正常",
    UNAVAILABLE: "不可用",
    DESTROYED: "已销毁",
    PROVISIONING: "创建中",
  };
  const bad = [
    "DISABLED",
    "UNHEALTHY",
    "UNAVAILABLE",
    "FAILED",
    "INFECTED",
    "DENIED",
  ].includes(value ?? "");
  return (
    <span
      className={`status ${bad ? "bad" : ["UNKNOWN", "RETIRED", "REJECTED", "ARCHIVED", "CLOSED"].includes(value ?? "") || !value ? "off" : ""}`}
    >
      {value ? (labels[value] ?? value) : "未提供"}
    </span>
  );
}

export function Table({
  headings,
  children,
  empty,
}: {
  headings: string[];
  children: ReactNode;
  empty?: boolean;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {headings.map((h) => (
              <th
                key={h}
                className={/人数|数量|CPU|内存/.test(h) ? "num" : undefined}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {empty ? (
            <tr>
              <td colSpan={headings.length} className="empty">
                没有匹配的记录，请调整搜索或筛选条件
              </td>
            </tr>
          ) : (
            children
          )}
        </tbody>
      </table>
    </div>
  );
}

export function List<T>({
  rows,
  text,
  states,
  state,
  placeholder,
  headings,
  render,
  extra,
}: {
  rows: T[];
  text: (row: T) => string;
  states?: [string, string][];
  state?: (row: T) => string;
  placeholder: string;
  headings: string[];
  render: (row: T) => ReactNode;
  extra?: ReactNode;
}) {
  const [search, setSearch] = useState(""),
    [filter, setFilter] = useState(""),
    [page, setPage] = useState(1);
  const filtered = rows.filter(
    (row) =>
      text(row).toLowerCase().includes(search.trim().toLowerCase()) &&
      (!filter || state?.(row) === filter),
  );
  const count = Math.max(1, Math.ceil(filtered.length / 8)),
    active = Math.min(page, count);
  return (
    <>
      <div className="toolbar">
        <input
          type="search"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          placeholder={placeholder}
          aria-label={placeholder}
        />
        {states && (
          <select
            aria-label="状态或操作筛选"
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setPage(1);
            }}
          >
            <option value="">全部</option>
            {states.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        )}
        {extra}
        <span className="count">{filtered.length} 条记录</span>
      </div>
      <Table headings={headings} empty={!filtered.length}>
        {filtered.slice((active - 1) * 8, active * 8).map(render)}
      </Table>
      <div className="pagination">
        <span>共 {filtered.length} 条 · 每页 8 条</span>
        <div>
          <button disabled={active <= 1} onClick={() => setPage(active - 1)}>
            上一页
          </button>
          <span>
            {active} / {count}
          </span>
          <button
            disabled={active >= count}
            onClick={() => setPage(active + 1)}
          >
            下一页
          </button>
        </div>
      </div>
    </>
  );
}

export function Modal({
  title,
  children,
  onClose,
  wide = false,
  busy = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
  busy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    // Native dialog handles Escape via onCancel and has an explicit close button; this click only dismisses the backdrop.
    // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions
    <dialog
      ref={ref}
      className={wide ? "detail" : undefined}
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onClose();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) {
          const r = e.currentTarget.getBoundingClientRect();
          if (
            e.clientX < r.left ||
            e.clientX > r.right ||
            e.clientY < r.top ||
            e.clientY > r.bottom
          )
            onClose();
        }
      }}
    >
      <div className="dialog-body">
        <div className="dialog-head">
          <h2>{title}</h2>
          <button
            type="button"
            aria-label="关闭弹窗"
            disabled={busy}
            onClick={onClose}
          >
            ×
          </button>
        </div>
        {children}
      </div>
    </dialog>
  );
}

export function Fields({ values }: { values: [string, ReactNode][] }) {
  return (
    <dl className="detail-grid">
      {values.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}
export function ErrorState({
  error,
  retry,
}: {
  error: unknown;
  retry: () => void;
}) {
  return (
    <div className="empty" role="alert">
      <p>{error instanceof Error ? error.message : "数据加载失败"}</p>
      <button onClick={retry}>重新加载</button>
    </div>
  );
}
export function Meter({
  label,
  percent,
  caption,
}: {
  label: string;
  percent: number | null;
  caption?: string;
}) {
  return (
    <div className="resource-line">
      <div>
        <span>{label}</span>
        <span className="mono">
          {percent == null ? "未提供" : `${percent}%`}
        </span>
      </div>
      <div
        className={`bar ${percent != null && percent > 80 ? "warning" : ""}`}
      >
        <i style={{ width: `${percent ?? 0}%` }} />
      </div>
      <span className="muted">{caption}</span>
    </div>
  );
}
