import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { labAssessmentApi } from "@edu/api-client";
import { ConfirmDialog, Panel, useToast } from "@edu/ui";
import { keys } from "@edu/query-keys";
import { apiErrorMessage, formatDateTime } from "@/lib/format";
import "./lab-workbench.css";

export function LabGradeRelease({ courseId, publicationId }: { courseId: string; publicationId: string }) {
  const toast = useToast();
  const client = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const status = useQuery({
    queryKey: ["lab-grade-release", courseId, publicationId],
    queryFn: () => labAssessmentApi.releaseStatus(courseId, publicationId),
    refetchInterval: (query) => query.state.data?.grades_published_at ? false : 5000,
  });
  const publish = useMutation({
    mutationFn: () => labAssessmentApi.release(courseId, publicationId),
    onSuccess: () => {
      setConfirm(false);
      toast.notify("整次实验成绩已发布");
      void status.refetch();
      void client.invalidateQueries({ queryKey: ["assessment-report-review", courseId] });
      void client.invalidateQueries({ queryKey: ["assessment-report-queue", courseId] });
      void client.invalidateQueries({ queryKey: ["assessment-parts", courseId] });
      void client.invalidateQueries({ queryKey: keys.publications(courseId) });
      void client.invalidateQueries({ queryKey: keys.releasedGrades(courseId) });
      void client.invalidateQueries({ queryKey: ["review-publication", courseId, publicationId] });
    },
    onError: (error) => {
      toast.notify(apiErrorMessage(error), "error");
      void status.refetch();
    },
  });
  const batch = useMutation({
    mutationFn: () => labAssessmentApi.batchReview(courseId, publicationId),
    onSuccess: (data) => {
      toast.notify(data.queued ? `已将 ${data.queued} 份报告加入批阅队列` : "目前没有可加入批阅队列的报告");
      void client.invalidateQueries({ queryKey: ["assessment-report-queue", courseId] });
      void status.refetch();
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });
  const data = status.data;
  const beforeDeadline = !data || Date.now() < new Date(data.deadline).getTime();
  const blocked = !data || data.pending_reports > 0 || data.pending_runs > 0 || data.open_redos > 0;
  return <section className="lab-review-controls" aria-label="实验成绩发布">
    <Panel title={<h2>整次实验成绩</h2>}>
      {status.isPending && <p role="status">正在读取发布条件…</p>}
      {status.isError && <p role="alert">无法读取发布条件。 <button className="btn sm" onClick={() => void status.refetch()}>重试</button></p>}
      {data?.grades_published_at ? <p role="status">已于 {formatDateTime(data.grades_published_at)} 发布，成绩和批阅结果已锁定。</p>
        : data && <>
          <p>截止 {formatDateTime(data.deadline)} · 待处理报告 {data.pending_reports} 份 · 正式评测 {data.pending_runs} 项 · 开放补做 {data.open_redos} 项</p>
          <div className="page-actions">
            <button className="btn" type="button" disabled={batch.isPending} onClick={() => batch.mutate()}>
              {batch.isPending ? "正在提交…" : "批量 AI 批阅"}
            </button>
            <button className="btn primary" type="button" disabled={beforeDeadline || blocked || publish.isPending}
              onClick={() => setConfirm(true)}>一键同意并发布成绩</button>
          </div>
        </>}
    </Panel>
    <ConfirmDialog open={confirm} title="确认发布整次实验成绩" confirmLabel="确认发布"
      description="发布会确认已有 AI 建议并锁定整次实验的成绩、批注与报告。"
      busy={publish.isPending} onClose={() => setConfirm(false)} onConfirm={() => publish.mutate()} />
  </section>;
}
