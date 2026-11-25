import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { timetableApi } from "@edu/api-client";
import type { TimetableImport } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, Panel, RequestStateView, useToast } from "@edu/ui";

const statusNames: Record<TimetableImport["status"], string> = {
  MAPPING_REQUIRED: "待匹配列名", READY: "待确认", RUNNING: "导入中", COMPLETED: "已完成", FAILED: "导入失败",
};
const requiredFields = ["course_code", "course_title", "weekday", "start_period", "end_period"];
const rowErrorNames: Record<string, string> = {
  course_title_required: "缺少课程名称", course_code_required: "缺少课程代码", weekday_required: "无法识别星期",
  integer_required: "缺少有效数字", invalid_period_or_week_range: "节次或周次范围无效",
  duplicate_schedule_row: "课表记录重复", course_title_conflicts_for_code: "同一课程代码对应多个课程名称",
  required: "缺少必填内容", invalid_integer: "星期、节次或周次必须为整数", invalid_weekday: "星期必须在 1 到 7 之间",
  invalid_period: "节次范围无效", invalid_week_range: "周次范围无效", duplicate: "课表记录重复", course_code_conflict: "该学期中此班号已关联其他班名",
  conflicting_week_parity: "周次不能同时指定单周和双周", week_parity_outside_range: "范围中没有符合单双周的周次",
};

