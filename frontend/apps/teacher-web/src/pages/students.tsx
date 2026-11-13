import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { assessmentTeachingApi, teachingApi } from "@edu/api-client";
import type { TeacherAssessmentReview } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import {
  DataTable, Metric, Drawer, Modal, Panel, RequestStateView, StatusBadge, useToast, EmptyState,
} from "@edu/ui";
import { ASSESSMENT_STATUS_LABEL, GRADING_STATUS_LABEL, REPORT_REVIEW_STATUS_LABEL, apiErrorMessage } from "@/lib/format";
import { formatDateTime } from "@/lib/task-format";

interface ProgressRow {
  public_id: string;
  student_name?: string;
  title: string;
  status: string;
  progress: number;
  effective_deadline?: string | null;
  report_required?: boolean;
}

function workspaceChip(status: string): { label: string; tone: "good" | "warn" | "blue" | "neutral" } {
  if (["IN_PROGRESS", "REPORT_DRAFT"].includes(status)) return { label: "在线", tone: "good" };
  if (status === "READY") return { label: "准备就绪", tone: "blue" };
  if (["SUBMITTED", "UNDER_REVIEW", "COMPLETED", "APPROVED"].includes(status)) return { label: "已结束", tone: "neutral" };
  return { label: "未进入", tone: "neutral" };
}

function reportChip(status: string, required = true): { label: string; tone: "good" | "warn" | "neutral" } {
  if (!required) return { label: "不适用", tone: "neutral" };
  if (status === "REPORT_DRAFT") return { label: "草稿", tone: "warn" };
  if (["SUBMITTED", "UNDER_REVIEW"].includes(status)) return { label: "已提交", tone: "good" };
  if (["COMPLETED", "APPROVED"].includes(status)) return { label: "已评阅", tone: "good" };
  return { label: "未提交", tone: "neutral" };
}

function riskChip(row: ProgressRow): { label: string; tone: "good" | "warn" } {
  if (["FAILED", "REJECTED"].includes(row.status)) return { label: "需要关注", tone: "warn" };
  if (row.effective_deadline && new Date(row.effective_deadline).getTime() < Date.now()
    && !["COMPLETED", "SUBMITTED", "UNDER_REVIEW", "APPROVED"].includes(row.status)) {
    return { label: "逾期未完成", tone: "warn" };
  }
  return { label: "正常", tone: "good" };
}

