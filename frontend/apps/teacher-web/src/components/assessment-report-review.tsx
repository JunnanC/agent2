import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { assessmentPartLabel, assessmentPartsApi, fileApi } from "@edu/api-client";
import type { AssessmentPart, ReportComment } from "@edu/api-client";
import { EmptyState, Panel, StatusBadge, useToast } from "@edu/ui";
import { formatDateTime } from "@/lib/format";
import { partStatus } from "@/lib/assessment-status";
import "./assessment-reviews.css";

export function AssessmentReportReview({
  courseId, publicationId, initialTaskId, direct = false,
}: { courseId: string; publicationId: string; initialTaskId: string; direct?: boolean }) {
  const [taskId, setTaskId] = useState(initialTaskId);
  const [search, setSearch] = useState("");
  const reports = useQuery({
    queryKey: ["assessment-report-queue", courseId, publicationId],
    queryFn: () => assessmentPartsApi.reports(courseId, publicationId),
    refetchInterval: direct ? 5000 : false,
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
            <small>{partStatus[row.status]} · {formatDateTime(row.submitted_at)}
              {direct && row.review_status && ` · ${reviewLabel[row.review_status] ?? row.review_status}`}</small>
          </button>)}
        </div>
      </section>
    </aside>
    {taskId
      ? <ReportDetail key={taskId} courseId={courseId} taskId={taskId} direct={direct} />
      : <Panel><EmptyState title="选择一份实验报告" /></Panel>}
  </div>;
}

const reviewLabel: Record<string, string> = {
  QUEUED: "AI 待批阅", RUNNING: "AI 批阅中", READY: "AI 建议待确认", FAILED: "AI 批阅失败",
};

function ReportDetail({ courseId, taskId, direct }: { courseId: string; taskId: string; direct: boolean }) {
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
    refetchInterval: direct ? 5000 : false,
  });
  const paragraphs = useQuery({
    queryKey: ["report-paragraphs", courseId, taskId, report.data?.attachment?.asset_id],
    queryFn: () => assessmentPartsApi.report(courseId, taskId, true),
    enabled: direct && Boolean(report.data?.attachment),
  });
  const [score, setScore] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [comments, setComments] = useState<ReportComment[] | null>(null);
  const [part, setPart] = useState<AssessmentPart["kind"] | "">("");
  const [deadline, setDeadline] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const data = report.data;
  const displayedScore = score ?? data?.score ?? data?.ai_review?.score ?? "";
  const displayedFeedback = feedback ?? (data?.status === "GRADED" ? data.feedback : data?.ai_review?.feedback) ?? "";
  const displayedComments = comments ?? (data?.status === "GRADED" ? data.comments : data?.ai_review?.comments) ?? [];
  const eligible = (parts.data?.parts ?? []).filter((item) =>
    item.kind !== "PROGRAMMING" || item.status !== "SUBMITTED",
  );

  async function save(action: "grade" | "redo") {
    setBusy(true);
    try {
      if (action === "grade" && data?.row_version != null) {
        await assessmentPartsApi.gradeReport(
          courseId, taskId, displayedScore, displayedFeedback, data.row_version,
          direct ? displayedComments : undefined,
        );
        setScore(null); setFeedback(null); setComments(null);
      } else if (action === "redo" && part && deadline) {
        await assessmentPartsApi.redo(courseId, taskId, part, new Date(deadline).toISOString(), reason);
        setDeadline(""); setReason("");
      }
      await Promise.all([
        parts.refetch(),
        client.invalidateQueries({ queryKey: ["assessment-report-review", courseId, taskId] }),
        client.invalidateQueries({ queryKey: ["assessment-report-queue", courseId] }),
        client.invalidateQueries({ queryKey: ["lab-grade-release", courseId] }),
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
        <dd><strong>{item.score == null ? "—" : `${item.score} / ${item.max_score}`}</strong>
          <span>{partStatus[item.status]}</span>
          {item.redo_until && <span>补做截止 {formatDateTime(item.redo_until)} · 上限 {item.score_cap} 分</span>}
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
      {direct && data.review_status && <p role="status">{reviewLabel[data.review_status]}</p>}
      {data.released_at && <p>已发布 · {data.signer} · {formatDateTime(data.released_at)}</p>}
      {data.released_at && data.comments?.map((comment, index) => <p key={index}>第 {comment.paragraph} 段 · {comment.text}</p>)}
      {data.status !== "RETURNED" && !data.released_at && <form className="assessment-review-fields" onSubmit={(event) => { event.preventDefault(); void save("grade"); }}>
        <label>报告评分（上限 {data.score_cap} 分）
          <input className="field" type="number" min="0" max={data.score_cap} step="0.01"
            required value={displayedScore} onChange={(event) => setScore(event.target.value)} />
        </label>
        <label>评语<textarea className="field" rows={3} maxLength={1000} value={displayedFeedback}
          onChange={(event) => setFeedback(event.target.value)} /></label>
        {direct && <fieldset className="lab-cases">
          <legend>正文批注</legend>
          {paragraphs.data?.paragraphs_unavailable && <p role="alert">无法读取报告段落，可下载原稿核对。</p>}
          {displayedComments.map((comment, index) => <div key={index} className="lab-form">
            <label>正文段落<input className="field" type="number" min="1" required value={comment.paragraph}
              onChange={(event) => setComments(displayedComments.map((item, position) => position === index
                ? { ...item, paragraph: Number(event.target.value) } : item))} /></label>
            {paragraphs.data?.paragraphs?.find((row) => row.paragraph === comment.paragraph)?.text && <p className="subtle">
              {paragraphs.data.paragraphs.find((row) => row.paragraph === comment.paragraph)?.text}
            </p>}
            <label>批注<textarea className="field" rows={2} required maxLength={1000} value={comment.text}
              onChange={(event) => setComments(displayedComments.map((item, position) => position === index
                ? { ...item, text: event.target.value } : item))} /></label>
            <button className="btn sm" type="button" onClick={() => setComments(displayedComments.filter((_, position) => position !== index))}>删除批注</button>
          </div>)}
          {paragraphs.data?.paragraphs?.length ? <details>
            <summary>查看正文段落和字号</summary>
            <ol>{paragraphs.data.paragraphs.map((item) => <li key={item.paragraph} value={item.paragraph}>
              {item.text} {item.sizes_pt.length > 0 && <small>（{item.sizes_pt.join("、")} 磅）</small>}
            </li>)}</ol>
          </details> : null}
          <button className="btn sm" type="button" disabled={displayedComments.length >= 50}
            onClick={() => setComments([...displayedComments, {
              paragraph: paragraphs.data?.paragraphs?.[0]?.paragraph ?? 1, text: "",
            }])}>添加批注</button>
        </fieldset>}
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
      {part && <StatusBadge tone="warn">补做成绩上限为该部分满分的 60%</StatusBadge>}
      <button className="btn" type="submit" disabled={busy}>{part === "REPORT" ? "退回报告并开放补做" : "开放补做"}</button>
    </form>}
    </div>
    </Panel>
  </section>;
}