export function TimetableImport({ termId }: { termId: string }) {
  const toast = useToast();
  const client = useQueryClient();
  const importResults = useRef<HTMLDivElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [jobId, setJobId] = useState("");
  const [mapping, setMapping] = useState<Record<string, string> | null>(null);
  const imports = useQuery({ queryKey: keys.timetableImports(), queryFn: timetableApi.imports });
  const job = useQuery({
    queryKey: keys.timetableImport(jobId), queryFn: () => timetableApi.importJob(jobId), enabled: Boolean(jobId),
    refetchInterval: (query) => query.state.data?.status === "RUNNING" ? 2000 : false,
  });
  useEffect(() => {
    if (job.data?.status === "COMPLETED") {
      void client.invalidateQueries({ queryKey: keys.teachingTimetable() });
      void client.invalidateQueries({ queryKey: keys.timetableImports() });
      void client.invalidateQueries({ queryKey: keys.teachingCourses() });
    }
  }, [client, job.data?.status]);
  const storeJob = (data: TimetableImport) => {
    client.setQueryData(keys.timetableImport(data.public_id), data);
    setJobId(data.public_id);
    setMapping(null);
    void imports.refetch();
  };
  const upload = useMutation({
    mutationFn: (selected: File) => timetableApi.upload(selected, termId),
    onSuccess: (data) => {
      storeJob(data);
      importResults.current?.focus();
    },
    onError: (error) => toast.notify(error.message, "error"),
  });
  const saveMapping = useMutation({
    mutationFn: () => timetableApi.updateMapping(jobId, mapping ?? job.data?.mapping ?? {}),
    onSuccess: storeJob, onError: (error) => toast.notify(error.message, "error"),
  });
  const confirm = useMutation({
    mutationFn: () => timetableApi.confirm(jobId),
    onSuccess: storeJob, onError: (error) => { toast.notify(error.message, "error"); void job.refetch(); },
  });
  const pending = upload.isPending || saveMapping.isPending || confirm.isPending;
  const editable = job.data?.status === "MAPPING_REQUIRED" || job.data?.status === "READY";
  const currentMapping = mapping ?? job.data?.mapping ?? {};
  const uploadDisabled = !termId || pending || job.data?.status === "RUNNING";
  const error = upload.error ?? saveMapping.error ?? confirm.error;

  const uploadForm = (
    <form className="student-timetable-upload" onSubmit={(event) => { event.preventDefault(); if (file && !uploadDisabled) upload.mutate(file); }}>
      <label className="form-label" htmlFor="timetable-file">导入教学班课表（.xlsx，最大 10 MB）</label>
      <div className="student-timetable-upload-controls">
        <input id="timetable-file" type="file" accept=".xlsx" disabled={uploadDisabled} aria-describedby="timetable-upload-hint"
          onChange={(event) => {
            const selected = event.target.files?.[0] ?? null;
            if (selected && (!selected.name.toLowerCase().endsWith(".xlsx") || selected.size > 10 * 1024 * 1024 || selected.size === 0)) {
              toast.notify("请选择不超过 10 MB 的非空 .xlsx 文件", "error"); event.target.value = ""; setFile(null); return;
            }
            setFile(selected);
          }} />
        <Button type="submit" size="sm" disabled={!file || uploadDisabled}>{upload.isPending ? "上传中…" : "上传课表"}</Button>
      </div>
      <p className="subtle" id="timetable-upload-hint">分开的节次或周次列可以分别映射。若同列提供范围，可将起止字段映射到同一列。</p>
    </form>
  );

  return <Panel className="section" title={<h2>导入教学班</h2>}>
    {uploadForm}
    {error && <p className="notice" role="alert">{error.message}</p>}
    <div ref={importResults} role="region" aria-label="课表导入结果" tabIndex={-1}>
      <RequestStateView loading={imports.isLoading} error={imports.error} onRetry={() => void imports.refetch()} empty={!imports.data?.rows.length} emptyState={<></>}>
        {(imports.data?.rows.length ?? 0) > 0 && <label className="form-label">最近的导入
          <select className="field" value={jobId} disabled={pending} onChange={(event) => { setJobId(event.target.value); setMapping(null); }}>
            <option value="">选择导入记录</option>
            {(imports.data?.rows ?? []).map((item) => <option key={item.public_id} value={item.public_id}>{item.filename} · {statusNames[item.status]}</option>)}
          </select>
        </label>}
      </RequestStateView>
      {jobId && <RequestStateView loading={job.isLoading} error={job.error} onRetry={() => void job.refetch()} empty={!job.data}>
        {job.data && <div className="section">
          <strong>{job.data.filename} · {statusNames[job.data.status]}</strong>
          {typeof job.data.summary.total === "number" && <p className="subtle">共 {job.data.summary.total} 行 · 通过 {String(job.data.summary.valid ?? "—")} 行 · 错误 {String(job.data.summary.errors ?? 0)} 项</p>}
          {editable && <>
            <p className="subtle">将表格列匹配到课程信息，带 * 的项目必填。</p>
            {job.data.fields.map((field) => <label className="form-label" key={field.key}>{field.label}{requiredFields.includes(field.key) ? " *" : ""}
              <select className="field" value={currentMapping[field.key] ?? ""} disabled={pending} onChange={(event) => {
                const next = { ...currentMapping }; if (event.target.value) next[field.key] = event.target.value; else delete next[field.key]; setMapping(next);
              }}><option value="">请选择列</option>{job.data.headers.map((header) => <option key={header} value={header}>{header}</option>)}</select>
            </label>)}
            <Button disabled={pending || requiredFields.some((field) => !currentMapping[field])} onClick={() => saveMapping.mutate()}>保存并检查</Button>{" "}
            <Button variant="primary" disabled={pending || mapping !== null || job.data.status !== "READY" || job.data.row_errors.length > 0} onClick={() => confirm.mutate()}>确认导入</Button>
          </>}
          {job.data.row_errors.length > 0 && <div role="alert"><p>有 {job.data.row_errors.length} 项未通过检查，请调整列映射或修改表格后重新上传。</p>
            <ul>{job.data.row_errors.map((error, index) => <li key={`${error.row_no}-${index}`}>第 {error.row_no} 行：{rowErrorNames[error.code] ?? error.code}</li>)}</ul>
          </div>}
          {job.data.status === "RUNNING" && <p role="status">正在导入，完成后课表会自动更新。</p>}
          {job.data.status === "COMPLETED" && <p role="status">课表已导入。</p>}
          {job.data.status === "FAILED" && <p role="alert">导入失败，请检查表格后重新上传。</p>}
        </div>}
      </RequestStateView>}
    </div>
  </Panel>;
}
