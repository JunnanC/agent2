/** 导出 CSV 处理清单（UTF-8 BOM，Excel 友好；不包含敏感内容） */
export function exportCsv(filename: string, rows: Array<Array<string | number | null | undefined>>): void {
  const escape = (value: string | number | null | undefined) => {
    const text = value == null ? "" : String(value);
    return `"${text.replace(/"/g, '""')}"`;
  };
  const csv = rows.map((row) => row.map(escape).join(",")).join("\r\n");
  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

/** 近 N 天的日期标签（MM/DD） */
export function lastDayLabels(days: number): string[] {
  const labels: string[] = [];
  for (let offset = -(days - 1); offset <= 0; offset += 1) {
    const date = new Date();
    date.setDate(date.getDate() + offset);
    labels.push(`${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")}`);
  }
  return labels;
}
