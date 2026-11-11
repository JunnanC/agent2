import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { teachingApi } from "@edu/api-client";
import type { Enrollment, Invitation } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import {
  AsyncJobProgress, Button, ConfirmDialog, DataTable, Metric, Modal, Panel,
  RequestStateView, StatusBadge, useToast,
} from "@edu/ui";
import { copyText } from "@/lib/clipboard";
import { ENROLLMENT_STATUS_LABEL, apiErrorMessage, formatDateTime } from "@/lib/format";

const isActiveInvitation = (invitation: Invitation) =>
  ["ACTIVE", "ENABLED"].includes(invitation.status);

export function Enrollments() {
  const { courseId = "" } = useParams();
  const toast = useToast();
  const [plainInvitation, setPlainInvitation] = useState<Invitation | null>(null);
  const [status, setStatus] = useState("PENDING");
  const [search, setSearch] = useState("");
  const [reviewTarget, setReviewTarget] = useState<Enrollment | null>(null);
  const [note, setNote] = useState("");
  const [removeTarget, setRemoveTarget] = useState<Enrollment | null>(null);
  const [importJobId, setImportJobId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const enrollments = useQuery({
    queryKey: keys.teachingEnrollments(courseId, { status: status === "ALL" ? null : status }),
    queryFn: () => teachingApi.enrollments(courseId, { status: status === "ALL" ? undefined : status, page: 1 }),
  });
  const course = useQuery({ queryKey: keys.teachingCourse(courseId), queryFn: () => teachingApi.course(courseId) });
  const invitations = useQuery({
    queryKey: [...keys.invitations(courseId)],
    queryFn: () => teachingApi.invitations(courseId),
  });
  const importJob = useQuery({
    queryKey: [keys.importJob(courseId, importJobId ?? ""), "poll"],
    queryFn: () => teachingApi.imports.get(courseId, importJobId ?? ""),
    enabled: Boolean(importJobId),
    refetchInterval: (query) => {
      const data = query.state.data as { status?: string } | null;
      return ["SUBMITTED", "RUNNING"].includes(String(data?.status ?? "")) ? 4000 : false;
    },
  });

  const rows = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (enrollments.data?.rows ?? []).filter((row) =>
      !query || row.student_name.toLowerCase().includes(query) || row.course_code?.toLowerCase().includes(query));
  }, [enrollments.data, search]);

  const pendingCount = (enrollments.data?.rows ?? []).filter((row) => row.status === "PENDING").length;
  const approvedCount = (enrollments.data?.rows ?? []).filter((row) => ["ACTIVE", "APPROVED"].includes(row.status)).length;
  const monthApplications = useMemo(() => {
    const now = new Date();
    const prefix = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
    return ((enrollments.data?.rows ?? []) as Enrollment[]).filter(
      (row) => typeof row.applied_at === "string" && row.applied_at.startsWith(prefix),
    ).length;
  }, [enrollments.data]);

  const capacity = course.data?.capacity ?? null;
  const used = course.data?.active_enrollment_count ?? approvedCount;

  const activeInvitation = (plainInvitation?.course_id === courseId ? plainInvitation : null) ?? (invitations.data?.rows ?? []).find(isActiveInvitation);

  const review = useMutation({
    mutationFn: (input: { target: Enrollment; decision: "approve" | "reject" }) =>
      teachingApi.reviewEnrollment(courseId, input.target.public_id,
        { decision: input.decision, decision_note: note || undefined },
        input.target.row_version),
    onSuccess: (_data, input) => {
      toast.notify(input.decision === "approve" ? "已通过选课申请" : "已拒绝选课申请");
      setReviewTarget(null);
      setNote("");
      void enrollments.refetch();
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  const remove = useMutation({
    mutationFn: (target: Enrollment) =>
      teachingApi.reviewEnrollment(courseId, target.public_id,
        { decision: "reject", decision_note: "教师移除学生" },
        target.row_version),
    onSuccess: () => {
      toast.notify("已提交移除检查");
      setRemoveTarget(null);
      void enrollments.refetch();
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  const createInvitation = useMutation({
    mutationFn: () => teachingApi.createInvitation(courseId, { valid_days: 30 }),
    onSuccess: async (invitation) => {
      setPlainInvitation({ ...invitation, course_id: courseId, status: "ACTIVE" });
      const copied = await copyText(invitation.code);
      toast.notify(copied ? "新邀请码已生成并复制" : "新邀请码已生成，请在下方手动复制", copied ? "default" : "error");
      void invitations.refetch();
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  const copyInvitation = async () => {
    const code = plainInvitation?.course_id === courseId ? plainInvitation.code : undefined;
    if (!code) {
      createInvitation.mutate();
      return;
    }
    const copied = await copyText(code);
    toast.notify(copied ? "邀请码已复制" : "浏览器未允许复制，请选中下方邀请码手动复制", copied ? "default" : "error");
  };

  const runImportPrecheck = useMutation({
    mutationFn: (file: File) => new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error("文件读取失败"));
      reader.onload = () => resolve(String(reader.result ?? ""));
      reader.readAsText(file);
    }).then((text) => {
      const rowsList = text
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);
      return teachingApi.imports.precheck(courseId, { rows: rowsList, file_name: file.name });
    }),
    onSuccess: (job) => {
      setImportJobId(job.job_id);
      toast.notify("导入预检已提交，正在处理");
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  const jobStages = (importJob.data?.stages ?? []).map((stage, index) => ({
    key: String(index),
    label: stage.name,
    state: stage.status === "COMPLETED" ? "done" as const
      : stage.status === "FAILED" ? "failed" as const
        : stage.status === "RUNNING" ? "running" as const
          : "pending" as const,
  }));
  const jobStatus = importJob.data?.status;
  const jobRunning = ["SUBMITTED", "RUNNING", "PRECHECK_FAILED"].includes(String(jobStatus));

  return (
    <>
      <div className="page-actions align-end">
        <Button onClick={() => fileInputRef.current?.click()}>批量导入</Button>
        <Button variant="primary" disabled={createInvitation.isPending} onClick={() => { void copyInvitation(); }}>
          {createInvitation.isPending ? "生成中…" : "复制邀请码"}
        </Button>
        <input ref={fileInputRef} type="file" accept=".csv,text/csv" hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) runImportPrecheck.mutate(file);
            event.target.value = "";
          }} />
      </div>

      <Panel className="section">
        <RequestStateView loading={enrollments.isLoading && course.isLoading && !rows.length}
          error={enrollments.error ?? course.error}
          onRetry={() => { void enrollments.refetch(); void course.refetch(); }}
          empty={false} emptyState={null}>
          <div className="metric-strip">
            <Metric label="待审核" value={String(pendingCount)} icon="user" sub="需要你处理" />
            <Metric label="已通过" value={String(approvedCount)} icon="users" sub="当前学期" />
            <Metric label="本月申请" value={String(monthApplications)} icon="trending-up" sub="按申请时间统计" />
            <Metric label="课程容量" value={capacity ? `${Math.min(used, capacity)} / ${capacity}` : `${used} 人已加入`}
              icon="gauge" sub={capacity ? `剩余 ${Math.max(0, capacity - used)} 个名额` : "未设置容量上限"} />
          </div>
        </RequestStateView>
      </Panel>

      <Panel title={<><h2>申请列表</h2></>}
        actions={(
          <>
            <button type="button" className={`btn sm${status === "PENDING" ? " primary" : ""}`} onClick={() => setStatus("PENDING")}>待审核</button>
            <button type="button" className={`btn sm${status === "ALL" ? " primary" : ""}`} onClick={() => setStatus("ALL")}>全部状态</button>
          </>
        )}>
        <RequestStateView
          loading={enrollments.isLoading}
          error={enrollments.error}
          onRetry={() => void enrollments.refetch()}
          empty={!rows.length}
          emptyState={(
            <div className="state-block">
              <strong>暂无选课记录</strong>
              <p>{status === "PENDING" ? "当前没有待审核申请。" : "学生提交申请后会出现在这里。"}</p>
            </div>
          )}
        >
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
            <input className="field" style={{ maxWidth: 230 }} type="search"
              placeholder="按学生姓名或课程代码搜索" aria-label="搜索学生"
              value={search} onChange={(event) => setSearch(event.target.value)} />
            <span className="subtle" style={{ marginLeft: "auto" }}>{rows.length} 条记录</span>
          </div>
          <DataTable
            rows={rows}
            rowKey={(row: Enrollment) => row.public_id}
            columns={[
              { key: "student", header: "学生", render: (row: Enrollment) => <strong>{row.student_name}</strong> },
              { key: "course", header: "课程", render: (row: Enrollment) => row.course_title ?? row.course_code ?? "—" },
              { key: "message", header: "申请说明", render: (row: Enrollment) => row.application_message || "—" },
              { key: "applied", header: "申请时间", render: (row: Enrollment) => formatDateTime(row.applied_at) },
              {
                key: "status", header: "状态", render: (row: Enrollment) => (
                  <StatusBadge tone={row.status === "ACTIVE" || row.status === "APPROVED" ? "good" : row.status === "PENDING" ? "warn" : "neutral"}>
                    {ENROLLMENT_STATUS_LABEL[row.status] ?? row.status}
                  </StatusBadge>
                ),
              },
              {
                key: "actions", header: "操作", align: "right", render: (row: Enrollment) => (
                  <div className="table-actions">
                    {row.status === "PENDING"
                      ? <>
                        <button type="button" className="btn sm primary" onClick={() => { setReviewTarget(row); }}>通过</button>
                        <button type="button" className="btn sm" onClick={() => { setReviewTarget(row); }}>拒绝</button>
                      </>
                      : <button type="button" className="btn sm" onClick={() => setRemoveTarget(row)}>移除</button>}
                  </div>
                ),
              },
            ]}
          />
        </RequestStateView>
      </Panel>

      <div className="grid two section"
        style={{ gridTemplateColumns: "minmax(0, 1.1fr) minmax(0, 1fr)" }}>
        <Panel title={<><h2>邀请码</h2>
          {activeInvitation ? <StatusBadge tone="good">已启用</StatusBadge> : <span className="status neutral">暂无启用中</span>}
        </>}>
          {activeInvitation ? (
            <>
              <div style={{
                fontSize: 26, fontWeight: 700, letterSpacing: "0.02em",
                color: "var(--teal)", margin: "8px 0 6px", wordBreak: "break-all",
              }}>{plainInvitation?.course_id === courseId ? plainInvitation.code : "邀请码已隐藏"}</div>
              {!plainInvitation && <p className="subtle">明文仅生成时显示一次。点击“复制邀请码”将生成可分享的新码；已有邀请码保持原有效期。</p>}
              <small>
                仅可用于{course.data?.title ?? "本课程"}课程
                {activeInvitation.expires_at ? `，${formatDateTime(activeInvitation.expires_at)}失效` : "，长期有效"}
              </small>
              <div className="section" style={{ display: "flex", gap: 8, marginTop: 12 }}>
                <Button size="sm" onClick={() => { void copyInvitation(); }}>复制</Button>
                <Button size="sm" disabled={createInvitation.isPending} onClick={() => createInvitation.mutate()}>重新生成</Button>
              </div>
            </>
          ) : (
            <div className="state-block">
              <strong>暂无启用中的邀请码</strong>
              <p>生成邀请码后学生可在加入课程页直接填写加入。</p>
              <Button variant="primary" disabled={createInvitation.isPending} onClick={() => createInvitation.mutate()}>
                {createInvitation.isPending ? "生成中…" : "生成邀请码"}
              </Button>
            </div>
          )}
        </Panel>
        <Panel title={<><h2>学生导入任务</h2><span className="subtle">导入 CSV 学生名单的处理进度，不是实验作业</span>
          <span className={`status ${jobRunning ? "blue" : "neutral"}`}>{jobRunning ? "进行中" : "无进行中作业"}</span>
        </>}>
          {!importJobId || !importJob.data ? (
            <>
              <p className="subtle" style={{ margin: "4px 0 10px" }}>先预检 CSV 中的学号、邮箱和课程分组，再执行导入。</p>
              <Button size="sm" onClick={() => fileInputRef.current?.click()}>选择文件</Button>
              {runImportPrecheck.isPending ? <small style={{ display: "block", marginTop: 8 }}>正在提交预检…</small> : null}
            </>
          ) : (
            <AsyncJobProgress
              status={jobStatus === "COMPLETED" ? "succeeded"
                : jobStatus === "FAILED" || jobStatus === "PRECHECK_FAILED" ? "failed"
                  : "processing"}
              stages={jobStages}
              failureReason="预检失败时请修正 CSV 后重新选择文件提交。"
              onRetry={() => void importJob.refetch()}
            />
          )}
        </Panel>
      </div>

      <Modal open={reviewTarget != null} onClose={() => setReviewTarget(null)} eyebrow="选课审核"
        title={reviewTarget ? `审核 ${reviewTarget.student_name} 的申请` : "审核"}
        actions={(
          <>
            <Button onClick={() => setReviewTarget(null)}>取消</Button>
            <Button variant="danger" disabled={review.isPending}
              onClick={() => { if (reviewTarget) review.mutate({ target: reviewTarget, decision: "reject" }); }}>
              拒绝
            </Button>
            <Button variant="primary" disabled={review.isPending}
              onClick={() => { if (reviewTarget) review.mutate({ target: reviewTarget, decision: "approve" }); }}>
              {review.isPending ? "处理中…" : "通过"}
            </Button>
          </>
        )}>
        {reviewTarget ? (
          <>
            <p className="subtle">申请说明：{reviewTarget.application_message || "（未填写）"}</p>
            <label className="form-label" htmlFor="review-note">审核备注 <span>选填</span></label>
            <textarea id="review-note" className="field" rows={2} value={note} onChange={(event) => setNote(event.target.value)} />
          </>
        ) : null}
      </Modal>

      <ConfirmDialog
        open={removeTarget != null}
        onClose={() => setRemoveTarget(null)}
        onConfirm={() => { if (removeTarget) remove.mutate(removeTarget); }}
        title="移除学生选课？"
        eyebrow="选课管理"
        tone="danger"
        busy={remove.isPending}
        confirmLabel="确认移除"
        description={(
          <>
            <p>将移除 <strong>{removeTarget?.student_name}</strong> 的选课记录。</p>
            <p className="subtle">若学生仍有进行中的实验任务，后端会返回检查失败原因，不会静默删除。</p>
          </>
        )}
      />
    </>
  );
}
