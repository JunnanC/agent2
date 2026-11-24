import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { teachingApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, Metric, Panel, RequestStateView } from "@edu/ui";

const percent = (value: number | null) => value === null ? "—" : `${value}%`;
const status = { NOT_SUBMITTED: "未提交", PARTIAL: "部分提交", SUBMITTED: "已完成" };
const reasons: Record<string, string> = { ENROLLMENT_UNCONFIRMED: "班级或入班记录待核对", RELEASED_PARTS_UNCONFIRMED: "分项成绩待核对" };

export function ReleasedGradeBoard({ courseId }: { courseId: string }) {
  const [selected, setSelected] = useState<string[]>([]);
  const all = useQuery({ queryKey: keys.releasedGrades(courseId), queryFn: () => teachingApi.releasedGrades(courseId) });
  const filtered = useQuery({ queryKey: keys.releasedGrades(courseId, selected),
    queryFn: () => teachingApi.releasedGrades(courseId, selected), enabled: selected.length > 0 });
  const report = selected.length ? filtered : all;
  const data = report.data;
  const exportReport = useMutation({
    mutationFn: () => teachingApi.exportReleasedGrades(courseId, selected),
    onSuccess: ({ filename, csv }) => {
      const url = URL.createObjectURL(new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    },
  });
  return <Panel className="section" title={<h2>已发布成绩</h2>}>
    {!!all.data?.experiments.length && <fieldset className="page-actions">
      <legend>分析与导出范围（未勾选时为全班全部实验）</legend>
      {all.data.experiments.map((experiment) => <label key={experiment.publication_id}>
        <input type="checkbox" checked={selected.includes(experiment.publication_id)} onChange={(event) => {
          setSelected((previous) => event.target.checked ? [...previous, experiment.publication_id].sort() : previous.filter((id) => id !== experiment.publication_id));
        }} />{experiment.title}
      </label>)}
      <Button disabled={!data || exportReport.isPending} onClick={() => exportReport.mutate()}>导出 CSV</Button>
    </fieldset>}
    {exportReport.error && <p role="alert">{exportReport.error.message}</p>}
    <RequestStateView loading={report.isLoading} error={report.error} onRetry={() => void report.refetch()}
      empty={!data?.experiments.length && !data?.awaiting_confirmation.length} emptyState={<p>暂无已发布成绩。</p>}>
      {data && <>
        <div className="metric-strip">
          <Metric label="得分率" value={percent(data.summary.percent)} />
          <Metric label="挂科率" value={percent(data.summary.failure_rate)} />
          <Metric label="完成度" value={percent(data.summary.completion_rate)} sub={`${data.summary.completed} / ${data.summary.expected} 项`} />
        </div>
        <div className="table-wrap"><table className="table">
          <caption>实验概览</caption>
          <thead><tr><th>实验</th><th>应做人数</th><th>完成人数</th><th>得分率</th></tr></thead>
          <tbody>{data.experiments.map((item) => <tr key={item.publication_id}><td>{item.title}</td><td>{item.expected}</td><td>{item.completed}</td><td>{percent(item.percent)}</td></tr>)}</tbody>
        </table></div>
        {data.parts.length > 0 && <ul aria-label="分项诊断">{data.parts.map((part) => <li key={part.kind}>{part.label} {percent(part.percent)} {part.suggestion}</li>)}</ul>}
        <div className="table-wrap"><table className="table">
          <caption>学生总评与名次</caption>
          <thead><tr><th>名次</th><th>学生</th><th>总评</th><th>实得 / 满分</th><th>完成度</th></tr></thead>
          <tbody>{data.students.map((student) => <tr key={student.student_id}><td>{student.rank ?? "—"}</td><td>{student.student_name}</td><td>{percent(student.percent)} {student.failed && "（挂科）"}</td><td>{student.score} / {student.max_score}</td><td>{percent(student.completion_rate)}</td></tr>)}</tbody>
        </table></div>
        {data.results.length > 0 && <details><summary>查看逐项提交与得分</summary>
          <div className="table-wrap"><table className="table">
            <thead><tr><th>实验</th><th>学生</th><th>提交状态</th><th>实得 / 满分</th></tr></thead>
            <tbody>{data.results.map((item) => <tr key={`${item.publication_id}-${item.student_id}`}><td>{data.experiments.find((experiment) => experiment.publication_id === item.publication_id)?.title}</td><td>{item.student_name}</td><td>{status[item.status]}</td><td>{item.score} / {item.max_score}</td></tr>)}</tbody>
          </table></div>
        </details>}
        {data.awaiting_confirmation.length > 0 && <details><summary>待确认记录（{data.awaiting_confirmation.length}）</summary>
          <ul>{data.awaiting_confirmation.map((item, index) => <li key={index}>{item.task_id} {reasons[item.reason] ?? item.reason}</li>)}</ul>
        </details>}
      </>}
    </RequestStateView>
  </Panel>;
}
