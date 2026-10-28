import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  width?: string | number;
  align?: "left" | "right";
}

export interface DataTableProps<T> {
  columns: Array<Column<T>>;
  rows: T[];
  rowKey: (row: T, index: number) => string;
  empty?: EmptyStatePropsLike;
  footer?: ReactNode;
}

type EmptyStatePropsLike = { title: string; hint?: string; action?: ReactNode };

export function DataTable<T>({ columns, rows, rowKey, empty, footer }: DataTableProps<T>) {
  if (!rows.length && empty) {
    return (
      <div className="state-block">
        <strong>{empty.title}</strong>
        {empty.hint ? <p>{empty.hint}</p> : null}
        {empty.action}
      </div>
    );
  }
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} style={{ width: column.width, textAlign: column.align ?? "left" }}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={rowKey(row, index)}>
              {columns.map((column) => (
                <td key={column.key} data-wrap={column.align ? undefined : undefined}
                  style={{ textAlign: column.align ?? "left" }}>
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {footer}
    </div>
  );
}

export interface FilterBarProps {
  search?: {
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
    label: string;
  };
  selects?: Array<{
    label: string;
    value: string;
    onChange: (value: string) => void;
    options: Array<{ value: string; label: string }>;
  }>;
  children?: ReactNode;
}

export function FilterBar({ search, selects = [], children }: FilterBarProps) {
  return (
    <div className="join-course-toolbar">
      {search ? (
        <div className="join-course-search">
          <input type="search" className="field" value={search.value}
            placeholder={search.placeholder} aria-label={search.label}
            onChange={(event) => search.onChange(event.target.value)} />
        </div>
      ) : null}
      {selects.map((select) => (
        <label key={select.label} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12, fontWeight: 600 }}>
          {select.label}
          <select className="field" style={{ width: "auto", minWidth: 120 }} value={select.value}
            onChange={(event) => select.onChange(event.target.value)}>
            {select.options.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
      ))}
      {children}
    </div>
  );
}
