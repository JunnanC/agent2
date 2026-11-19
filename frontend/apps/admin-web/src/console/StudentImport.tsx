import { useRef, useState } from "react";
import { platformApi, type StudentImportRow } from "@edu/api-client";
import { newIdempotencyKey } from "@edu/auth-client";

const ERROR_TEXT: Record<string, string> = {
  duplicate_identifier: "学号或用户名已存在",
  ACCOUNT_ALREADY_EXISTS: "邮箱或用户名已存在",
  PASSWORD_INVALID: "初始密码不符合强度要求",
};

export function StudentImport({ onComplete }: { onComplete: () => void }) {
  const [csv, setCsv] = useState("");
  const [fileName, setFileName] = useState("");
  const [rows, setRows] = useState<StudentImportRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const key = useRef<string | null>(null);

  async function submit() {
    setBusy(true);
    setError("");
    key.current ??= newIdempotencyKey();
    try {
      const result = await platformApi.importStudents(csv, key.current);
      setRows(result.rows);
      setCsv("");
      setFileName("");
      key.current = null;
      onComplete();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "导入失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  const created = rows.filter((row) => row.status === "CREATED").length;
  const failed = rows.filter((row) => row.status === "FAILED").length;

  function downloadTemplate() {
    const csvTemplate = "student_number,email,display_name,password\n";
    const url = URL.createObjectURL(new Blob([`\ufeff${csvTemplate}`], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "学生账号导入模板.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  return <details className="panel student-import">
    <summary><strong>批量创建学生账号</strong></summary>
    <div className="student-import-body">
      <div className="student-import-actions">
        <input
          id="student-import-file"
          className="student-import-file"
          type="file"
          accept=".csv,text/csv"
          aria-label="学生账号 CSV"
          disabled={busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            if (file.size > 1024 * 1024) {
              setError("文件不能超过 1 MiB");
              return;
            }
            void file.text().then((text) => {
              setCsv(text);
              setFileName(file.name);
              setRows([]);
              key.current = null;
              setError("");
            }, () => setError("文件读取失败"));
            event.target.value = "";
          }}
        />
        <label className="btn student-import-picker" htmlFor="student-import-file">选择 CSV 文件</label>
        <span className="student-import-filename">{fileName || "未选择文件"}</span>
        <button type="button" className="link student-import-template" onClick={downloadTemplate}>下载 CSV 模板</button>
        <button className="btn primary student-import-submit" disabled={busy || !csv} onClick={() => void submit()}>
          {busy ? "正在导入…" : "创建学生账号"}
        </button>
      </div>
      {csv && <p className="student-import-hint" role="status">已读取 <strong>{fileName}</strong>，可以开始导入。</p>}
      {error && <p className="student-import-error" role="alert">{error}</p>}
      {rows.length > 0 && <div className="student-import-result">
        <p role="status">已创建 <strong>{created}</strong> 个账号，失败 <strong>{failed}</strong> 行。</p>
        <div className="table-wrap">
          <table>
            <thead><tr><th>CSV 行</th><th>学号</th><th>结果</th></tr></thead>
            <tbody>{rows.map((row) => <tr key={row.row_number}>
              <td>{row.row_number}</td>
              <td className="mono">{row.student_number}</td>
              <td>{row.status === "CREATED" ? "已创建" : ERROR_TEXT[row.error ?? ""] || "该行信息无效，请核对学号、邮箱和密码"}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </div>}
    </div>
  </details>;
}
