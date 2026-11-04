import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { studentApi } from "@edu/api-client";
import type { Enrollment } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, Modal, RequestStateView, useToast } from "@edu/ui";

export function EnrollmentExit({ enrollment, onExited }: { enrollment: Enrollment; onExited?: () => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const client = useQueryClient();
  const toast = useToast();
  const latest = useQuery({ queryKey: keys.enrollment(enrollment.public_id),
    queryFn: () => studentApi.enrollment(enrollment.public_id), enabled: open, staleTime: 0 });
  const pending = (latest.data ?? enrollment).status === "PENDING";
  const active = (latest.data ?? enrollment).status === "ACTIVE";
  const check = useQuery({ queryKey: [...keys.enrollment(enrollment.public_id), "drop-check"],
    queryFn: () => studentApi.dropCheck(enrollment.public_id), enabled: open && latest.isSuccess && active, staleTime: 0 });
  const exit = useMutation({
    mutationFn: async () => {
      const current = latest.data;
      if (!current) throw new Error("请先读取最新选课状态");
      if (current.status === "PENDING") return studentApi.withdrawEnrollment(current.public_id, current.row_version);
      if (current.status !== "ACTIVE" || !check.data?.allowed) throw new Error("当前选课状态不允许退出");
      return studentApi.dropEnrollment(current.public_id, { reason: reason.trim() }, current.row_version);
    },
    onSuccess: (result) => {
      toast.notify(result.status === "WITHDRAWN" ? "选课申请已撤回" : "已退出课程"); setOpen(false); setReason("");
      void client.invalidateQueries({ queryKey: keys.enrollments() });
      void client.invalidateQueries({ queryKey: ["courses"] });
      void client.invalidateQueries({ queryKey: ["student"] });
      void client.invalidateQueries({ queryKey: ["tasks"] });
      void client.invalidateQueries({ queryKey: keys.context() });
      onExited?.();
    },
    onError: (error) => { toast.notify(error.message, "error"); void latest.refetch(); if (active) void check.refetch(); },
  });
  if (!["PENDING", "ACTIVE"].includes(enrollment.status)) return null;
  return <>
    <Button size="sm" onClick={() => setOpen(true)}>{enrollment.status === "PENDING" ? "撤回申请" : "退出课程"}</Button>
    <Modal open={open} onClose={() => { if (!exit.isPending) setOpen(false); }} title={pending ? "撤回选课申请" : "退出课程"}
      actions={<><Button disabled={exit.isPending} onClick={() => setOpen(false)}>取消</Button>
        <Button variant="danger" disabled={exit.isPending || latest.isFetching || latest.isError || !latest.data ||
          (!pending && (!active || check.isFetching || check.isError || !check.data?.allowed || !reason.trim()))}
          onClick={() => exit.mutate()}>{exit.isPending ? "处理中…" : pending ? "确认撤回" : "确认退出"}</Button></>}>
      <p className="section">{enrollment.course_title ?? enrollment.course_code}</p>
      <RequestStateView loading={latest.isPending} error={latest.error} empty={false} onRetry={() => void latest.refetch()}>
        {pending ? <p>撤回后，教师将不再审核这次申请。</p> : active ?
          <RequestStateView loading={check.isPending} error={check.error} empty={false} onRetry={() => void check.refetch()}>
            {check.data?.allowed ? <p>有未完成任务也可以退出课程。确认后退课立即生效，系统会通知课程老师，无需老师同意。退出后将失去本课程的学习权限，未完成任务不再显示在待办列表中，已有学习记录会保留。</p> :
              <div role="alert">当前无法退出课程{check.data?.blockers.map((blocker) => <p key={blocker.type}>{blocker.message}（{blocker.count} 项）</p>)}</div>}
            <label className="form-label" htmlFor={`exit-${enrollment.public_id}`}>退出原因</label>
            <textarea id={`exit-${enrollment.public_id}`} className="field" maxLength={500} rows={3} value={reason}
              disabled={exit.isPending} onChange={(event) => setReason(event.target.value)} />
          </RequestStateView> : <p role="status">选课状态已变化，请关闭弹窗并刷新课程列表。</p>}
      </RequestStateView>
    </Modal>
  </>;
}
