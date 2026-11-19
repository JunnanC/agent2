import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { assessmentPartLabel, assessmentPartsApi, fileApi } from "@edu/api-client";
import type { AssessmentPart } from "@edu/api-client";
import { EmptyState, Panel, StatusBadge, useToast } from "@edu/ui";
import { formatDateTime } from "@/lib/format";
import "./assessment-reviews.css";

export const partStatus: Record<string, string> = {
  NOT_SUBMITTED: "未提交", IN_PROGRESS: "进行中", SUBMITTED: "已提交", GRADED: "已评分", RETURNED: "待补做",
};

export function AssessmentReportReview({
  courseId, publicationId, initialTaskId,
}: { courseId: string; publicationId: string; initialTaskId: string }) {
  const [taskId, setTaskId] = useState(initialTaskId);
  const [search, setSearch] = useState("");
  const reports = useQuery({
    queryKey: ["assessment-report-queue", courseId, publicationId],
    queryFn: () => assessmentPartsApi.reports(courseId, publicationId),
  });
  const rows = (reports.data ?? []).filter((row) =>
    `${row.student_name} ${row.title}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
  );
  return <div className="assessment-review-workspace">
    <aside className="assessment-review-queue" aria-label="报告列表">
      <section className="assessment-review-queue-panel">
        <h2>学生报告</h2>
        <input className="field" type="search" aria-label="搜索实验报告" placeholder="搜索学生或实验"
          value={search} onChange={(event) => setSearch(event.target.value)} />
        {reports.isPending && <p role="status">正在载入报告…</p>}
        {reports.isError && <p role="alert">报告列表载入失败。 <button className="btn sm" onClick={() => void reports.refetch()}>重试</button></p>}
        {reports.isSuccess && !rows.length && <EmptyState title={search ? "没有匹配的报告" : "暂无已提交报告"} />}
        <div className="assessment-review-queue-list">
          {rows.map((row) => <button className={`assessment-review-queue-row${taskId === row.task_id ? " active" : ""}`}
            type="button" key={row.task_id} aria-pressed={taskId === row.task_id} onClick={() => setTaskId(row.task_id)}>
            <span className="assessment-review-queue-student">{row.student_name}</span>
            <strong>{row.title}</strong>
            <small>{partStatus[row.status]} · {formatDateTime(row.submitted_at)}</small>
          </button>)}
        </div>
      </section>
    </aside>
    {taskId
      ? <ReportDetail key={taskId} courseId={courseId} taskId={taskId} />
      : <Panel><EmptyState title="选择一份实验报告" /></Panel>}
  </div>;
}

function ReportDetail({ courseId, taskId }: { courseId: string; taskId: string }) {
  const toast = useToast();
  const client = useQueryClient();
  const parts = useQuery({
    queryKey: ["assessment-parts", courseId, taskId],
    queryFn: () => assessmentPartsApi.parts(courseId, taskId),
  });
  const reportPart = parts.data?.parts.find((part) => part.kind === "REPORT");
  const report = useQuery({
    queryKey: ["assessment-report-review", courseId, taskId],
    queryFn: () => assessmentPartsApi.report(courseId, taskId),
    enabled: Boolean(reportPart && reportPart.status !== "NOT_SUBMITTED"),
  });
  const [score, setScore] = useState("");
  const [feedback, setFeedback] = useState("");
  const [part, setPart] = useState<AssessmentPart["kind"] | "">("");
  const [deadline, setDeadline] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const data = report.data;
  const eligible = (parts.data?.parts ?? []).filter((item) =>
    item.kind !== "PROGRAMMING" || item.status !== "SUBMITTED",
  );

  async function save(action: "grade" | "redo") {
    setBusy(true);
    try {
      if (action === "grade" && data?.row_version != null) {
        await assessmentPartsApi.gradeReport(courseId, taskId, score, feedback, data.row_version);
        setScore(""); setFeedback("");
      } else if (action === "redo" && part && deadline) {
        await assessmentPartsApi.redo(courseId, taskId, part, new Date(deadline).toISOString(), reason);
        setDeadline(""); setReason("");
      }
      await Promise.all([
        parts.refetch(),
        client.invalidateQueries({ queryKey: ["assessment-report-review", courseId, taskId] }),
        client.invalidateQueries({ queryKey: ["assessment-report-queue", courseId] }),
        client.invalidateQueries({ queryKey: ["course-grade-analysis", courseId] }),
      ]);
      toast.notify(action === "grade" ? "报告评分已保存" : "补做已开放");
    } catch (error) {
      toast.notify(error instanceof Error ? error.message : "保存失败", "error");
    } finally {
      setBusy(false);
    }
  }

  async function download(assetId: string) {
    try {
      const grant = await fileApi.createDownloadGrant(assetId);
      if (!/^\/files\/[A-Za-z0-9_-]+$/.test(grant.download_path)) throw new Error("文件地址无效");
      window.location.assign(grant.download_path);
    } catch (error) {
      toast.notify(error instanceof Error ? error.message : "下载失败", "error");
    }
  }

  return <section className="assessment-review-detail" aria-label="分项成绩与报告">
    <Panel title={<h2>分项成绩与报告</h2>}>
    {parts.isPending && <p role="status">正在载入分项成绩…</p>}
    {parts.isError && <p role="alert">分项成绩载入失败。 <button className="btn sm" onClick={() => void parts.refetch()}>重试</button></p>}
    {parts.isSuccess && !parts.data.parts.length && <p>此答卷使用原有评审流程。</p>}
    {(parts.data?.parts.length ?? 0) > 0 && <dl className="assessment-part-scores">
      {parts.data?.parts.map((item) => <div key={item.kind}>
        <dt>{assessmentPartLabel[item.kind]}</dt>
        <dd><strong>{item.score == null ? "—" : `${item.score} / 100`}</strong>
          <span>{partStatus[item.status]}</span>
          {item.redo_until && <span>补做截止 {formatDateTime(item.redo_until)} · 上限 60 分</span>}
        </dd>
      </div>)}
    </dl>}
    {report.isError && reportPart?.status !== "RETURNED" && <p role="alert">实验报告载入失败。</p>}
    <div className="assessment-report-controls">
    {data?.attachment && <section className="section">
      <h3>当前报告附件</h3>
      <p>{data.attachment.file_name} · {formatDateTime(data.submitted_at ?? "")}</p>
      <button className="btn" type="button" onClick={() => void download(data.attachment!.asset_id)}>下载报告</button>
      {data.feedback && <p>已保存评语 · {data.feedback}</p>}
      {data.status !== "RETURNED" && <form className="assessment-review-fields" onSubmit={(event) => { event.preventDefault(); void save("grade"); }}>
        <label>报告评分（上限 {data.score_cap} 分）
          <input className="field" type="number" min="0" max={data.score_cap} step="0.01"
            required value={score} onChange={(event) => setScore(event.target.value)} />
        </label>
        <label>评语<textarea className="field" rows={3} maxLength={1000} value={feedback}
          onChange={(event) => setFeedback(event.target.value)} /></label>
        <button className="btn primary" type="submit" disabled={busy}>保存评分</button>
      </form>}
    </section>}
    {parts.data?.redo_available && eligible.length > 0 && <form className="assessment-review-fields section"
      onSubmit={(event) => { event.preventDefault(); void save("redo"); }}>
      <h3>开放补做</h3>
      <label>补做部分<select className="field" required value={part}
        onChange={(event) => setPart(event.target.value as AssessmentPart["kind"] | "")}>
        <option value="">请选择</option>
        {eligible.map((item) => <option key={item.kind} value={item.kind}>{assessmentPartLabel[item.kind]}</option>)}
      </select></label>
      <label>补做截止<input className="field" type="datetime-local" value={deadline} required
        onChange={(event) => setDeadline(event.target.value)} /></label>
      <label>补做说明<input className="field" value={reason} maxLength={500}
        onChange={(event) => setReason(event.target.value)} /></label>
      {part && <StatusBadge tone="warn">补做成绩上限 60 分</StatusBadge>}
      <button className="btn" type="submit" disabled={busy}>{part === "REPORT" ? "退回报告并开放补做" : "开放补做"}</button>
    </form>}
    </div>
    </Panel>
  </section>;
}
