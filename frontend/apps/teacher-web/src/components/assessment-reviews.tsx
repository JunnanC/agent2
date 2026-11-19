import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { assessmentPartLabel, assessmentTeachingApi } from "@edu/api-client";
import type { TeacherAssessmentReview } from "@edu/api-client";
import { EmptyState, Panel, StatusBadge, useToast } from "@edu/ui";
import { newIdempotencyKey } from "@edu/auth-client";

import { GRADING_STATUS_LABEL, REPORT_REVIEW_STATUS_LABEL } from "@/lib/format";
import "./assessment-reviews.css";

type ReviewQueueRow = {
  task_id: string;
  student_name: string;
  title: string;
  version_no: number;
  kinds: string[];
  review_status?: string;
  workspace_flow?: boolean;
};
type ExamReviewQuestion = Omit<TeacherAssessmentReview["sections"][number]["questions"][number], "title"> & {
  title?: string;
  description?: string;
  instructions?: string;
  task_type?: string;
  samples?: Array<{ input: string; output: string }>;
};
type ExamReview = Omit<TeacherAssessmentReview, "sections" | "choice_answers"> & {
  sections: Array<Omit<TeacherAssessmentReview["sections"][number], "questions"> & {
    questions: ExamReviewQuestion[];
  }>;
  choice_answers: Array<TeacherAssessmentReview["choice_answers"][number] & {
    description?: string;
    instructions?: string;
  }>;
};

