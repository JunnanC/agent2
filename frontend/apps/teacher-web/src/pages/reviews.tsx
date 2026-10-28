import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import DOMPurify from "dompurify";
import { teachingApi } from "@edu/api-client";
import type { ReviewDetail, ReviewSummary } from "@edu/api-client";
import { ApiError } from "@edu/auth-client";
import { keys } from "@edu/query-keys";
import {
  Button, Drawer, EmptyState, Modal, Panel, Breadcrumbs, RequestStateView, StatusBadge, useToast,
} from "@edu/ui";
import { REVIEW_STATUS_LABEL, apiErrorMessage, formatDateTime } from "@/lib/format";

type EvidenceView = { type: "preview" | "workspace" | "replay" | "similarity"; data: unknown } | null;

const EVIDENCE_TITLES: Record<NonNullable<EvidenceView>["type"], string> = {
  preview: "提交预览",
  workspace: "工作区快照",
  replay: "操作回放",
  similarity: "相似度检测",
};

function sanitizeReportHtml(html: string): string {
  // 学生提交的富文本可含内联结构；经 DOMPurify 清洗后再注入，防 XSS。
  return DOMPurify.sanitize(html);
}

export function Reviews() {
  const { courseId = "" } = useParams();
  const toast = useToast();
  const [statusFilter, setStatusFilter] = useState("PENDING");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<ReviewSummary | null>(null);

  const reviews = useQuery({
    queryKey: keys.reviews(courseId, { status: statusFilter === "ALL" ? null : statusFilter }),
    queryFn: () => teachingApi.reviews(courseId, { status: statusFilter === "ALL" ? undefined : statusFilter }),
  });

  const detail = useQuery({
    queryKey: keys.review(courseId, selected?.public_id ?? ""),
    queryFn: () => teachingApi.review(courseId, selected?.public_id ?? ""),
    enabled: Boolean(selected),
  });

  const [scores, setScores] = useState<Record<string, string>>({});
  const [annotation, setAnnotation] = useState("");

  const filledScoreEntries = Object.entries(scores).filter(([, text]) => text.trim() !== "");
  const invalidScores = filledScoreEntries.some(([, text]) => !Number.isFinite(Number(text)));

  const saveScores = useMutation({
    mutationFn: async (review: ReviewDetail) => {
      const payload = filledScoreEntries.map(([criterionId, text]) => ({ criterion_id: criterionId, score: Number(text) }));
      return teachingApi.saveCriterionScores(courseId, review.public_id, { scores: payload }, review.row_version);
    },
    onSuccess: () => {
      toast.notify("评分已保存");
      void detail.refetch();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.payload?.code === "AUTO_CHECK_PENDING") {
        toast.notify("自动检查尚未完成，评分暂时无法保存，请稍后。", "error");
      } else {
        toast.notify(apiErrorMessage(error), "error");
      }
    },
  });

  const addAnnotation = useMutation({
    /* 批注锚定报告全文：REPORT_TEXT 锚点要求合法 TEXT_RANGE 且落在报告长度内 */
    mutationFn: (review: ReviewDetail) => {
      const reportId = review.submission?.report_id ?? "";
      const reportLength = review.submission?.report_markdown?.length ?? 0;
      return teachingApi.addAnnotation(courseId, review.public_id, {
        body: annotation.trim(),
        target_ref: reportId,
        anchor: { kind: "TEXT_RANGE", start: 0, end: reportLength },
      }, review.row_version);
    },
    onSuccess: () => {
      toast.notify("批注已保存");
      setAnnotation("");
      void detail.refetch();
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  const decide = useMutation({
    mutationFn: (input: { review: ReviewDetail; decision: "approve" | "return" }) =>
      teachingApi.decideReview(courseId, input.review.public_id, { decision: input.decision }, input.review.row_version),
    onSuccess: (_data, input) => {
      toast.notify(input.decision === "approve" ? "评审已通过并通知学生" : "已退回报告并通知学生");
      setSelected(null);
      void reviews.refetch();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.payload?.code === "SIMILARITY_UNAVAILABLE") {
        toast.notify("相似度服务暂不可用，无法完成决策", "error");
      } else if (error instanceof ApiError && error.payload?.code === "AUTO_CHECK_PENDING") {
        toast.notify("自动检查尚未完成，请稍后重试", "error");
      } else if (error instanceof ApiError && error.payload?.code === "REVIEW_VALIDATION_ERROR") {
        toast.notify("请先为每个评分标准保存评分，再进行决策", "error");
      } else {
        toast.notify(apiErrorMessage(error), "error");
      }
    },
  });

  const rows = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (reviews.data?.rows ?? []).filter((row: ReviewSummary) =>
      !query || row.student_name.toLowerCase().includes(query) || row.publication_title?.toLowerCase().includes(query));
  }, [reviews.data, search]);

  const detailData: ReviewDetail | undefined = detail.data;
  const [evidence, setEvidence] = useState<EvidenceView>(null);

  /* 详情载入/刷新时用服务端已存分数重置本地输入（同时避免切换学生后残留上一份打分） */
  useEffect(() => {
    if (!detailData) {
      setScores({});
      return;
    }
    const saved: Record<string, string> = {};
    for (const criterion of detailData.rubric?.criteria ?? []) {
      if (criterion.score != null) saved[criterion.public_id] = String(criterion.score);
    }
    setScores(saved);
  }, [detailData]);
  const resolveTaskId = (): string => detailData?.task_id ?? selected?.task_id ?? "";

  const previewMutation = useMutation({
    mutationFn: () => teachingApi.submissionPreview(courseId, resolveTaskId()),
    onSuccess: (data) => setEvidence({ type: "preview", data }),
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });
  const workspaceMutation = useMutation({
    mutationFn: () => teachingApi.studentTaskWorkspace(courseId, resolveTaskId()),
    onSuccess: (data) => setEvidence({ type: "workspace", data }),
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });
  const replayMutation = useMutation({
    mutationFn: () => teachingApi.operationReplay(courseId, resolveTaskId()),
    onSuccess: (data) => setEvidence({ type: "replay", data }),
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });
  const similarityMutation = useMutation({
    mutationFn: () => teachingApi.startSimilarityRun(courseId, resolveTaskId()),
    onSuccess: (data) => {
      toast.notify("相似度检测已提交，稍后刷新查看结果");
      setEvidence({ type: "similarity", data });
      window.setTimeout(() => { void detail.refetch(); }, 4000);
      window.setTimeout(() => { void detail.refetch(); }, 10000);
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  return (
    <>
      <Breadcrumbs items={[{ label: "教师门户" }, { label: "课程" }]} current="评审中心" />
      <div className="page-actions align-end">
        <button type="button" className={`btn sm${statusFilter === "PENDING" ? " primary" : ""}`} onClick={() => setStatusFilter("PENDING")}>待评审</button>
        <button type="button" className={`btn sm${statusFilter === "ALL" ? " primary" : ""}`} onClick={() => setStatusFilter("ALL")}>全部记录</button>
        <span className={`status ${(reviews.data?.rows ?? []).filter((row: ReviewSummary) => row.status === "PENDING").length ? "warn" : "good"}`}>
          {(reviews.data?.rows ?? []).filter((row: ReviewSummary) => row.status === "PENDING").length} 份待处理
        </span>
      </div>
      <Panel title={<><h2>报告提交</h2><span className="subtle">先看提交预览和自动检查，再进入评分。</span></>}
        actions={(
          <input className="field" style={{ width: 220 }} type="search" placeholder="搜索学生或实验"
            aria-label="搜索学生或实验" value={search} onChange={(event) => setSearch(event.target.value)} />
        )}>
        <RequestStateView
          loading={reviews.isLoading}
          error={reviews.error}
          onRetry={() => void reviews.refetch()}
          empty={!rows.length}
          emptyState={<EmptyState title="暂无评审记录" hint="学生提交报告后，提交会进入评审队列。" />}
        >
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>学生</th><th>实验</th><th>提交时间</th><th>自动检查</th><th>状态</th><th /></tr></thead>
              <tbody>
                {rows.map((row: ReviewSummary) => (
                  <tr key={row.public_id}>
                    <td><strong>{row.student_name}</strong></td>
                    <td>{row.publication_title ?? row.task_id}</td>
                      <td>{formatDateTime(row.created_at)}</td>
                      <td>{row.auto_check_result ?? "—"}</td>
                      <td>
                        <StatusBadge tone={row.status === "PENDING" ? "warn" : row.status === "RETURNED" ? "bad" : "good"}>
                          {REVIEW_STATUS_LABEL[row.status] ?? row.status}
                        </StatusBadge>
                      </td>
                      <td className="table-actions">
                        <button type="button" className={`btn sm${row.status === "PENDING" ? " primary" : ""}`}
                          onClick={() => setSelected(row)}>
                          {row.status === "PENDING" ? "开始评审" : "查看评审"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </RequestStateView>
        </Panel>

      <Drawer open={selected != null} onClose={() => setSelected(null)} title={detailData ? `${detailData.student_name} · ${detailData.publication_title ?? ""}` : "评审详情"}>
        {detail.isLoading || !detailData ? (
          <EmptyState title="正在载入评审详情" />
        ) : (
          <>
            <div className="review-section" style={{ marginBottom: 12 }}>
              <span className="eyebrow">报告内容</span>
              {detailData.submission?.report_html
                ? <div className="report-submission-copy" dangerouslySetInnerHTML={{ __html: sanitizeReportHtml(detailData.submission.report_html) }} />
                : <div className="report-submission-copy">该提交尚未包含报告内容。</div>}
            </div>
            <div className="review-section" style={{ marginBottom: 12 }}>
              <span className="eyebrow">工作区证据</span>
              <div className="evidence-row"><span>执行记录</span><button type="button" className="btn sm" onClick={() => previewMutation.mutate()} disabled={previewMutation.isPending}>{previewMutation.isPending ? "载入中…" : "查看"}</button></div>
              <div className="evidence-row"><span>工作区快照</span><button type="button" className="btn sm" onClick={() => workspaceMutation.mutate()} disabled={workspaceMutation.isPending}>{workspaceMutation.isPending ? "载入中…" : "查看"}</button></div>
              <div className="evidence-row"><span>操作回放</span><button type="button" className="btn sm" onClick={() => replayMutation.mutate()} disabled={replayMutation.isPending}>{replayMutation.isPending ? "载入中…" : "查看"}</button></div>
              <div className="evidence-row"><span>相似度</span>
                <button type="button" className="btn sm" disabled={similarityMutation.isPending || detailData.similarity_ratio != null}
                  onClick={() => similarityMutation.mutate()}>
                  {detailData.similarity_ratio != null
                    ? `已完成 ${Math.round(detailData.similarity_ratio * 100)}%`
                    : similarityMutation.isPending ? "检测中…" : "发起检测"}
                </button>
              </div>
            </div>

            <div className="review-section" style={{ marginBottom: 12 }}>
              <div className="panel-title"><h3>Rubric 评分</h3><span className="status blue">criterion-scores</span></div>
              {(detailData.rubric?.criteria ?? []).map((criterion) => (
                <label className="score-row" key={criterion.public_id}>
                  <span style={{ minWidth: 0 }}>
                    <strong>{criterion.title}</strong>
                    <small>{criterion.description}</small>
                  </span>
                  <input className="field" type="number" inputMode="decimal" step="any"
                    min={0} max={criterion.max_score}
                    placeholder={`0 ~ ${criterion.max_score} 分`}
                    aria-label={`${criterion.title}（满分 ${criterion.max_score} 分）`}
                    value={scores[criterion.public_id] ?? ""}
                    onChange={(event) => {
                      const text = event.target.value;
                      setScores((prev) => {
                        const next = { ...prev };
                        if (text.trim() === "") delete next[criterion.public_id];
                        else next[criterion.public_id] = text;
                        return next;
                      });
                    }} />
                </label>
              ))}
              <Button size="sm" disabled={saveScores.isPending || !detailData.rubric?.criteria?.length
                  || invalidScores || filledScoreEntries.length === 0}
                title={invalidScores ? "评分必须是数字" : "先填写分数再保存"}
                onClick={() => saveScores.mutate(detailData)}>
                {saveScores.isPending ? "保存中…" : "保存评分"}
              </Button>
            </div>

            <div className="review-section" style={{ marginBottom: 12 }}>
              <label className="form-label" htmlFor="review-annotation">报告批注</label>
              <textarea id="review-annotation" className="field" rows={3} value={annotation} onChange={(event) => setAnnotation(event.target.value)} />
              <Button size="sm" disabled={!annotation.trim() || !detailData.submission?.report_id
                  || (detailData.submission?.report_markdown?.length ?? 0) === 0 || addAnnotation.isPending}
                onClick={() => addAnnotation.mutate(detailData)}>
                {!detailData.submission?.report_id ? "仅支持批注报告提交" : addAnnotation.isPending ? "保存中…" : "添加批注"}
              </Button>
              <div className="annotation-list section" style={{ marginTop: 6 }}>
                {(detailData.annotations ?? []).filter((item) => !item.revoked).map((item) => (
                  <div className="annotation-chip" key={item.id}>📝 {item.body}</div>
                ))}
              </div>
            </div>

            <div className="review-actions" style={{ display: "flex", gap: 8 }}>
              <Button variant="danger" disabled={decide.isPending}
                onClick={() => decide.mutate({ review: detailData, decision: "return" })}>退回修改</Button>
              <Button variant="primary" disabled={decide.isPending}
                onClick={() => decide.mutate({ review: detailData, decision: "approve" })}>
                {decide.isPending ? "提交中…" : "通过评审"}
              </Button>
            </div>
          </>
        )}
      </Drawer>

      <Modal
        open={evidence != null}
        onClose={() => setEvidence(null)}
        eyebrow="评审证据"
        title={evidence ? EVIDENCE_TITLES[evidence.type] : ""}
        wide
        actions={<Button onClick={() => setEvidence(null)}>关闭</Button>}
      >
        {evidence?.type === "replay" && Array.isArray(evidence.data) ? (
          (evidence.data as Array<Record<string, unknown>>).length ? (
            (evidence.data as Array<Record<string, unknown>>).map((event, index) => (
              <div className="status-line" key={String(event.public_id ?? index)}>
                {String(event.occurred_at ?? "")} · {String(event.event_type ?? "")} · {String(event.result_summary ?? "")}
              </div>
            ))
          ) : (
            <p className="subtle">该任务还没有工作区操作记录。</p>
          )
        ) : (
          <div className="report-submission-copy" style={{ whiteSpace: "pre-wrap" }}>
            {JSON.stringify(evidence?.data ?? {}, null, 2)}
          </div>
        )}
      </Modal>
    </>
  );
}
