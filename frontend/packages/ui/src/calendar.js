import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useState } from "react";
import { Icon } from "./icons";
import { StatusBadge } from "./primitives";
function toKey(date) {
    const parsed = new Date(date.length === 10 ? `${date}T12:00:00` : date);
    if (Number.isNaN(parsed.getTime()))
        return "";
    const month = String(parsed.getMonth() + 1).padStart(2, "0");
    const day = String(parsed.getDate()).padStart(2, "0");
    return `${parsed.getFullYear()}-${month}-${day}`;
}
const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];
function dateLabel(date) {
    const parsed = new Date(`${date}T12:00:00`);
    const weekday = WEEKDAYS[(parsed.getDay() + 6) % 7];
    return `${date.slice(5, 7)} 月 ${date.slice(8, 10)} 日（周${weekday}）`;
}
export function DateCalendar({ items, title = "日历", selectedDate: controlledDate, onDateSelect, showPopover = true }) {
    const [cursor, setCursor] = useState(() => {
        const now = new Date();
        return new Date(now.getFullYear(), now.getMonth(), 1);
    });
    const [internalSelectedDate, setInternalSelectedDate] = useState(null);
    const selectedDate = controlledDate === undefined ? internalSelectedDate : controlledDate;
    const groups = new Map();
    for (const item of items) {
        const key = toKey(item.date);
        if (!key)
            continue;
        const bucket = groups.get(key) ?? [];
        bucket.push(item);
        groups.set(key, bucket);
    }
    const year = cursor.getFullYear();
    const month = cursor.getMonth();
    const firstDay = (new Date(year, month, 1).getDay() + 6) % 7;
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const todayKey = toKey(new Date().toISOString());
    const cells = [];
    for (let index = 0; index < firstDay; index += 1) {
        cells.push(_jsx("div", { className: "calendar-day empty", "aria-hidden": "true" }, `empty-${index}`));
    }
    for (let day = 1; day <= daysInMonth; day += 1) {
        const key = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
        const count = groups.get(key)?.length ?? 0;
        const isSelected = key === selectedDate;
        cells.push(_jsxs("button", { type: "button", className: `calendar-day${isSelected ? " selected" : ""}${key === todayKey ? " today" : ""}`, "aria-pressed": isSelected, "aria-label": `${dateLabel(key)}，${count ? `${count} 项待办任务` : "无待办任务"}`, onClick: () => {
                const nextDate = isSelected ? null : key;
                setInternalSelectedDate(nextDate);
                onDateSelect?.(nextDate);
            }, children: [_jsx("span", { className: "calendar-day-number", children: day }), count ? _jsx("span", { className: "calendar-count", children: count }) : null] }, key));
    }
    const selectedItems = selectedDate ? groups.get(selectedDate) ?? [] : [];
    return (_jsxs("div", { className: "calendar-shell", children: [_jsxs("div", { className: "calendar-main", children: [_jsxs("div", { className: "calendar-month-nav", style: { display: "flex", alignItems: "center", gap: 8, justifyContent: "flex-end", paddingBottom: 4 }, children: [_jsx("button", { type: "button", className: "icon-btn sm", "aria-label": "\u4E0A\u4E2A\u6708", onClick: () => setCursor(new Date(year, month - 1, 1)), children: _jsx(Icon, { name: "chevron-left", size: 14 }) }), _jsxs("strong", { style: { fontSize: 13 }, children: [year, " \u5E74 ", month + 1, " \u6708"] }), _jsx("button", { type: "button", className: "icon-btn sm", "aria-label": "\u4E0B\u4E2A\u6708", onClick: () => setCursor(new Date(year, month + 1, 1)), children: _jsx(Icon, { name: "chevron-right", size: 14 }) })] }), _jsx("div", { className: "calendar-weekdays", children: WEEKDAYS.map((label) => _jsx("span", { children: label }, label)) }), _jsx("div", { className: "calendar-grid", role: "grid", "aria-label": title, children: cells })] }), showPopover ? _jsx("div", { className: "calendar-popover", hidden: !selectedDate || !selectedItems.length, "aria-live": "polite", children: selectedDate ? (_jsxs(_Fragment, { children: [_jsxs("div", { className: "calendar-popover-head", children: [_jsxs("div", { children: [_jsx("span", { className: "eyebrow", children: dateLabel(selectedDate) }), _jsxs("strong", { style: { display: "block" }, children: [selectedItems.length, " \u9879\u4EFB\u52A1"] })] }), _jsx("button", { type: "button", className: "icon-btn sm", "aria-label": "\u5173\u95ED\u4EFB\u52A1\u6D6E\u5C42", onClick: () => {
                                        setInternalSelectedDate(null);
                                        onDateSelect?.(null);
                                    }, children: _jsx(Icon, { name: "x", size: 14 }) })] }), _jsx("div", { children: selectedItems.map((item, index) => (_jsxs("button", { type: "button", className: "calendar-task", onClick: item.onClick, children: [_jsxs("span", { className: "calendar-task-copy", children: [_jsx("strong", { children: item.title }), _jsx("small", { children: item.subtitle })] }), _jsxs("span", { className: "calendar-task-meta", children: [item.statusLabel ? _jsx(StatusBadge, { tone: item.statusTone ?? "neutral", children: item.statusLabel }) : null, _jsx(Icon, { name: "chevron-right", size: 13 })] })] }, `${item.title}-${index}`))) })] })) : null }) : null] }));
}
