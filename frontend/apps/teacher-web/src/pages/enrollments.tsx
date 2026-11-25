import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { teachingApi } from "@edu/api-client";
import type { Enrollment } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import {
  AsyncJobProgress, Button, ConfirmDialog, DataTable, Metric, Modal, Panel,
  RequestStateView, StatusBadge, useToast,
} from "@edu/ui";
import { DirectInvite } from "@/components/direct-invite";
import { ENROLLMENT_STATUS_LABEL, apiErrorMessage, formatDateTime } from "@/lib/format";
import { allPages } from "@/lib/all-pages";

export function Enrollments() {
  const { courseId = "" } = useParams();
  const toast = useToast();
  const client = useQueryClient();
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
  const roster = useQuery({
    queryKey: keys.teachingEnrollments(courseId, { status: "ACTIVE", scope: "roster" }),
    queryFn: () => allPages((page) => teachingApi.enrollments(courseId, { status: "ACTIVE", page })),
  });
  const course = useQuery({ queryKey: keys.teachingCourse(courseId), queryFn: () => teachingApi.course(courseId) });
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
  const approvedCount = course.data?.active_enrollment_count ?? 0;
  const monthApplications = useMemo(() => {
    const now = new Date();
    const prefix = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
    return ((enrollments.data?.rows ?? []) as Enrollment[]).filter(
      (row) => typeof row.applied_at === "string" && row.applied_at.startsWith(prefix),
    ).length;
  }, [enrollments.data]);

  const capacity = course.data?.capacity ?? null;
  const used = course.data?.active_enrollment_count ?? approvedCount;
  const refreshMembers = () => {
    void client.invalidateQueries({ queryKey: keys.teachingEnrollments(courseId) });
    void client.invalidateQueries({ queryKey: keys.teachingCourses() });
  };

  const review = useMutation({
    mutationFn: (input: { target: Enrollment; decision: "approve" | "reject" }) =>
      teachingApi.reviewEnrollment(courseId, input.target.public_id,
        { decision: input.decision, decision_note: note || undefined },
        input.target.row_version),
    onSuccess: (_data, input) => {
      toast.notify(input.decision === "approve" ? "已通过选课申请" : "已拒绝选课申请");
      setReviewTarget(null);
      setNote("");
      refreshMembers();
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
      refreshMembers();
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

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
    <div className="rail">
      <Panel title={<><h2>入班申请</h2><span className="small">{course.data?.pending_enrollments ?? pendingCount} 人待审</span></>}
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
          {status === "PENDING" ? <ul className="work-list roster-requests">
            {rows.map((row) => <li key={row.public_id} className="work-row">
              <span><strong>{row.student_name}</strong>
                <span className="small">{formatDateTime(row.applied_at)}{row.application_message ? ` · ${row.application_message}` : ""}</span></span>
              <button type="button" className="btn" onClick={() => setReviewTarget(row)}>批准入班</button>
            </li>)}
          </ul> : <DataTable
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
          />}
        </RequestStateView>
      </Panel>

      <section className="panel agenda-panel">
        <div className="panel-head"><div><h2>学生名单</h2><p className="small">{course.data?.active_enrollment_count ?? "—"} 名学生</p></div>
          <Button disabled={runImportPrecheck.isPending} onClick={() => fileInputRef.current?.click()}>导入名单</Button>
          <input ref={fileInputRef} type="file" accept=".csv,text/csv" hidden onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) runImportPrecheck.mutate(file);
            event.target.value = "";
          }} />
        </div>
        <RequestStateView loading={roster.isPending} error={roster.error} onRetry={() => void roster.refetch()}
          empty={!roster.data?.length} emptyState={<p className="empty">本班还没有学生。</p>}>
          <DataTable rows={roster.data ?? []} rowKey={(row: Enrollment) => row.public_id} columns={[
            { key: "name", header: "姓名", render: (row: Enrollment) => <strong>{row.student_name}</strong> },
            { key: "joined", header: "入班时间", render: (row: Enrollment) => formatDateTime(row.activated_at) },
            { key: "action", header: "操作", align: "right", render: (row: Enrollment) =>
              <button type="button" className="text-button" onClick={() => setRemoveTarget(row)}>移除</button> },
          ]} />
        </RequestStateView>
      </section>
      <DirectInvite courseId={courseId} onAdded={refreshMembers} />
      <Panel title={<><h2>学生导入</h2>
        <span className={`status ${jobRunning ? "blue" : "neutral"}`}>{jobRunning ? "进行中" : "无进行中作业"}</span>
      </>}>
        {!importJobId || !importJob.data ? (
          <>
            <p className="subtle" style={{ margin: "4px 0 10px" }}>名单使用 UTF-8 CSV，学号列名为 student_number。系统会匹配已注册的学生账号。</p>
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
      <details className="course-tools"><summary>入班统计</summary>
        <Panel><div className="metric-strip">
          <Metric label="待审核" value={String(course.data?.pending_enrollments ?? pendingCount)} icon="user" />
          <Metric label="已通过" value={String(approvedCount)} icon="users" />
          <Metric label="本月申请" value={String(monthApplications)} icon="trending-up" sub="按当前申请列表统计" />
          <Metric label="课程容量" value={capacity ? `${Math.min(used, capacity)} / ${capacity}` : `${used} 人已加入`} icon="gauge" />
        </div></Panel>
      </details>

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
    </div>
  );
}
