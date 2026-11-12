import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { reportApi, taskApi } from "@edu/api-client";
import type { Task, WorkspaceSession } from "@edu/api-client";
import { ApiError } from "@edu/auth-client";
import { keys } from "@edu/query-keys";
import { AsyncJobProgress, Button, ErrorState, Modal, Panel, RequestStateView, StatusBadge, useToast } from "@edu/ui";
import type { JobStage } from "@edu/ui";
import { storeWorkspaceSession } from "@/lib/workspace-session";
import { actionLabel, formatDateTime, taskStatusLabel, taskStatusTone } from "@/lib/task-format";
import { CourseAgent } from "@/components/course-agent";

const WORKFLOW_STATUS_ORDER = ["ASSIGNED", "PROVISIONING", "READY", "IN_PROGRESS", "REPORT_DRAFT", "SUBMITTED", "UNDER_REVIEW", "COMPLETED"];

/* 工作区准备流水线的六个阶段(与后端 ProvisioningJob.Stage 对应) */
const STAGE_LABELS: Record<string, string> = {
  QUOTA_CHECK: "配额检查",
  IMAGE_PREPARE: "镜像准备",
  CREATE: "创建工作区",
  NETWORK_ATTACH: "挂载运行时网络",
  BOOT_PROBE: "启动探活",
  WORKSPACE_READY: "工作区就绪",
};

