import { useRef, useState } from "react";
import { platformApi, type StudentImportRow } from "@edu/api-client";
import { newIdempotencyKey } from "@edu/auth-client";

export function StudentImport({ onComplete }: { onComplete: () => void }) {
  const [csv, setCsv] = useState("");
  const [rows, setRows] = useState<StudentImportRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const key = useRef<string | null>(null);
  async function submit() {
    setBusy(true); setError(""); key.current ??= newIdempotencyKey();
    try {
      const result = await platformApi.importStudents(csv, key.current);
      setRows(result.rows); setCsv(""); key.current = null; onComplete();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "导入失败，请重试"); }
    finally { setBusy(false); }
  }
  return <details className="panel"><summary>按学号批量创建学生账号</summary>
    <p>上传 UTF-8 CSV，最多 500 行。表头：student_number,email,display_name,password。学号 3–32 位，全站唯一；邮箱必填，初始密码至少 12 位且包含字母和非字母字符。已有账号不会被覆盖。</p>
    <label>学生账号 CSV<input type="file" accept=".csv,text/csv" disabled={busy} onChange={(event) => {
      const file = event.target.files?.[0]; if (!file) return;
      if (file.size > 1024 * 1024) { setError("文件不能超过 1 MiB"); return; }
      void file.text().then((text) => { setCsv(text); setRows([]); key.current = null; setError(""); }, () => setError("文件读取失败"));
      event.target.value = "";
    }} /></label>
    {csv && <p role="status">文件已读取，可提交导入。</p>}
    <button className="btn" disabled={busy || !csv} onClick={() => void submit()}>{busy ? "正在导入…" : "创建学生账号"}</button>
    {error && <p role="alert">{error}</p>}
    {rows.length > 0 && <><p role="status">创建 {rows.filter((row) => row.status === "CREATED").length} 个，失败 {rows.filter((row) => row.status === "FAILED").length} 行</p><table><thead><tr><th>CSV 行</th><th>学号</th><th>结果</th></tr></thead><tbody>{rows.map((row) => <tr key={row.row_number}><td>{row.row_number}</td><td>{row.student_number}</td><td>{row.status === "CREATED" ? "已创建" : ({ duplicate_identifier: "学号或用户名已存在", ACCOUNT_ALREADY_EXISTS: "邮箱或用户名已存在", PASSWORD_INVALID: "初始密码不符合强度要求" } as Record<string, string>)[row.error ?? ""] || "该行信息无效，请核对学号、邮箱和密码"}</td></tr>)}</tbody></table></>}
  </details>;
}