export function AssessmentReviews({ courseId, publicationId = "", initialTaskId = "" }: { courseId: string; publicationId?: string; initialTaskId?: string }) {
  const [taskId, setTaskId] = useState(initialTaskId);
  const [scores, setScores] = useState<Record<string, string>>({});
  const [feedback, setFeedback] = useState("");
  const [returnUntil, setReturnUntil] = useState("");
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [suggestion, setSuggestion] = useState<Awaited<ReturnType<typeof assessmentTeachingApi.reportSuggestion>> | null>(null);
  const toast = useToast();
  const client = useQueryClient();
  const rows = useQuery({ queryKey: ["assessment-reviews", courseId, publicationId], queryFn: () => assessmentTeachingApi.reviews(courseId, publicationId) });
  const detail = useQuery({ queryKey: ["assessment-review", courseId, taskId],
    queryFn: () => assessmentTeachingApi.review(courseId, taskId).then(review => review as ExamReview), enabled: !!taskId });
  const section = detail.data?.sections.find((s) => s.kind === "PROGRAMMING");
  const pendingRows = (rows.data ?? []).filter(
    (row) => row.kind === "PROGRAMMING" && row.review_status === "PENDING",
  );
  const queueRows = useMemo(() => {
    const grouped = new Map<string, ReviewQueueRow>();
    for (const row of rows.data ?? []) {
      const current = grouped.get(row.task_id);
      if (current) {
        if (!current.kinds.includes(row.kind)) current.kinds.push(row.kind);
        if (row.kind === "PROGRAMMING") {
          current.review_status = row.review_status;
          current.version_no = row.version_no;
        }
      } else {
        grouped.set(row.task_id, {
          task_id: row.task_id,
          student_name: row.student_name,
          title: row.title,
          version_no: row.version_no,
          kinds: [row.kind],
          review_status: row.kind === "PROGRAMMING" ? row.review_status : undefined,
          workspace_flow: row.workspace_flow,
        });
      }
    }
    return [...grouped.values()];
  }, [rows.data]);
  const visibleQueueRows = queueRows.filter(row =>
    !search.trim()
    || `${row.student_name} ${row.title}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
  );
  const selectedTask = queueRows.find(row => row.task_id === taskId);
  const reviewLocked = section?.review_status === "COMPLETED";

  function selectTask(nextTaskId: string) {
    setTaskId(nextTaskId);
    setScores({});
    setFeedback("");
    setReturnUntil("");
    setSuggestion(null);
  }

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
    } catch (error) {
      const message = error instanceof Error ? error.message : "操作失败";
      toast.notify(message.includes("资源当前状态不允许")
        ? "这份报告已完成评审，当前状态不能再次保存。如需重新评分，请先「退回编程与报告卷」让学生重交。"
        : message, "error");
    }
    finally { setBusy(false); }
  }

  return <div className="assessment-review-workspace">
    <aside className="assessment-review-queue" aria-label="学生交卷列表">
      <section className="assessment-review-queue-panel">
        <header className="assessment-review-queue-heading">
          <h2>学生答卷</h2>
          <StatusBadge tone={pendingRows.length ? "warn" : "neutral"}>待评审 {pendingRows.length} 份</StatusBadge>
        </header>
        <input className="field" type="search" aria-label="搜索学生或实验" placeholder="搜索学生或实验"
          value={search} onChange={event => setSearch(event.target.value)} />
        {rows.error && <p role="alert">交卷列表载入失败</p>}
        {!rows.isLoading && !queueRows.length && <EmptyState title="暂无已交卷" hint="学生提交后，答卷会显示在这里。" />}
        {queueRows.length > 0 && !visibleQueueRows.length && <p className="subtle">没有匹配的学生或实验。</p>}
        <div className="assessment-review-queue-list">
          {visibleQueueRows.map(row => {
            const reviewLabel = row.review_status
              ? REPORT_REVIEW_STATUS_LABEL[row.review_status] ?? "状态未知"
              : row.kinds.includes("CHOICE") ? "选择题已交卷" : "已交卷";
            const reviewTone = row.review_status === "PENDING" || row.review_status === "RETURNED"
              ? "warn" as const
              : row.review_status === "COMPLETED" ? "good" as const : "neutral" as const;
            const kinds = row.workspace_flow
              ? row.kinds.map((kind) => kind === "CHOICE" ? "选择题" : "编程题").join(" + ")
              : row.kinds.includes("CHOICE") && row.kinds.includes("PROGRAMMING")
              ? "选择题 + 编程与报告"
              : row.kinds.includes("CHOICE") ? "选择题" : "编程与报告";
            return <button type="button" className={`assessment-review-queue-row${taskId === row.task_id ? " active" : ""}`}
              key={row.task_id} aria-pressed={taskId === row.task_id}
              aria-label={`打开答卷：${row.student_name} · ${row.title}`}
              onClick={() => selectTask(row.task_id)}>
              <span className="assessment-review-queue-student">{row.student_name}</span>
              <strong>{row.title}</strong>
              <span className="subtle">{kinds}{!row.workspace_flow && ` · 第 ${row.version_no} 次提交`}</span>
              <StatusBadge tone={reviewTone}>{row.workspace_flow ? "有提交记录" : reviewLabel}</StatusBadge>
            </button>;
          })}
        </div>
      </section>
    </aside>

    <section className="assessment-review-detail" aria-label="试卷与评审">
      {!taskId && <div className="state-block">
        <strong>选择一份学生答卷</strong>
        <p>选中左侧交卷后，可以查看题目、作答、判分和报告。</p>
      </div>}
      {taskId && detail.isLoading && <p className="subtle">正在载入学生答卷…</p>}
      {taskId && detail.error && <p role="alert">学生答卷载入失败，请重试。</p>}
      {detail.data && <>
        <ExamPaper review={detail.data} title={selectedTask?.title ?? "实验答卷"} taskId={taskId} />
        {section && !detail.data.parts?.length && <Panel className="assessment-report-review" title={<>
          <h2>评审操作</h2>
          <StatusBadge tone={reviewLocked ? "good" : "warn"}>
            {REPORT_REVIEW_STATUS_LABEL[section.review_status ?? ""] ?? "待评审"}
          </StatusBadge>
        </>}>
          {detail.data.report_criteria.length > 0 && <p className="subtle">按评分项核对学生报告。编程题得分由平台判题，教师在这里评阅报告。</p>}
          {reviewLocked && <p role="note">这份报告已经完成评审。如需重新评分，请先退回让学生重交。</p>}
          {section.questions.some(question => question.score == null) && <button type="button" className="btn sm" disabled={busy} onClick={() => {
            setBusy(true);
            void assessmentTeachingApi.saveReview(courseId, taskId, {
              submission_version: section.submission_version!, scores: {}, feedback: "", retry_judge: true,
            }, section.row_version).then(() => detail.refetch()).catch(() => toast.notify("重试失败", "error")).finally(() => setBusy(false));
          }}>重试失败的判题</button>}
          {detail.data.report && detail.data.report_criteria.length > 0 && <div className="assessment-report-actions">
            <button type="button" className="btn sm" disabled={busy || section.status === "RETURNED"} onClick={() => {
              setBusy(true);
              void assessmentTeachingApi.reportSuggestion(courseId, taskId, section.submission_version!, newIdempotencyKey())
                .then(setSuggestion).catch(() => toast.notify("报告 AI 建议暂不可用，请人工评分", "error")).finally(() => setBusy(false));
            }}>获取报告 AI 建议</button>
          </div>}
          {detail.data.report_criteria.length > 0 && suggestion?.submission_version === section.submission_version && <div className="assessment-suggestion">
            <p>AI 建议仅供参考，保存前请核对评分依据和证据。</p>
            {suggestion.criteria.map(item => <p key={item.criterion_id}>{item.score} 分 · {item.rationale} · {item.evidence}</p>)}
            <button type="button" className="btn sm" onClick={() => setScores(Object.fromEntries(suggestion.criteria.map(item => [item.criterion_id, item.score])))}>填入建议分</button>
          </div>}
          {detail.data.report_criteria.length > 0 && <div className="assessment-rubric-fields">
            {detail.data.report_criteria.map(criterion => <label key={criterion.id}>{criterion.title}（满分 {criterion.max_score}）
              <input className="field" type="number" min="0" max={criterion.max_score} step="0.01" value={scores[criterion.id] ?? ""}
                onChange={event => { const value = event.target.value; setScores(previous => ({ ...previous, [criterion.id]: value })); }} />
            </label>)}
          </div>}
          {detail.data.report_criteria.length > 0 && <label>评语<textarea className="field" value={feedback} onChange={event => setFeedback(event.target.value)} /></label>}
          <div className="assessment-review-actions">
            {detail.data.report_criteria.length > 0 && <button type="button" className="btn primary" disabled={busy || section.status === "RETURNED" || reviewLocked} onClick={() => void save(false)}>保存报告评分</button>}
            <label>退回后重交截止时间<input className="field" type="datetime-local" value={returnUntil} onChange={event => setReturnUntil(event.target.value)} /></label>
            <button type="button" className="btn" disabled={busy || !returnUntil} onClick={() => void save(true)}>退回重交</button>
          </div>
        </Panel>}
      </>}
    </section>
  </div>;
}

function ExamPaper({ review, title, taskId }: { review: ExamReview; title: string; taskId: string }) {
  const sections = review.sections ?? [];
  const maximum = sections.reduce((sum, item) => sum + Number(item.max_score ?? 0), 0);
  const score = sections.reduce((sum, item) => sum + Number(item.score ?? 0), 0);
  const scorePending = sections.some(item => item.score == null);
  const programming = sections.find(item => item.kind === "PROGRAMMING");
  return <article className="assessment-exam-paper">
    <header className="assessment-exam-heading">
      <div className="assessment-exam-identity">
        <p className="eyebrow">学生试卷</p>
        <h2>{review.student_name}</h2>
        <p>{title} · 固定提交记录</p>
      </div>
      <div className="assessment-exam-summary">
        {review.parts?.length ? <dl className="assessment-part-scores">
          {review.parts.map((part) => <div key={part.kind}>
            <dt>{assessmentPartLabel[part.kind]}</dt>
            <dd>{part.score == null ? "—" : `${part.score} / 100`}{part.score_cap === 60 && " · 上限 60"}</dd>
          </div>)}
        </dl> : <><div className="assessment-exam-score" aria-label="当前成绩">
          <span>当前成绩</span>
          <div><strong>{scorePending ? (score ? `${score} · 部分` : "待评分") : score}</strong><span> / {maximum}</span></div>
        </div>
        <div className="assessment-exam-statuses">{sections.map(section => <StatusBadge key={section.kind}
          tone={section.grading_status === "COMPLETED" ? "good" : section.grading_status === "RETURNED" ? "warn" : "neutral"}>
          {section.kind === "CHOICE" ? "选择题" : "编程与报告"} · {GRADING_STATUS_LABEL[section.grading_status] ?? "状态未知"}
        </StatusBadge>)}</div></>}
      </div>
    </header>
    {review.choice_answers?.length > 0 && <ChoiceReview data={review} />}
    {programming && <ProgrammingReview review={review} />}
    {review.report && <section className="assessment-exam-section" aria-label="实验报告">
      <header className="assessment-exam-section-heading">
        <div><h3>实验报告</h3><p className="subtle">第 {review.report.version_no} 次提交</p></div>
        <div className="assessment-report-actions">
          {programming?.report_score != null && <StatusBadge tone="good">{programming.report_score} / {programming.report_max_score}</StatusBadge>}
          <button type="button" className="btn sm" onClick={() => downloadReport(review, taskId)}>下载报告</button>
        </div>
      </header>
      <pre className="assessment-report-body">{review.report.body_markdown}</pre>
    </section>}
    {review.history?.length ? <details className="assessment-submission-history">
      <summary>提交历史</summary>
      {review.history.map(item => <div key={item.kind}>
        <strong>{item.kind === "CHOICE" ? "选择题" : "编程与报告"}</strong>
        {item.versions.map(version => <p key={version.version_no}>第 {version.version_no} 次 · {new Date(version.submitted_at).toLocaleString("zh-CN")}</p>)}
      </div>)}
    </details> : null}
  </article>;
}

function ChoiceReview({ data }: { data: ExamReview }) {
  const optionText = (options: Array<{ id: string; text: string }>, ids: string[]) =>
    options.filter(option => ids.includes(option.id)).map(option => option.text).join("；") || "未作答";
  const total = data.choice_answers.reduce((sum, answer) => sum + Number(answer.score ?? 0), 0);
  const max = data.choice_answers.reduce((sum, answer) => sum + Number(answer.max_score ?? 0), 0);
  const score = data.parts?.find((part) => part.kind === "CHOICE");
  return <section className="assessment-exam-section" aria-label="选择题答卷">
    <header className="assessment-exam-section-heading">
      <div><h3>选择题答卷</h3><p className="subtle">自动判分 · 本卷 {score ? `${score.score ?? "—"} / 100` : `${total} / ${max}`} 分</p></div>
      <StatusBadge tone="good">已提交</StatusBadge>
    </header>
    <div className="assessment-choice-list">
      {data.choice_answers.map((answer, index) => {
        const earned = answer.score == null ? null : Number(answer.score);
        const possible = Number(answer.max_score);
        const result = earned == null ? "待评分" : earned >= possible ? "正确" : earned > 0 ? "部分得分" : "未得分";
        const tone = earned == null ? "neutral" as const : earned >= possible ? "good" as const : earned > 0 ? "warn" as const : "bad" as const;
        return <article className="assessment-choice-question" key={answer.question_id}>
          <header><span>第 {index + 1} 题 · {answer.task_type === "MULTIPLE_CHOICE" ? "多选题" : "单选题"}</span><StatusBadge tone={tone}>{result}{!score && ` · ${answer.score ?? "—"} / ${answer.max_score}`}</StatusBadge></header>
          <h4>{answer.title}</h4>
          {answer.description && <p>{answer.description}</p>}
          {answer.instructions && <p className="subtle">{answer.instructions}</p>}
          <div className="assessment-choice-options">
            {answer.options.map((option, optionIndex) => {
              const selected = answer.selected_option_ids.includes(option.id);
              const correct = answer.correct_option_ids.includes(option.id);
              return <div className={`assessment-choice-option${correct ? " correct" : ""}${selected ? " selected" : ""}`} key={option.id}>
                <span className="assessment-choice-letter">{String.fromCharCode(65 + optionIndex)}</span>
                <span>{option.text}</span>
                <span className="assessment-choice-tags">
                  {selected && <StatusBadge tone="blue">学生选择</StatusBadge>}
                  {correct && <StatusBadge tone="good">正确答案</StatusBadge>}
                </span>
              </div>;
            })}
          </div>
          {!answer.selected_option_ids.length && <p className="subtle">学生未作答。</p>}
          <div className="assessment-choice-result"><span>学生作答</span><strong>{optionText(answer.options, answer.selected_option_ids)}</strong></div>
        </article>;
      })}
    </div>
  </section>;
}

function ProgrammingReview({ review }: { review: ExamReview }) {
  const section = review.sections.find(item => item.kind === "PROGRAMMING");
  if (!section) return null;
  const sources = new Map(review.sources.map(source => [source.question_id, source]));
  return <section className="assessment-exam-section" aria-label="编程题答卷">
    <header className="assessment-exam-section-heading">
      <div><h3>编程题答卷</h3><p className="subtle">判题状态：{GRADING_STATUS_LABEL[section.grading_status] ?? "状态未知"}</p></div>
      <StatusBadge tone={section.score != null ? "good" : "neutral"}>
        {section.score == null ? "待出分" : `${section.score} / ${section.max_score}`}
      </StatusBadge>
    </header>
    <div className="assessment-programming-list">
      {section.questions.map((question, index) => {
        const source = sources.get(question.id);
        return <article className="assessment-programming-question" key={question.id}>
          <header><span>第 {index + 1} 题{question.language ? ` · ${question.language}` : ""}</span>
            <strong>{review.parts?.length ? "已通过" : question.score == null ? "待判题" : `${question.score} / ${question.max_score}`}</strong></header>
          <h4>{question.title || "未命名题目"}</h4>
          {question.description && <p>{question.description}</p>}
          {question.instructions && <p className="subtle">{question.instructions}</p>}
          {question.samples?.length ? <details><summary>公开示例</summary>
            {question.samples.map((sample, sampleIndex) => <div className="assessment-sample" key={sampleIndex}>
              <div><span>示例输入</span><pre>{sample.input || "（空）"}</pre></div>
              <div><span>示例输出</span><pre>{sample.output || "（空）"}</pre></div>
            </div>)}
          </details> : null}
          {source && <details><summary>查看学生代码（{source.language}）</summary>
            {Object.entries(source.files).map(([path, code]) => <div className="assessment-source-file" key={path}>
              <strong>{path}</strong><pre>{code}</pre>
            </div>)}
          </details>}
        </article>;
      })}
      {!section.questions.length && <p className="subtle">编程卷暂无作答记录。</p>}
    </div>
  </section>;
}

function downloadReport(review: ExamReview, taskId: string) {
  if (!review.report) return;
  const section = review.sections.find(item => item.kind === "PROGRAMMING");
  const version = review.history?.find(item => item.kind === "PROGRAMMING")
    ?.versions.find(item => item.version_no === review.report!.version_no);
  const submittedAt = version ? new Date(version.submitted_at).toLocaleString("zh-CN") : "—";
  const header = [
    "# 实验报告", "", `- 学生：${review.student_name}`, `- 任务：${taskId}`,
    `- 提交版本：第 ${review.report.version_no} 次`, `- 提交时间：${submittedAt}`,
    `- 报告得分：${section?.report_score == null ? "待评分" : `${section.report_score} / ${section.report_max_score ?? "—"}`}`,
    "", "---", "",
  ].join("\n");
  const blob = new Blob([header + review.report.body_markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `experiment-report-${taskId}-v${review.report.version_no}.md`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
