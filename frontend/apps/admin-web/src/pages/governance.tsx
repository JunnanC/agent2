import { useMutation, useQuery } from "@tanstack/react-query";
import { platformApi } from "@edu/api-client";
import type { Anomaly, Course } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { ApiError } from "@edu/auth-client";
import {
  Button, ConfirmDialog, Panel,  RequestStateView, StatusBadge, useToast,
} from "@edu/ui";
import { apiErrorMessage } from "@/lib/format";
import { useState } from "react";

function governanceActionError(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.payload?.code === "FEATURE_NOT_AVAILABLE") {
    return "该治理能力尚未在当前后端开放(接口返回 501)。";
  }
  if (error instanceof ApiError) return apiErrorMessage(error);
  return fallback;
}

export function Governance() {
  const toast = useToast();
  const [freezeTarget, setFreezeTarget] = useState<Course | null>(null);
  const [unfreezeTarget, setUnfreezeTarget] = useState<Course | null>(null);
  const [message, setMessage] = useState("");

  const courses = useQuery({ queryKey: keys.courses({ platform: true }), queryFn: () => platformApi.courses({ page_size: 50 }) });
  const alerts = useQuery({ queryKey: keys.governanceAlerts({}), queryFn: () => platformApi.governanceAlerts({}) });

  const freeze = useMutation({
    mutationFn: (target: Course) => platformApi.freezeCourse(target.public_id, { reason: message }, target.row_version),
    onSuccess: (course) => {
      toast.notify(`已冻结课程「${course.title ?? ""}」`);
      setFreezeTarget(null);
      setMessage("");
      void courses.refetch();
    },
    onError: (error) => toast.notify(governanceActionError(error, "冻结操作失败，请检查权限"), "error"),
  });
  const unfreeze = useMutation({
    mutationFn: (target: Course) => platformApi.freezeCourse(target.public_id, { reason: "解冻" }, target.row_version),
    onSuccess: () => {
      toast.notify("已解冻");
      setUnfreezeTarget(null);
      void courses.refetch();
    },
    onError: (error) => toast.notify(governanceActionError(error, "解冻失败"), "error"),
  });

  const rows = courses.data?.rows ?? [];
  const alertRows = alerts.data?.rows ?? [];

  return (
    <>
      
      <Panel title={<><h2>待处理治理告警</h2><span className="subtle">{alertRows.length} 项</span></>}>
        <RequestStateView
          loading={alerts.isLoading}
          error={alerts.error}
          onRetry={() => void alerts.refetch()}
          empty={!alertRows.length}
          emptyState={<div className="state-block"><strong>暂无治理告警</strong></div>}
        >
          <div>
            {alertRows.map((alert: Anomaly) => (
              <div className="item" key={alert.public_id}>
                <div>
                  <strong>{alert.message}</strong>
                  <small>{alert.kind} · {alert.target_ref} · {alert.occurred_at}</small>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <StatusBadge tone={alert.level === "HIGH" ? "bad" : alert.level === "MEDIUM" ? "warn" : "blue"}>{alert.level}</StatusBadge>
                  {alert.assignee ? <span className="subtle">负责人 {alert.assignee}</span> : null}
                </div>
              </div>
            ))}
          </div>
        </RequestStateView>
      </Panel>

      <Panel className="section" title={<h2>课程冻结状态</h2>}>
        <RequestStateView
          loading={courses.isLoading}
          error={courses.error}
          onRetry={() => void courses.refetch()}
          empty={!rows.length}
          emptyState={<div className="state-block"><strong>暂无课程</strong></div>}
        >
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>课程</th><th>选课方式</th><th>人数</th><th>状态</th><th /></tr></thead>
              <tbody>
                {rows.map((course) => (
                  <tr key={course.public_id}>
                    <td><strong>{course.title}</strong><small style={{ display: "block" }}>{course.code}</small></td>
                    <td>{course.enrollment_mode === "OPEN" ? "直接加入" : "需要审核"}</td>
                    <td>{course.active_enrollment_count}{course.capacity ? ` / ${course.capacity}` : ""}</td>
                    <td>
                      <StatusBadge tone={course.status === "ACTIVE" ? "good" : course.status === "FROZEN" ? "bad" : "neutral"}>
                        {course.status === "ACTIVE" ? "正常" : course.status === "FROZEN" ? "已冻结" : course.status}
                      </StatusBadge>
                    </td>
                    <td className="table-actions">
                      {course.status === "FROZEN"
                        ? <Button size="sm" onClick={() => setUnfreezeTarget(course)}>解冻</Button>
                        : <Button size="sm" variant="danger" onClick={() => setFreezeTarget(course)}>冻结</Button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </RequestStateView>
      </Panel>

      <ConfirmDialog
        open={freezeTarget != null}
        onClose={() => setFreezeTarget(null)}
        onConfirm={() => { if (freezeTarget) freeze.mutate(freezeTarget); }}
        title={`冻结课程「${freezeTarget?.title ?? ""}」？`}
        eyebrow="课程治理"
        tone="danger"
        busy={freeze.isPending}
        confirmLabel="确认冻结"
        description={(
          <>
            <label className="form-label" htmlFor="freeze-reason">冻结原因 <span>必填</span></label>
            <textarea id="freeze-reason" className="field" rows={2} value={message} onChange={(event) => setMessage(event.target.value)} />
          </>
        )}
      />
      <ConfirmDialog
        open={unfreezeTarget != null}
        onClose={() => setUnfreezeTarget(null)}
        onConfirm={() => { if (unfreezeTarget) unfreeze.mutate(unfreezeTarget); }}
        title={`解冻课程「${unfreezeTarget?.title ?? ""}」？`}
        eyebrow="课程治理"
        busy={unfreeze.isPending}
        description={<p>解冻后课程恢复正常教学运行。</p>}
      />
    </>
  );
}
