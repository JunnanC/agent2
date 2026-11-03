import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
export function DataTable({ columns, rows, rowKey, empty, footer }) {
    if (!rows.length && empty) {
        return (_jsxs("div", { className: "state-block", children: [_jsx("strong", { children: empty.title }), empty.hint ? _jsx("p", { children: empty.hint }) : null, empty.action] }));
    }
    return (_jsxs("div", { className: "table-wrap", children: [_jsxs("table", { className: "table", children: [_jsx("thead", { children: _jsx("tr", { children: columns.map((column) => (_jsx("th", { style: { width: column.width, textAlign: column.align ?? "left" }, children: column.header }, column.key))) }) }), _jsx("tbody", { children: rows.map((row, index) => (_jsx("tr", { children: columns.map((column) => (_jsx("td", { "data-wrap": column.align ? undefined : undefined, style: { textAlign: column.align ?? "left" }, children: column.render(row) }, column.key))) }, rowKey(row, index)))) })] }), footer] }));
}
export function FilterBar({ search, selects = [], children }) {
    return (_jsxs("div", { className: "join-course-toolbar", children: [search ? (_jsx("div", { className: "join-course-search", children: _jsx("input", { type: "search", className: "field", value: search.value, placeholder: search.placeholder, "aria-label": search.label, onChange: (event) => search.onChange(event.target.value) }) })) : null, selects.map((select) => (_jsxs("label", { style: { display: "flex", gap: 6, alignItems: "center", fontSize: 12, fontWeight: 600 }, children: [select.label, _jsx("select", { className: "field", style: { width: "auto", minWidth: 120 }, value: select.value, onChange: (event) => select.onChange(event.target.value), children: select.options.map((option) => (_jsx("option", { value: option.value, children: option.label }, option.value))) })] }, select.label))), children] }));
}
