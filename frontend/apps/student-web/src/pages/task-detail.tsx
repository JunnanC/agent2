import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { taskApi } from "@edu/api-client";
import type { Task, WorkspaceSession } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { AsyncJobProgress, Button, ErrorState, Modal, Panel, RequestStateView, StatusBadge, useToast } from "@edu/ui";
import type { JobStage } from "@edu/ui";
import { storeWorkspaceSession } from "@/lib/workspace-session";
import { actionLabel, formatDateTime, taskStatusLabel, taskStatusTone } from "@/lib/task-format";

const WORKFLOW_STATUS_ORDER = ["ASSIGNED", "PROVISIONING", "READY", "IN_PROGRESS", "REPORT_DRAFT", "SUBMITTED", "UNDER_REVIEW", "COMPLETED"];

export function TaskDetail() {
  const { taskId = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [extensionOpen, setExtensionOpen] = useState(false);
  const [extensionReason, setExtensionReason] = useState("");
  const [restartConfirm, setRestartConfirm] = useState(false);
  const [provisionOpen, setProvisionOpen] = useState(false);
  const autoEnteredRef = useRef(false);

  const task = useQuery({ queryKey: keys.task(taskId), queryFn: () => taskApi.detail(taskId) });
  const provisioning = useQuery({
    queryKey: keys.provisioningJob(taskId),
    queryFn: () => taskApi.provisioningJob(taskId),
    refetchInterval: (query) => {
      const data = query.state.data as Record<string, unknown> | null;
      const status = String(data?.["status"] ?? "");
      return ["SUBMITTED", "RUNNING"].includes(status) ? 4000 : false;
    },
    enabled: task.data?.status === "PROVISIONING",
  });

  const invalidate = () => { void task.refetch(); };

  const actionMutation = useMutation({
    mutationFn: (input: { action: string }): Promise<Task | { task: Task; session: WorkspaceSession }> => {
      const reuseKey = `task-${input.action}-${taskId}`;
      if (input.action === "start") return taskApi.start(taskId, task.data?.row_version ?? "", reuseKey);
      if (input.action === "retry") return taskApi.retry(taskId, task.data?.row_version ?? "", reuseKey);
      if (input.action === "enter") {
        return taskApi.enter(taskId, task.data?.row_version ?? "", reuseKey);
      }
      return taskApi.complete(taskId, task.data?.row_version ?? "");
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

  const jobStages = (): { key: string; label: string; state: JobStage["state"] }[] => {
    const job = provisioning.data as { status?: string; stages?: Array<{ name?: string; status?: string }> } | null;
    return (job?.stages ?? []).map((stage, index) => ({
      key: String(index),
      label: stage.name ?? `阶段 ${index + 1}`,
      state: stageProgressState(stage.status),
    }));
  };

  // 弹窗流程：任务就绪后自动进入工作台；job 成功但任务仍为 PROVISIONING 时先热刷新任务
  useEffect(() => {
    if (!provisionOpen) return;
    const taskStatus = task.data?.status ?? "";
    const jobStatus = String((provisioning.data as Record<string, unknown> | null)?.["status"] ?? "");
    if (taskStatus !== "PROVISIONING" && ["SUCCEEDED", "PASSED", "COMPLETED"].includes(jobStatus)) {
      void task.refetch();
    }
    if (taskStatus === "READY" && !autoEnteredRef.current) {
      autoEnteredRef.current = true;
      setProvisionOpen(false);
      actionMutation.mutate({ action: "enter" });
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
        {current.allowed_actions.includes("enter") && !current.blockers.length ? (
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
            .filter((action) => !["enter", "extension", "request_extension"].includes(action))
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
              failureReason={current.current_failure?.message}
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
            failureReason={current.current_failure?.message}
            onRetry={current.status === "FAILED" ? () => actionMutation.mutate({ action: "retry" }) : undefined}
          />
        ) : (
          <div className="state-block"><strong>正在提交开通请求…</strong></div>
        )}
      </Modal>
    </>
  );
}
