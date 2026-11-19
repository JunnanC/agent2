import { useEffect, useRef, useState, type ReactNode } from "react";

export function Status({ value }: { value?: string }) {
  const labels: Record<string, string> = {
    ACTIVE: "正常",
    DISABLED: "已禁用",
    PUBLISHED: "已发布",
    PUBLISHING: "发布中",
    DRAFT: "草稿",
    PRECHECKING: "预检中",
    PRECHECK_PASSED: "预检通过",
    PRECHECK_FAILED: "预检失败",
    CLOSED: "已关闭",
    ARCHIVED: "已归档",
    APPROVED: "已批准",
    RETIRED: "已停用",
    REJECTED: "已拒绝",
    PENDING: "待处理",
    PENDING_APPROVAL: "待审批",
    READY: "就绪",
    QUEUED: "排队中",
    RETRY: "重试中",
    PASSED: "通过",
    CLEAN: "扫描通过",
    INFECTED: "扫描未通过",
    FAILED: "失败",
    EXPIRED: "已过期",
    CANCELLED: "已取消",
    HEALTHY: "正常",
    DEGRADED: "降级",
    UNHEALTHY: "异常",
    UNKNOWN: "未知",
    SUCCESS: "成功",
    SUCCEEDED: "成功",
    DENIED: "未执行",
    RUNNING: "运行中",
    ENABLED: "已启用",
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
  emptyText = "没有匹配的记录，请调整搜索或筛选条件",
  className,
}: {
  headings: string[];
  children: ReactNode;
  empty?: boolean;
  emptyText?: string;
  className?: string;
}) {
  return (
    <div className="table-wrap">
      <table className={className}>
        <thead>
          <tr>
            {headings.map((h) => (
              <th
                key={h}
                className={/人数|数量|CPU|内存|磁盘/.test(h) ? "num" : undefined}
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
                {emptyText}
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

type ListState = { search: string; filter: string; page: number };

function loadListState(storageKey: string | undefined, initialFilter: string): ListState {
  if (!storageKey) return { search: "", filter: initialFilter, page: 1 };
  try {
    const raw = window.sessionStorage.getItem(storageKey);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<ListState>;
      return {
        search: typeof parsed.search === "string" ? parsed.search : "",
        filter: typeof parsed.filter === "string" ? parsed.filter : initialFilter,
        page: typeof parsed.page === "number" && parsed.page > 0 ? parsed.page : 1,
      };
    }
  } catch {
    // A disabled or full session store must not break the list.
  }
  return { search: "", filter: initialFilter, page: 1 };
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
  initialState = "",
  storageKey,
  tableClassName,
  reserveRows,
}: {
  rows: T[];
  text: (row: T) => string;
  states?: [string, string][];
  state?: (row: T) => string;
  placeholder: string;
  headings: string[];
  render: (row: T) => ReactNode;
  extra?: ReactNode;
  initialState?: string;
  storageKey?: string;
  tableClassName?: string;
  reserveRows?: boolean;
}) {
  const [restored] = useState(() => loadListState(storageKey, initialState));
  const [search, setSearch] = useState(restored.search),
    [filter, setFilter] = useState(restored.filter),
    [page, setPage] = useState(restored.page);
  useEffect(() => {
    if (!storageKey) return;
    try {
      window.sessionStorage.setItem(storageKey, JSON.stringify({ search, filter, page }));
    } catch {
      // Persistence is a convenience; pagination still works without it.
    }
  }, [filter, page, search, storageKey]);
  const filtered = rows.filter(
    (row) =>
      text(row).toLowerCase().includes(search.trim().toLowerCase()) &&
      (!filter || state?.(row) === filter),
  );
  const count = Math.max(1, Math.ceil(filtered.length / 8)),
    active = Math.min(page, count);
  const pageRows = filtered.slice((active - 1) * 8, active * 8);
  const fillers = reserveRows && filtered.length > 8 ? Math.max(0, 8 - pageRows.length) : 0;
  return (
    <section className="console-list">
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
      <Table headings={headings} empty={!filtered.length} className={tableClassName}>
        {pageRows.map(render)}
        {Array.from({ length: fillers }, (_, index) => (
          <tr key={`reserve-${index}`} className="reserve-row" aria-hidden="true">
            <td colSpan={headings.length} />
          </tr>
        ))}
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
    </section>
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
