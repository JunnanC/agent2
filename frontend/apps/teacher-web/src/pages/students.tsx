import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { assessmentTeachingApi, teachingApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import {
  DataTable, Metric, Panel, RequestStateView, StatusBadge, EmptyState,
} from "@edu/ui";
import { REPORT_REVIEW_STATUS_LABEL } from "@/lib/format";
import { formatDateTime } from "@/lib/task-format";
import { allPages } from "@/lib/all-pages";

interface ProgressRow {
  public_id: string;
  student_name?: string;
  title: string;
  status: string;
  progress: number;
  score?: string | number | null;
  effective_deadline?: string | null;
  report_required?: boolean;
}

const SUBMITTED_STATUSES = ["SUBMITTED", "UNDER_REVIEW", "COMPLETED", "APPROVED"];

function submissionChip(status: string): { label: string; tone: "good" | "warn" | "neutral" } {
  if (["COMPLETED", "APPROVED"].includes(status)) return { label: "已交 · 已评阅", tone: "good" };
  if (["SUBMITTED", "UNDER_REVIEW"].includes(status)) return { label: "已交卷", tone: "good" };
  if (["IN_PROGRESS", "REPORT_DRAFT", "READY"].includes(status)) return { label: "进行中", tone: "warn" };
  return { label: "未交", tone: "neutral" };
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
  const [search, setSearch] = useState("");

  const progress = useQuery({
    queryKey: keys.teachingProgress(courseId, {}),
    queryFn: () => allPages(page => teachingApi.progress(courseId, { page, page_size: 100 })),
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
    return (progress.data ?? []).filter((row: ProgressRow) =>
      !query || row.student_name?.toLowerCase().includes(query) || row.title.toLowerCase().includes(query)
        || String(row.score ?? "").toLowerCase().includes(query));
  }, [progress.data, search]);

  const inProgressCount = (progress.data ?? []).filter((row) => ["IN_PROGRESS", "REPORT_DRAFT", "READY"].includes(row.status)).length;
  const staleCount = (progress.data ?? []).filter((row) => {
    if (["COMPLETED", "SUBMITTED", "UNDER_REVIEW", "APPROVED"].includes(row.status)) return false;
    const deadline = row.effective_deadline ? new Date(row.effective_deadline).getTime() : 0;
    return deadline > 0 && deadline < Date.now() - 7 * 86_400_000;
  }).length;
  const failedCount = (progress.data ?? []).filter((row) => row.status === "FAILED").length;
  const pendingReviewTotal = typeof pendingReviews.data?.total === "number"
    ? pendingReviews.data?.total
    : (pendingReviews.data?.rows.length ?? 0);

  const byExperiment = useMemo(() => {
    const grouped = new Map<string, Map<string, string>>();
    (progress.data ?? []).forEach((row: ProgressRow) => {
      const name = row.student_name ?? "—";
      const inner = grouped.get(row.title) ?? new Map<string, string>();
      const previous = inner.get(name);
      const advance = !previous
        || (!SUBMITTED_STATUSES.includes(previous) && SUBMITTED_STATUSES.includes(row.status));
      inner.set(name, advance ? row.status : previous ?? row.status);
      grouped.set(row.title, inner);
    });
    return [...grouped.entries()].map(([title, inner]) => {
      const names = (statuses: string[]) => [...inner.entries()]
        .filter(([, status]) => statuses.includes(status))
        .map(([name]) => name);
      const inProgress = names(["IN_PROGRESS", "REPORT_DRAFT", "READY"]);
      const notStarted = names(["ASSIGNED", "NOT_STARTED"]);
      const submitted = inner.size - inProgress.length - notStarted.length;
      return { title, total: inner.size, submitted, inProgress, notStarted };
    }).sort((left, right) => left.title.localeCompare(right.title, "zh-CN"));
  }, [progress.data]);

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

      <Panel className="section" title={<><h2>按实验看谁没交</h2><span className="subtle">同一名学生的多条记录只算一次</span></>}>
        {byExperiment.length ? <div style={{ display: "grid", gap: 10 }}>
          {byExperiment.map((group) => <div key={group.title} className="item" style={{ display: "block" }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
              <strong>{group.title}</strong>
              <span className="subtle">已交齐 {group.submitted} / {group.total} 人</span>
              <StatusBadge tone={group.inProgress.length + group.notStarted.length ? "warn" : "good"}>
                {group.inProgress.length + group.notStarted.length ? `未交齐 ${group.inProgress.length + group.notStarted.length} 人` : "全部已交齐"}
              </StatusBadge>
            </div>
            {group.inProgress.length > 0 && <p className="subtle" style={{ margin: "6px 0 0" }}>进行中（已进入、未交齐）：{group.inProgress.join("、")}</p>}
            {group.notStarted.length > 0 && <p className="subtle" style={{ margin: "2px 0 0" }}>未开始：{group.notStarted.join("、")}</p>}
          </div>)}
        </div> : <EmptyState title="还没有学生记录" hint="实验发布并分配后才出现学生过程记录。" />}
      </Panel>

      <Panel title={<><h2>学生进度与风险</h2></>}
        actions={(
            <input className="field" style={{ width: 230 }} type="search" placeholder="搜索学生、实验或成绩"
            aria-label="搜索学生、实验或成绩" value={search} onChange={(event) => setSearch(event.target.value)} />
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
              { key: "score", header: "成绩", render: (row: ProgressRow) => row.score ?? "待评分" },
              {
                key: "progress", header: "进度", width: 170, render: (row: ProgressRow) => (
                  <div style={{ minWidth: 130 }}>
                    <div className="progress"><span style={{ width: `${row.progress}%` }} /></div>
                    <small style={{ display: "block", marginTop: 3 }}>{row.progress}%</small>
                  </div>
                ),
              },
              { key: "deadline", header: "截止", render: (row: ProgressRow) => (
                row.effective_deadline
                  ? (new Date(row.effective_deadline).getTime() < Date.now()
                    ? `已过截止 ${formatDateTime(row.effective_deadline)}`
                    : `距截止 ${formatDateTime(row.effective_deadline)}`)
                  : "无截止时间"
              ) },
              {
                key: "submission", header: "提交状态", render: (row: ProgressRow) => {
                  const chip = submissionChip(row.status);
                  return <div>
                    <StatusBadge tone={chip.tone}>{chip.label}</StatusBadge>
                    <small style={{ display: "block", marginTop: 3 }}>{workspaceChip(row.status).label}</small>
                  </div>;
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
            ]}
          />
        </RequestStateView>
      </Panel>
    </>
  );
}