export function Students() {
  const { courseId = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [detail, setDetail] = useState<ProgressRow | null>(null);

  const progress = useQuery({
    queryKey: keys.teachingProgress(courseId, {}),
    queryFn: () => teachingApi.progress(courseId, { page_size: 100 }),
  });
  const pendingReviews = useQuery({
    queryKey: keys.reviews(courseId, { status: "PENDING" }),
    queryFn: () => assessmentTeachingApi.reviews(courseId).then(rows => ({
      allRows: rows,
      rows: rows.filter(row => row.kind === "PROGRAMMING" && row.review_status === "PENDING"),
      total: rows.filter(row => row.kind === "PROGRAMMING" && row.review_status === "PENDING").length,
    })),
  });

  const rows = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (progress.data?.rows ?? []).filter((row: ProgressRow) =>
      !query || row.student_name?.toLowerCase().includes(query) || row.title.toLowerCase().includes(query));
  }, [progress.data, search]);

  const inProgressCount = (progress.data?.rows ?? []).filter((row) => ["IN_PROGRESS", "REPORT_DRAFT", "READY"].includes(row.status)).length;
  const staleCount = (progress.data?.rows ?? []).filter((row) => {
    if (["COMPLETED", "SUBMITTED", "UNDER_REVIEW", "APPROVED"].includes(row.status)) return false;
    const deadline = row.effective_deadline ? new Date(row.effective_deadline).getTime() : 0;
    return deadline > 0 && deadline < Date.now() - 7 * 86_400_000;
  }).length;
  const failedCount = (progress.data?.rows ?? []).filter((row) => row.status === "FAILED").length;
  const pendingReviewTotal = typeof pendingReviews.data?.total === "number"
    ? pendingReviews.data?.total
    : (pendingReviews.data?.rows.length ?? 0);

  const [evidence, setEvidence] = useState<{ title: string; data: unknown } | null>(null);

  const previewMutation = useMutation({
    mutationFn: (task: ProgressRow) => assessmentTeachingApi.review(courseId, task.public_id),
    onSuccess: (data, task) => setEvidence({ title: `提交预览 · ${task.title}`, data }),
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  return (
    <>
      <div className="page-actions align-end">
        <button type="button" className="btn primary" onClick={() => navigate(`/courses/${courseId}/reviews`)} aria-label="进入评审中心">
          进入评审
        </button>
      </div>

      <Panel className="section">
        <RequestStateView loading={progress.isLoading && !rows.length}
          error={progress.error}
          onRetry={() => void progress.refetch()}
          empty={false} emptyState={null}>
          <div className="metric-strip">
            <Metric label="正常进行" value={String(inProgressCount)} icon="users" sub="人" />
            <Metric label="长时未活动" value={String(staleCount)} icon="clock" sub="按截止时间判断" />
            <Metric label="报告待审" value={String(pendingReviewTotal)} icon="file-check" sub="份" />
            <Metric label="实验失败" value={String(failedCount)} icon="alert-triangle" sub="个任务" />
          </div>
        </RequestStateView>
      </Panel>

      <Panel title={<><h2>学生进度与风险</h2></>}
        actions={(
          <input className="field" style={{ width: 210 }} type="search" placeholder="搜索学生"
            aria-label="搜索学生" value={search} onChange={(event) => setSearch(event.target.value)} />
        )}>
        <RequestStateView
          loading={progress.isLoading}
          error={progress.error}
          onRetry={() => void progress.refetch()}
          empty={!rows.length}
          emptyState={<EmptyState title="暂无学生任务" hint="实验发布并分配后才出现学生过程记录。" />}
        >
          <DataTable
            rows={rows}
            rowKey={(row: ProgressRow) => row.public_id}
            columns={[
              { key: "student", header: "学生", render: (row: ProgressRow) => <strong>{row.student_name ?? "—"}</strong> },
              { key: "task", header: "当前任务", render: (row: ProgressRow) => row.title },
              {
                key: "progress", header: "进度", width: 170, render: (row: ProgressRow) => (
                  <div style={{ minWidth: 130 }}>
                    <div className="progress"><span style={{ width: `${row.progress}%` }} /></div>
                    <small style={{ display: "block", marginTop: 3 }}>{row.progress}%</small>
                  </div>
                ),
              },
              { key: "deadline", header: "最近活动", render: (row: ProgressRow) => (
                row.effective_deadline
                  ? (new Date(row.effective_deadline).getTime() < Date.now()
                    ? `已过截止 ${formatDateTime(row.effective_deadline)}`
                    : `距截止 ${formatDateTime(row.effective_deadline)}`)
                  : "无截止时间"
              ) },
              {
                key: "assessment", header: "答题", render: (row: ProgressRow) => {
                  const chip = workspaceChip(row.status);
                  return <StatusBadge tone={chip.tone}>{chip.label}</StatusBadge>;
                },
              },
              {
                key: "report", header: "报告", render: (row: ProgressRow) => {
                  const review = pendingReviews.data?.allRows.find(item => item.task_id === row.public_id && item.kind === "PROGRAMMING");
                  const chip = review?.review_status
                    ? { label: REPORT_REVIEW_STATUS_LABEL[review.review_status] ?? "状态未知", tone: ["RETURNED", "PENDING"].includes(review.review_status) ? "warn" as const : "good" as const }
                    : reportChip(row.status, row.report_required !== false);
                  return <StatusBadge tone={chip.tone}>{chip.label}</StatusBadge>;
                },
              },
              {
                key: "risk", header: "风险", render: (row: ProgressRow) => {
                  const chip = riskChip(row);
                  return <StatusBadge tone={chip.tone}>{chip.label}</StatusBadge>;
                },
              },
              {
                key: "actions", header: "", align: "right", render: (row: ProgressRow) => (
                  <button type="button" className="btn sm" onClick={() => setDetail(row)}>查看</button>
                ),
              },
            ]}
          />
        </RequestStateView>
      </Panel>

      <Drawer open={detail != null} onClose={() => setDetail(null)} title={detail ? `${detail.student_name} · ${detail.title}` : "任务详情"}>
        {detail ? (
          <>
            <div className="status-line is-ok" style={{ marginBottom: 10 }}>
              ✓ 查看学生已交卷的固定代码和报告，不读取后续草稿。
            </div>
            <div style={{ display: "grid", gap: 8 }}>
              <button type="button" className="btn" disabled={previewMutation.isPending}
                onClick={() => previewMutation.mutate(detail)}>
                {previewMutation.isPending ? "载入中…" : "提交预览"}
              </button>

            </div>
          </>
        ) : null}
      </Drawer>

      <Modal open={evidence != null} onClose={() => setEvidence(null)}
        eyebrow="学生过程" title={evidence?.title ?? ""} wide
        actions={<button type="button" className="btn" onClick={() => setEvidence(null)}>关闭</button>}>
        {evidence ? <SubmissionEvidence review={evidence.data as TeacherAssessmentReview} /> : null}
      </Modal>
    </>
  );
}

export function SubmissionEvidence({ review }: { review: TeacherAssessmentReview }) {
  const sections = review.sections ?? [];
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="status-line is-ok">✓ 以下为已交卷的固定版本，不读取后续草稿。</div>
      <div className="metric-strip">
        {sections.map((section) => (
          <Metric key={section.kind}
            label={section.kind === "CHOICE" ? "选择题" : "编程与报告"}
            value={section.score ?? "—"}
            sub={`满分 ${section.max_score} · ${GRADING_STATUS_LABEL[section.grading_status] ?? "状态未知"}`} />
        ))}
      </div>
      {sections.map((section) => (
        <Panel key={section.kind} title={section.kind === "CHOICE" ? "选择题答卷" : "编程与报告答卷"}>
          <p className="subtle">答题状态：{ASSESSMENT_STATUS_LABEL[section.status] ?? "状态未知"} · 评分状态：{GRADING_STATUS_LABEL[section.grading_status] ?? "状态未知"}</p>
          {section.kind === "PROGRAMMING" && section.review_status && <p>报告评审：{REPORT_REVIEW_STATUS_LABEL[section.review_status] ?? "状态未知"}</p>}
          {section.questions.length > 0 ? (
            <DataTable
              rows={section.questions}
              rowKey={(question) => question.id}
              columns={[
                { key: "question", header: "题目", render: (question) => question.title || "未命名题目" },
                { key: "language", header: "语言", render: (question) => question.language || "—" },
                { key: "score", header: "得分", render: (question) => (
                  question.score == null ? "待评分" : `${question.score} / ${question.max_score}`
                ) },
              ]}
            />
          ) : <p className="subtle">暂无题目记录。</p>}
        </Panel>
      ))}
      {review.report && (
        <Panel title={`实验总报告 · 第 ${review.report.version_no} 次提交`}>
          <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit" }}>{review.report.body_markdown}</pre>
        </Panel>
      )}
      {review.report_criteria.length > 0 && (
        <Panel title="报告评分项">
          <ul>{review.report_criteria.map((criterion) => (
            <li key={criterion.id}>{criterion.title}（满分 {criterion.max_score}）</li>
          ))}</ul>
        </Panel>
      )}
      <details>
        <summary>技术详情</summary>
        <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(review, null, 2)}</pre>
      </details>
    </div>
  );
}
