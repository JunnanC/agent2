import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { assessmentTeachingApi } from "@edu/api-client";
import type { TeacherAssessmentReview } from "@edu/api-client";
import { useToast } from "@edu/ui";
import { newIdempotencyKey } from "@edu/auth-client";

import { GRADING_STATUS_LABEL, REPORT_REVIEW_STATUS_LABEL } from "@/lib/format";

export function AssessmentReviews({ courseId, publicationId = "" }: { courseId: string; publicationId?: string }) {
  const [taskId, setTaskId] = useState("");
  const [scores, setScores] = useState<Record<string, string>>({});
  const [feedback, setFeedback] = useState("");
  const [returnUntil, setReturnUntil] = useState("");
  const [busy, setBusy] = useState(false);
  const [suggestion, setSuggestion] = useState<Awaited<ReturnType<typeof assessmentTeachingApi.reportSuggestion>> | null>(null);
  const toast = useToast();
  const client = useQueryClient();
  const rows = useQuery({ queryKey: ["assessment-reviews", courseId, publicationId], queryFn: () => assessmentTeachingApi.reviews(courseId, publicationId) });
  const detail = useQuery({ queryKey: ["assessment-review", courseId, taskId], queryFn: () => assessmentTeachingApi.review(courseId, taskId), enabled: !!taskId });
  const section = detail.data?.sections.find((s) => s.kind === "PROGRAMMING");

  async function save(returned: boolean) {
    if (!section?.submission_version) return;
    setBusy(true);
    try {
      if (returned && !returnUntil) throw new Error("退回必须指定重交截止时间");
      await assessmentTeachingApi.saveReview(courseId, taskId, {
        submission_version: section.submission_version, scores, feedback,
        ...(returned ? { return_until: new Date(returnUntil).toISOString() } : {}),
      }, section.row_version);
      await Promise.all([
        detail.refetch(), rows.refetch(),
        client.invalidateQueries({ queryKey: ["teaching-reviews", courseId] }),
        client.invalidateQueries({ queryKey: ["teaching-analytics", courseId, "progress"] }),
        client.invalidateQueries({ queryKey: ["teaching-courses", "overview-summary"] }),
      ]); toast.notify(returned ? "编程卷已退回，选择题提交保持有效" : "报告评分已保存");
    } catch (error) { toast.notify(error instanceof Error ? error.message : "操作失败", "error"); }
    finally { setBusy(false); }
  }

  return <section className="panel" aria-label="分卷评审">
    <h2>答题评审</h2>
    {rows.error && <p role="alert">评审列表载入失败</p>}
    {!rows.data?.length && <p>暂无可评审的答题交卷。</p>}
    <label>选择交卷<select className="field" value={taskId} onChange={(e) => { setTaskId(e.target.value); setScores({}); setFeedback(""); setSuggestion(null); }}>
      <option value="">选择学生与实验</option>
      {rows.data?.map((row) => <option key={`${row.task_id}:${row.kind}`} value={row.task_id}>{row.student_name} · {row.title} · {row.kind === "CHOICE" ? "选择题" : "编程与报告"} · 第 {row.version_no} 次 · {REPORT_REVIEW_STATUS_LABEL[row.review_status ?? ""] ?? "状态未知"}</option>)}
    </select></label>
    {detail.data && detail.data.choice_answers?.length > 0 && <ChoiceReview data={detail.data} />}
    {detail.data && section && <>
      <h3>{detail.data.student_name} · 第 {section.submission_version} 次提交</h3>
      <p>报告评审：{REPORT_REVIEW_STATUS_LABEL[section.review_status ?? ""] ?? "状态未知"}</p>
      <p>综合评分状态：{GRADING_STATUS_LABEL[section.grading_status] ?? "状态未知"}，教师不直接修改代码得分。</p>
      {section.questions.map((q) => <p key={q.id}>{q.title || "未命名题目"}（{q.language}）：{q.score ?? "待判题"} / {q.max_score}</p>)}
      <button className="btn" disabled={busy} onClick={() => {
        setBusy(true);
        void assessmentTeachingApi.saveReview(courseId, taskId, {
          submission_version: section.submission_version!, scores: {}, feedback: "", retry_judge: true,
        }, section.row_version).then(() => detail.refetch()).catch(() => toast.notify("重试失败", "error")).finally(() => setBusy(false));
      }}>重试平台失败的判题</button>
      {detail.data.sources?.map((source) => <details key={source.question_id}><summary>查看提交代码（{source.language}）</summary>{Object.entries(source.files).map(([path, code]) => <div key={path}><h4>{path}</h4><pre>{code}</pre></div>)}</details>)}
      <h3>本次总报告</h3><pre style={{ whiteSpace: "pre-wrap" }}>{detail.data.report?.body_markdown ?? "未附报告"}</pre>
      <button className="btn" disabled={!detail.data.report} onClick={() => {
        if (!detail.data.report) return;
        const report = detail.data.report;
        const sectionData = detail.data.sections.find((item) => item.kind === "PROGRAMMING");
        const version = detail.data.history?.find((item) => item.kind === "PROGRAMMING")
          ?.versions.find((item) => item.version_no === report.version_no);
        const submittedAt = version ? new Date(version.submitted_at).toLocaleString("zh-CN") : "—";
        const header = [
          "# 实验报告",
          "",
          `- 学生：${detail.data.student_name}`,
          `- 任务：${taskId}`,
          `- 提交版本：第 ${report.version_no} 次`,
          `- 提交时间：${submittedAt}`,
          `- 报告得分：${sectionData?.report_score == null ? "待评分" : `${sectionData.report_score} / ${sectionData.report_max_score ?? "—"}`}`,
          "",
          "---",
          "",
        ].join("\n");
        const blob = new Blob([header + report.body_markdown], { type: "text/markdown;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `experiment-report-${taskId}-v${report.version_no}.md`;
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 0);
      }}>下载报告</button>
      <button className="btn" disabled={busy || !detail.data.report || section.status === "RETURNED"} onClick={() => {
        setBusy(true);
        void assessmentTeachingApi.reportSuggestion(courseId, taskId, section.submission_version!, newIdempotencyKey())
          .then(setSuggestion).catch(() => toast.notify("报告 AI 建议暂不可用，请人工评分", "error")).finally(() => setBusy(false));
      }}>获取报告 AI 建议</button>
      {suggestion?.submission_version === section.submission_version && <div className="section">
        <p>仅供教师参考，不修改代码分或报告正式成绩。</p>
        {suggestion.criteria.map((item) => <p key={item.criterion_id}>{item.score} 分 · {item.rationale} · {item.evidence}</p>)}
        <button className="btn" onClick={() => setScores(Object.fromEntries(suggestion.criteria.map((item) => [item.criterion_id, item.score])))}>填入建议，人工核对后保存</button>
      </div>}
      {detail.data.report_criteria.map((criterion) => <label key={criterion.id}>{criterion.title}（满分 {criterion.max_score}）
        <input className="field" type="number" min="0" max={criterion.max_score} step="0.01" value={scores[criterion.id] ?? ""} onChange={(e) => { const value = e.target.value; setScores((previous) => ({ ...previous, [criterion.id]: value })); }} />
      </label>)}
      <label>评语<textarea className="field" value={feedback} onChange={(e) => setFeedback(e.target.value)} /></label>
      <button className="btn primary" disabled={busy || section.status === "RETURNED"} onClick={() => void save(false)}>保存报告评分</button>
      <label>退回后的重交截止时间<input className="field" type="datetime-local" value={returnUntil} onChange={(e) => setReturnUntil(e.target.value)} /></label>
      <button className="btn" disabled={busy || !returnUntil} onClick={() => void save(true)}>退回编程与报告卷</button>
    </>}
  </section>;
}

function ChoiceReview({ data }: { data: TeacherAssessmentReview }) {
  const optionText = (options: Array<{ id: string; text: string }>, ids: string[]) =>
    options.filter((option) => ids.includes(option.id)).map((option) => option.text).join("；") || "未作答";
  return <div className="section" aria-label="选择题答卷">
    <h3>{data.student_name} · 选择题答卷</h3>
    <table className="data-table">
      <thead><tr><th>题目</th><th>学生选择</th><th>正确答案</th><th>得分</th></tr></thead>
      <tbody>
        {data.choice_answers.map((answer) => (
          <tr key={answer.question_id}>
            <td>{answer.title}</td>
            <td>{optionText(answer.options, answer.selected_option_ids)}</td>
            <td>{optionText(answer.options, answer.correct_option_ids)}</td>
            <td>{answer.score == null ? "待评分" : `${answer.score} / ${answer.max_score}`}</td>
          </tr>
        ))}
      </tbody>
    </table>
    <p className="subtle">选择题由平台自动评分，教师可只读核对作答与答案，无需人工打分。</p>
  </div>;
}