export function TaskDetail() {
  const { taskId = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [extensionOpen, setExtensionOpen] = useState(false);
  const [extensionReason, setExtensionReason] = useState("");
  const [restartConfirm, setRestartConfirm] = useState(false);
  const [provisionOpen, setProvisionOpen] = useState(false);
  const autoEnteredRef = useRef(false);

  const task = useQuery({
    queryKey: keys.task(taskId), queryFn: () => taskApi.detail(taskId),
    refetchInterval: (query) => query.state.data?.status === "PROVISIONING" ? 2000 : false,
  });
  const hasReview = !task.data?.assessment_available && ["SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "REPORT_DRAFT", "IN_PROGRESS", "ARCHIVING", "DESTROYING", "COMPLETED"].includes(task.data?.status ?? "");
  const reviewResult = useQuery({
    queryKey: keys.reviewResult(taskId), queryFn: () => reportApi.reviewResult(taskId), enabled: hasReview, retry: false,
  });
  const reviewedRound = reviewResult.data?.rounds.find(round => round.decision);
  const provisioning = useQuery({
    queryKey: keys.provisioningJob(taskId),
    queryFn: () => taskApi.provisioningJob(taskId),
    refetchInterval: (query) => {
      const data = query.state.data as Record<string, unknown> | null;
      const status = String(data?.["status"] ?? "");
      /* 后端 job 状态只有 QUEUED/RUNNING/RETRY/PASSED/FAILED/CANCELLED,QUEUED 阶段也必须持续轮询 */
      return ["QUEUED", "SUBMITTED", "RUNNING", "RETRY"].includes(status) ? 4000 : false;
    },
    enabled: task.data?.status === "PROVISIONING",
  });

  const invalidate = () => { void task.refetch(); };

  const actionMutation = useMutation({
    mutationFn: (input: { action: string }): Promise<Task | { task: Task; session: WorkspaceSession }> => {
      const ifMatch = task.data?.row_version ?? "";
      /* 幂等键必须随行版本变化:同一任务可能反复 start/retry,固定键会被后端幂等层重放旧响应,
         提示"成功"但任务状态不变,弹窗会永远停留在"正在提交开通请求…" */
      const reuseKey = `task-${input.action}-${taskId}-${ifMatch}`;
      if (input.action === "start") return taskApi.start(taskId, ifMatch, reuseKey);
      if (input.action === "retry") return taskApi.retry(taskId, ifMatch, reuseKey);
      if (input.action === "enter") {
        return taskApi.enter(taskId, ifMatch, reuseKey);
      }
      return taskApi.complete(taskId, ifMatch);
    },
    onMutate: (input) => {
      if (input.action === "start" || input.action === "retry") {
        autoEnteredRef.current = false;
        setProvisionOpen(true);
      }
    },
    onSuccess: (data, input) => {
      toast.notify(actionLabel(input.action) === "进入工作台" ? "正在打开工作台" : `${actionLabel(input.action)}成功`);
      invalidate();
      if (input.action === "enter" && "session" in data) {
        const session = data.session;
        if (session?.public_id && session.workspace_token) {
          storeWorkspaceSession(taskId, {
            session_id: session.public_id,
            token: session.workspace_token,
            expires_at: session.expires_at ?? null,
            status: session.status,
            workspace_urls: session.workspace_urls,
            capabilities: session.capabilities,
          });
        }
        navigate(`/experiments/${taskId}/workbench`);
      }
    },
    onError: (error) => {
      const payload = (error as { payload?: { message?: string } }).payload;
      toast.notify(payload?.message ?? "操作失败，请稍后重试。", "error");
      setProvisionOpen(false);
    },
  });

  const extensionMutation = useMutation({
    mutationFn: () => taskApi.requestExtension(taskId, { reason: extensionReason.trim() }, task.data?.row_version ?? ""),
    onSuccess: () => { toast.notify("延期申请已提交，等待审核"); setExtensionOpen(false); setExtensionReason(""); invalidate(); },
    onError: (error) => toast.notify((error as { payload?: { message?: string } }).payload?.message ?? "提交失败", "error"),
  });

  const jobProgressState = (status?: string): "succeeded" | "failed" | "submitted" | "processing" =>
    ["COMPLETED", "PASSED", "SUCCEEDED"].includes(status ?? "") ? "succeeded"
      : status === "FAILED" ? "failed"
        : status === "SUBMITTED" ? "submitted" : "processing";

  const stageProgressState = (status?: string): JobStage["state"] =>
    status === "done" || status === "SUCCEEDED" ? "done"
      : status === "failed" || status === "FAILED" ? "failed"
        : status === "running" || status === "RUNNING" ? "running" : "pending";

  const jobStages = (): { key: string; label: string; state: JobStage["state"]; detail?: string }[] => {
    const job = provisioning.data as
      | { status?: string; stages?: Array<{ stage?: string; name?: string; status?: string; error_code?: string }> }
      | null;
    /* 后端 stages 是逐条事件行(STARTED/PASSED/FAILED),按阶段去重取最新状态,保证行数=可见阶段数 */
    const latest = new Map<string, { stage?: string; name?: string; status?: string; error_code?: string }>();
    for (const stage of job?.stages ?? []) {
      latest.set(stage.stage ?? `event-${latest.size}`, stage);
    }
    return [...latest.values()].map((stage, index) => ({
      key: String(index),
      label: STAGE_LABELS[stage.stage ?? ""] ?? stage.name ?? `阶段 ${index + 1}`,
      state: stageProgressState(stage.status),
      detail: stage.error_code || undefined,
    }));
  };

  /* 失败原因:任务行 current_failure 为空时,取 provisioning job 挂的失败记录(error_code + message) */
  const failureReasonText = (): string | undefined => {
    const taskFailure = current?.current_failure;
    const jobFailure = (provisioning.data as { failure?: { message?: string; error_code?: string } | null } | null)?.failure;
    const message = jobFailure?.message || taskFailure?.message || "";
    const code = jobFailure?.error_code || taskFailure?.code || "";
    if (message && code && !message.includes(code)) return `${message}（${code}）`;
    return message || (code || undefined);
  };

  // 弹窗流程：任务就绪后自动进入工作台；job 成功但任务仍为 PROVISIONING 时先热刷新任务
  useEffect(() => {
    if (!provisionOpen) return;
    const taskStatus = task.data?.status ?? "";
    const jobStatus = String((provisioning.data as Record<string, unknown> | null)?.["status"] ?? "");
    if (taskStatus === "PROVISIONING" && ["SUCCEEDED", "PASSED", "COMPLETED"].includes(jobStatus) && !task.isFetching) {
      void task.refetch();
    }
    if (taskStatus === "READY" && !autoEnteredRef.current) {
      autoEnteredRef.current = true;
      setProvisionOpen(false);
      actionMutation.mutate({ action: "enter" });
      return;
    }
    /* 操作已受理但任务没有进入准备状态且无装载进度可展示时收起弹窗,避免永远停留在"正在提交开通请求…" */
    if (!task.isFetching && !actionMutation.isPending && taskStatus !== "PROVISIONING" && !provisioning.data) {
      setProvisionOpen(false);
    }
  }, [provisionOpen, task, provisioning.data, actionMutation]);

  if (task.isLoading) {
    return (
      <div className="app-shell"><Panel>
        <RequestStateView loading error={null} empty={false} emptyState={null} />
      </Panel></div>
    );
  }
  if (task.error) {
    return (
      <div className="app-shell"><Panel>
        <ErrorState error={task.error} onRetry={() => void task.refetch()} title="无法读取任务" />
      </Panel></div>
    );
  }
  const current = task.data;
  if (!current) return null;

  const workflowIndex = WORKFLOW_STATUS_ORDER.indexOf(current.status);

  return (
    <>
      <div className="crumb">
        <Link className="crumb-link" to="/">学生门户</Link>　/　
        <Link className="crumb-link" to="/experiments">实验任务</Link>　/　<b>{current.title}</b>
      </div>
      <div className="page-actions align-end">
        {current.assessment_available ? <Link className="btn primary" to={`/experiments/${taskId}/assessment`}>进入实验答题</Link> : null}
        {!current.assessment_available && current.allowed_actions.includes("enter") && !current.blockers.length ? (
          <Button variant="primary" onClick={() => {
            if (current.status === "ASSIGNED" && !actionMutation.isPending) {
              autoEnteredRef.current = false;
              setProvisionOpen(true);
              actionMutation.mutate({ action: "start" });
              return;
            }
            actionMutation.mutate({ action: "enter" });
          }}
            disabled={actionMutation.isPending}>
            {actionMutation.isPending ? "打开中…" : "进入实验工作台"}
          </Button>
        ) : null}
      </div>

      <Panel>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center" }}>
          <StatusBadge tone={taskStatusTone(current.status)}>{taskStatusLabel(current.status)}</StatusBadge>
          <span className="subtle">开放 {formatDateTime(current.window_start)} · 截止 {formatDateTime(current.effective_deadline)}</span>
        </div>
        {current.blockers.length ? (
          <div className="section" style={{ marginTop: 10 }}>
            <div className="join-course-note" style={{ background: "var(--amber-soft)", color: "var(--amber)" }}>
              <span>!</span>
              <div>
                <strong>下一步阻塞</strong>
                {current.blockers.map((blocker, index) => (
                  <p key={index} style={{ margin: "2px 0" }}>
                    {blocker.reason ?? blocker.detail ?? blocker.code ?? "请稍后重试"}
                    {blocker.detail ? ` · ${blocker.detail}` : ""}
                  </p>
                ))}
              </div>
            </div>
          </div>
        ) : null}
        <div className="section actions" style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
          {current.allowed_actions
            .filter((action) => !current.assessment_available && !["enter", "extension", "request_extension"].includes(action))
            .map((action) => (
              <Button key={action}
                variant={action === "start" || action === "retry" ? "primary" : "default"}
                onClick={() => {
                  if (action === "start") {
                    actionMutation.mutate({ action });
                  } else if (action === "retry") {
                    setRestartConfirm(true);
                  }
                }}
                disabled={actionMutation.isPending}>
                {actionLabel(action)}
              </Button>
            ))}
          {current.allowed_actions.includes("extension") || current.allowed_actions.includes("request_extension")
            ? <Button onClick={() => setExtensionOpen(true)}>申请延期</Button> : null}
        </div>
      </Panel>

      {current.status === "PROVISIONING" ? (
        <Panel className="section" title={<h2>工作区准备进度</h2>}>
          <RequestStateView loading={provisioning.isLoading && !provisioning.data}
            error={provisioning.error}
            onRetry={() => void provisioning.refetch()}
            empty={!provisioning.data}
            emptyState={<div className="state-block"><strong>尚未开始装载</strong></div>}>
            <AsyncJobProgress
              status={jobProgressState(provisioning.data?.["status"] as string | undefined)}
              stages={jobStages()}
              failureReason={failureReasonText()}
              onRetry={() => { void provisioning.refetch(); }}
            />
          </RequestStateView>
        </Panel>
      ) : null}

      <div className="grid two section">
        <Panel title={<h2>完成路径</h2>}>
          <div className="workflow-list">
            {WORKFLOW_STATUS_ORDER.map((status, index) => {
              const isDone = workflowIndex > index;
              const isCurrent = workflowIndex === index;
              return (
                <div key={status} className={`workflow-step${isDone ? " complete" : isCurrent ? " current" : ""}`}>
                  <span aria-hidden="true">{isDone ? "✓" : index + 1}</span>
                  <div>
                    <strong>{taskStatusLabel(status)}</strong>
                    {isCurrent ? <small>当前阶段</small> : null}
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>
        <Panel title={<h2>任务信息</h2>}>
          <div style={{ display: "grid", gap: 8, fontSize: 13 }}>
            <div><span className="eyebrow">完成条件</span><strong style={{ display: "block" }}>
              {current.report_required ? "完成工作区任务并通过测试，提交实验报告。" : "完成工作区任务并提交结果。"}
            </strong></div>
            <div><span className="eyebrow">延后处理</span><strong style={{ display: "block" }}>
              {current.allowed_actions.includes("extension") ? "可申请延期" : "不可申请延期"}
            </strong></div>
            <div><span className="eyebrow">当前版本</span><small>row_version {current.row_version.slice(0, 12)}…</small></div>
          </div>
        </Panel>
      </div>

      {hasReview && (reviewedRound || ["SUBMITTED", "UNDER_REVIEW", "ARCHIVING", "DESTROYING", "COMPLETED"].includes(current.status)) ? (
        <Panel className="section" title={<h2>评审结果</h2>}>
          <RequestStateView loading={reviewResult.isLoading} error={reviewResult.error instanceof ApiError && reviewResult.error.status === 404 ? null : reviewResult.error}
            onRetry={() => void reviewResult.refetch()} empty={!reviewedRound}
            emptyState={<p className="subtle">教师正在评审，评分与批注将在评审完成后显示。</p>}>
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <StatusBadge tone={reviewedRound?.decision?.decision === "APPROVE" ? "good" : "warn"}>
                {reviewedRound?.decision?.decision === "APPROVE" ? "评审通过" : "退回修改"}
              </StatusBadge>
              <strong>{reviewResult.data?.effective_score ?? reviewedRound?.decision?.score} 分</strong>
            </div>
            <dl>
              {reviewedRound?.scores?.criteria.map(criterion => (
                <div key={criterion.public_id} style={{ display: "flex", gap: 16, marginTop: 8 }}>
                  <dt>{criterion.title}</dt><dd style={{ margin: 0 }}>{criterion.score} / {criterion.max_score}</dd>
                </div>
              ))}
            </dl>
            {reviewedRound?.decision?.feedback ? <p>{reviewedRound.decision.feedback}</p> : null}
            {reviewedRound?.annotations.length ? <h3>教师批注</h3> : null}
            {reviewedRound?.annotations.map(annotation => <p key={annotation.public_id}>{annotation.body}</p>)}
            {reviewResult.data?.allowed_actions?.includes("REVISE_AND_RESUBMIT") && current.allowed_actions.includes("enter") &&
              <Link className="btn primary" to={`/experiments/${taskId}/workbench`}>修改报告并重新提交</Link>}
          </RequestStateView>
        </Panel>
      ) : null}

      {current.course_id && <CourseAgent key={taskId} courseId={current.course_id} taskId={taskId} />}

      <Modal open={extensionOpen} onClose={() => setExtensionOpen(false)} eyebrow="申请延期"
        title="申请任务延期"
        actions={(
          <>
            <Button onClick={() => setExtensionOpen(false)}>取消</Button>
            <Button variant="primary" disabled={!extensionReason.trim() || extensionMutation.isPending}
              onClick={() => extensionMutation.mutate()}>
              {extensionMutation.isPending ? "提交中…" : "提交延期申请"}
            </Button>
          </>
        )}>
        <label className="form-label" htmlFor="extension-reason">申请原因 <span>必填</span></label>
        <textarea id="extension-reason" className="field" rows={3} value={extensionReason}
          onChange={(event) => setExtensionReason(event.target.value)}
          placeholder="说明延期理由，教师审核后生效" />
      </Modal>

      <Modal open={restartConfirm} onClose={() => setRestartConfirm(false)} eyebrow="实验任务"
        title="确认重试任务？"
        actions={(
          <>
            <Button onClick={() => setRestartConfirm(false)}>取消</Button>
            <Button variant="primary"
              onClick={() => { setRestartConfirm(false); actionMutation.mutate({ action: "retry" }); }}>
              确认
            </Button>
          </>
        )}>
        <p className="subtle">重试将从最近的检查点恢复，已保存的工作区记录会被保留。</p>
      </Modal>

      <Modal open={provisionOpen} onClose={() => setProvisionOpen(false)} eyebrow="实验任务"
        title="正在启动实验环境"
        actions={(
          <Button onClick={() => setProvisionOpen(false)}>稍后手动进入</Button>
        )}>
        <p className="subtle" style={{ marginTop: 0 }}>
          按教师发布时锁定的镜像准备工作区，成功后将自动进入工作台。
        </p>
        {(provisioning.data ?? (current.status === "PROVISIONING")) ? (
          <AsyncJobProgress
            status={
              provisioning.data
                ? jobProgressState(provisioning.data["status"] as string | undefined)
                : "submitted"
            }
            stages={jobStages()}
            failureReason={failureReasonText()}
            onRetry={current.status === "FAILED" ? () => actionMutation.mutate({ action: "retry" }) : undefined}
          />
        ) : (
          <div className="state-block"><strong>正在提交开通请求…</strong></div>
        )}
      </Modal>
    </>
  );
}
