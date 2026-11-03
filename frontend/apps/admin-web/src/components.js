import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useRef, useState } from 'react';
import { filterRows, toCsv } from './data';
export function Badge({ value }) {
    const green = ['成功', '健康', '启用', '扫描通过', '已批准'];
    const red = ['高', '待处理', '失败', '扫描失败', '回收失败', '已阻止'];
    const blue = ['低', '处理中', '运行中'];
    const tone = green.includes(value) ? 'green' : red.includes(value) ? 'red' : blue.includes(value) ? 'blue' : value === '空闲' ? 'gray' : 'amber';
    return _jsx("span", { className: `pill ${tone}`, children: value });
}
export function Panel({ title, extra, children, className = '' }) {
    return _jsxs("section", { className: `panel ${className}`, children: [_jsxs("div", { className: "panel-head", children: [_jsx("h2", { children: title }), extra] }), children] });
}
export function Metrics({ items }) {
    return _jsx("div", { className: "metrics", children: items.map(item => {
            const content = _jsxs(_Fragment, { children: [_jsx("span", { className: "metric-label", children: item.label }), _jsx("span", { className: "metric-value", children: item.value }), _jsx("span", { className: "metric-foot", children: item.foot })] });
            return item.onClick ? _jsx("button", { className: "metric", onClick: item.onClick, children: content }, item.label) : _jsx("div", { className: "metric", children: content }, item.label);
        }) });
}
export function DataTable({ headers, rows, badgeColumns = [], statuses = [], timeFilter = false, exportable = false, onDetail }) {
    const [query, setQuery] = useState('');
    const [status, setStatus] = useState('all');
    const [days, setDays] = useState(7);
    const visible = filterRows(rows, query, status, timeFilter ? days : 0);
    function exportCurrent() {
        const url = URL.createObjectURL(new Blob([toCsv(headers, visible.map(row => row.cells))], { type: 'text/csv;charset=utf-8' }));
        const link = document.createElement('a');
        link.href = url;
        link.download = 'audit-demo.csv';
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    return _jsxs("section", { className: "panel", children: [_jsxs("div", { className: "toolbar", children: [_jsx("input", { className: "search", value: query, onChange: event => setQuery(event.target.value), placeholder: "\u641C\u7D22\u540D\u79F0\u3001\u5BF9\u8C61 ID \u6216 Trace ID", "aria-label": "\u641C\u7D22\u8BB0\u5F55" }), statuses.length > 0 && _jsxs("select", { className: "select", "aria-label": "\u7B5B\u9009\u72B6\u6001", value: status, onChange: event => setStatus(event.target.value), children: [_jsx("option", { value: "all", children: "\u5168\u90E8\u72B6\u6001" }), statuses.map(value => _jsx("option", { children: value }, value))] }), timeFilter && _jsxs("select", { className: "select", "aria-label": "\u7B5B\u9009\u65F6\u95F4", value: days, onChange: event => setDays(Number(event.target.value)), children: [_jsx("option", { value: 7, children: "\u6700\u8FD1 7 \u5929" }), _jsx("option", { value: 1, children: "\u4ECA\u5929" }), _jsx("option", { value: 30, children: "\u6700\u8FD1 30 \u5929" })] }), exportable && _jsx("button", { className: "btn", onClick: exportCurrent, children: "\u5BFC\u51FA\u5F53\u524D\u8BB0\u5F55" }), _jsxs("span", { className: "toolbar-end", role: "status", children: [visible.length, " \u6761\u8BB0\u5F55 \u00B7 \u6F14\u793A\u6570\u636E"] })] }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { children: [_jsx("thead", { children: _jsxs("tr", { children: [headers.map(header => _jsx("th", { children: header }, header)), _jsx("th", { children: _jsx("span", { className: "sr-only", children: "\u64CD\u4F5C" }) })] }) }), _jsxs("tbody", { children: [visible.map(row => _jsxs("tr", { children: [row.cells.map((value, index) => _jsx("td", { className: index === 0 ? 'object-cell' : '', children: badgeColumns.includes(index) ? _jsx(Badge, { value: value }) : value }, index)), _jsx("td", { children: _jsx("button", { className: "row-action", onClick: () => onDetail({ title: row.cells[0] ?? '', fields: [['记录 ID', row.id], ...headers.map((header, index) => [header, row.cells[index] ?? ''])] }), children: "\u67E5\u770B\u8BE6\u60C5 \u2192" }) })] }, row.id)), visible.length === 0 && _jsx("tr", { children: _jsx("td", { colSpan: headers.length + 1, className: "empty-state", children: "\u6CA1\u6709\u5339\u914D\u8BB0\u5F55\uFF0C\u8BF7\u8C03\u6574\u641C\u7D22\u6216\u7B5B\u9009\u6761\u4EF6\u3002" }) })] })] }) })] });
}
export function DetailDrawer({ detail, onClose }) {
    const dialog = useRef(null);
    useEffect(() => {
        const target = dialog.current;
        const previous = document.activeElement;
        target.showModal();
        return () => { target.close(); previous?.focus(); };
    }, []);
    return _jsx("dialog", { ref: dialog, className: "detail-dialog", "aria-labelledby": "drawerTitle", onCancel: onClose, onClick: event => { if (event.target === event.currentTarget)
            onClose(); }, children: _jsxs("div", { className: "drawer-content", children: [_jsxs("div", { className: "drawer-head", children: [_jsxs("div", { children: [_jsx("h2", { id: "drawerTitle", children: detail.title }), _jsx("p", { children: "\u5E73\u53F0\u7BA1\u7406\u8BB0\u5F55 \u00B7 \u6F14\u793A\u6570\u636E" })] }), _jsx("button", { className: "icon-button", onClick: onClose, "aria-label": "\u5173\u95ED\u8BE6\u60C5", children: "\u00D7" })] }), _jsxs("div", { className: "drawer-section", children: [_jsx("h3", { children: "\u5BF9\u8C61\u4FE1\u606F" }), detail.fields.map(([label, value]) => _jsxs("div", { className: "detail-line", children: [_jsx("span", { children: label }), _jsx("strong", { children: value })] }, label))] }), _jsxs("div", { className: "drawer-section", children: [_jsx("h3", { children: "\u5904\u7406\u8BF4\u660E" }), _jsx("p", { className: "detail-description", children: "\u6B64\u754C\u9762\u5C55\u793A\u6F14\u793A\u8BB0\u5F55\u3002\u6B63\u5F0F\u63A5\u5165\u540E\u6839\u636E\u670D\u52A1\u7AEF\u6743\u9650\u3001\u5141\u8BB8\u64CD\u4F5C\u548C\u963B\u585E\u539F\u56E0\u63D0\u4F9B\u5904\u7406\u5165\u53E3\u3002" })] }), _jsx("div", { className: "drawer-actions", children: _jsx("button", { className: "btn", onClick: onClose, children: "\u5173\u95ED" }) })] }) });
}
