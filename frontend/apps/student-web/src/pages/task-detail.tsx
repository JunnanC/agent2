import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { taskApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, ErrorState, Modal, Panel, RequestStateView, StatusBadge, useToast } from "@edu/ui";
import { formatDateTime, taskStatusLabel, taskStatusTone } from "@/lib/task-format";
import { CourseAgent } from "@/components/course-agent";
import { useStudentWorkspace } from "@/lib/use-student-workspace";

export function TaskDetail() {
  const { taskId = "" } = useParams();
  const toast = useToast();
  const [extensionOpen, setExtensionOpen] = useState(false);
  const [extensionReason, setExtensionReason] = useState("");
  const task = useQuery({ queryKey: keys.task(taskId), queryFn: () => taskApi.detail(taskId) });
  const workspace = useStudentWorkspace(taskId, Boolean(task.data?.workspace_available
    && Date.now() >= new Date(task.data.window_start ?? "").getTime()
    && !["WITHDRAWN", "CANCELLED", "FAILED", "ARCHIVING"].includes(task.data.status)));
  const extension = useMutation({
    mutationFn: () => taskApi.requestExtension(taskId, { reason: extensionReason.trim() }, task.data?.row_version ?? ""),
    onSuccess: () => {
      toast.notify("延期申请已提交，等待审核");
      setExtensionOpen(false); setExtensionReason(""); void task.refetch();
    },
    onError: () => toast.notify("延期申请失败，请稍后重试", "error"),
  });
  if (task.isLoading) return <Panel><RequestStateView loading error={null} empty={false} emptyState={null} /></Panel>;
  if (task.error) return <Panel><ErrorState error={task.error} onRetry={() => void task.refetch()} title="无法读取任务" /></Panel>;
  const current = task.data;
  if (!current) return null;
  const canExtend = current.allowed_actions.some(action => ["extension", "request_extension"].includes(action));
  return <>
    <div className="crumb"><Link className="crumb-link" to="/">学生门户</Link> / <Link className="crumb-link" to="/experiments">实验任务</Link> / <b>{current.title}</b></div>
    <div className="page-actions"><h1>{current.title}</h1>
      {current.assessment_available && <Link className="btn primary" to={`/experiments/${taskId}/assessment`}>进入实验答题</Link>}
    </div>
    <Panel>
      <StatusBadge tone={taskStatusTone(current.status)}>{taskStatusLabel(current.status)}</StatusBadge>
      <p>开放 {formatDateTime(current.window_start)} · 截止 {formatDateTime(current.effective_deadline)}</p>
      {current.assessment_available
        ? <p>{current.workspace_available ? "选择题、编程题和实验报告分别作答、计分。" : "进入答题页面查看作答与提交记录。"}</p>
        : <p role="status">此任务使用已停用的工作区格式，请联系教师重新发布。</p>}
      {current.blockers.map((blocker, index) => <p key={index}>{blocker.reason ?? blocker.detail ?? blocker.code}</p>)}
      {workspace.status === "PENDING" && <p role="status">正在准备实验环境…</p>}
      {canExtend && <Button onClick={() => setExtensionOpen(true)}>申请延期</Button>}
    </Panel>
    {current.course_id && <CourseAgent key={taskId} courseId={current.course_id} taskId={taskId} />}
    <Modal open={extensionOpen} onClose={() => setExtensionOpen(false)} eyebrow="申请延期" title="申请任务延期"
      actions={<><Button onClick={() => setExtensionOpen(false)}>取消</Button><Button variant="primary" disabled={!extensionReason.trim() || extension.isPending} onClick={() => extension.mutate()}>提交延期申请</Button></>}>
      <label className="form-label" htmlFor="extension-reason">申请原因</label>
      <textarea id="extension-reason" className="field" rows={3} value={extensionReason} onChange={event => setExtensionReason(event.target.value)} />
    </Modal>
  </>;
}
