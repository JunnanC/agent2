import { useState } from "react";
import { Icon } from "./icons";
import { StatusBadge } from "./primitives";

function toKey(date: string): string {
  const parsed = new Date(date.length === 10 ? `${date}T12:00:00` : date);
  if (Number.isNaN(parsed.getTime())) return "";
  const month = String(parsed.getMonth() + 1).padStart(2, "0");
  const day = String(parsed.getDate()).padStart(2, "0");
  return `${parsed.getFullYear()}-${month}-${day}`;
}

const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];

function dateLabel(date: string): string {
  const parsed = new Date(`${date}T12:00:00`);
  const weekday = WEEKDAYS[(parsed.getDay() + 6) % 7];
  return `${date.slice(5, 7)} 月 ${date.slice(8, 10)} 日（周${weekday}）`;
}

export interface CalendarItem {
  date: string;
  title: string;
  subtitle?: string;
  statusLabel?: string;
  statusTone?: "good" | "warn" | "blue" | "bad" | "neutral";
  onClick?: () => void;
}

export interface DateCalendarProps {
  items: CalendarItem[];
  title?: string;
}

export function DateCalendar({ items, title = "日历" }: DateCalendarProps) {
  const [cursor, setCursor] = useState(() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1);
  });
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  const groups = new Map<string, CalendarItem[]>();
  for (const item of items) {
    const key = toKey(item.date);
    if (!key) continue;
    const bucket = groups.get(key) ?? [];
    bucket.push(item);
    groups.set(key, bucket);
  }

  const year = cursor.getFullYear();
  const month = cursor.getMonth();
  const firstDay = (new Date(year, month, 1).getDay() + 6) % 7;
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const todayKey = toKey(new Date().toISOString());

  const cells: React.ReactNode[] = [];
  for (let index = 0; index < firstDay; index += 1) {
    cells.push(<div key={`empty-${index}`} className="calendar-day empty" aria-hidden="true" />);
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    const key = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const count = groups.get(key)?.length ?? 0;
    const isSelected = key === selectedDate;
    cells.push(
      <button key={key} type="button"
        className={`calendar-day${isSelected ? " selected" : ""}${key === todayKey ? " today" : ""}`}
        aria-pressed={isSelected}
        aria-label={`${dateLabel(key)}，${count ? `${count} 项任务到期` : "无任务到期"}`}
        onClick={() => setSelectedDate(isSelected ? null : key)}>
        <span className="calendar-day-number">{day}</span>
        {count ? <span className="calendar-count">{count}</span> : null}
      </button>,
    );
  }

  const selectedItems = selectedDate ? groups.get(selectedDate) ?? [] : [];

  return (
    <div className="calendar-shell">
      <div className="calendar-main">
        <div className="calendar-month-nav" style={{ display: "flex", alignItems: "center", gap: 8, justifyContent: "flex-end", paddingBottom: 4 }}>
          <button type="button" className="icon-btn sm" aria-label="上个月"
            onClick={() => setCursor(new Date(year, month - 1, 1))}><Icon name="chevron-left" size={14} /></button>
          <strong style={{ fontSize: 13 }}>{year} 年 {month + 1} 月</strong>
          <button type="button" className="icon-btn sm" aria-label="下个月"
            onClick={() => setCursor(new Date(year, month + 1, 1))}><Icon name="chevron-right" size={14} /></button>
        </div>
        <div className="calendar-weekdays">{WEEKDAYS.map((label) => <span key={label}>{label}</span>)}</div>
        <div className="calendar-grid" role="grid" aria-label={title}>{cells}</div>
      </div>
      <div className="calendar-popover" hidden={!selectedDate || !selectedItems.length} aria-live="polite">
        {selectedDate ? (
          <>
            <div className="calendar-popover-head">
              <div>
                <span className="eyebrow">{dateLabel(selectedDate)}</span>
                <strong style={{ display: "block" }}>{selectedItems.length} 项任务</strong>
              </div>
              <button type="button" className="icon-btn sm" aria-label="关闭任务浮层"
                onClick={() => setSelectedDate(null)}>
                <Icon name="x" size={14} />
              </button>
            </div>
            <div>
              {selectedItems.map((item, index) => (
                <button key={`${item.title}-${index}`} type="button" className="calendar-task" onClick={item.onClick}>
                  <span className="calendar-task-copy">
                    <strong>{item.title}</strong>
                    <small>{item.subtitle}</small>
                  </span>
                  <span className="calendar-task-meta">
                    {item.statusLabel ? <StatusBadge tone={item.statusTone ?? "neutral"}>{item.statusLabel}</StatusBadge> : null}
                    <Icon name="chevron-right" size={13} />
                  </span>
                </button>
              ))}
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
