import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { timetableApi } from "@edu/api-client";
import type { TimetableImport, TimetableSchedule } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, EmptyState, Panel, RequestStateView, useToast } from "@edu/ui";

const weekdays = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"];
const displayTermName = (name?: string) => !name || /^legacy\b/i.test(name) ? "当前学期" : name;
const statusNames: Record<TimetableImport["status"], string> = {
  MAPPING_REQUIRED: "待匹配列名", READY: "待确认", RUNNING: "导入中", COMPLETED: "已完成", FAILED: "导入失败",
};
const requiredFields = ["course_title", "weekday", "start_period", "end_period"];
const rowErrorNames: Record<string, string> = {
  course_title_required: "缺少课程名称", course_code_required: "缺少课程代码", weekday_required: "无法识别星期",
  integer_required: "缺少有效数字", invalid_period_or_week_range: "节次或周次范围无效",
  duplicate_schedule_row: "课表记录重复", course_title_conflicts_for_code: "同一课程代码对应多个课程名称",
  required: "缺少必填内容", invalid_integer: "星期、节次或周次必须为整数", invalid_weekday: "星期必须在 1 到 7 之间",
  invalid_period: "节次范围无效", invalid_week_range: "周次范围无效", duplicate: "课表记录重复", course_code_conflict: "课程代码已被使用",
};

export function StudentTimetable({ uploadContainer }: { uploadContainer?: HTMLDivElement | null }) {
  const toast = useToast();
  const client = useQueryClient();
  const importResults = useRef<HTMLDivElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [jobId, setJobId] = useState("");
  const [mapping, setMapping] = useState<Record<string, string> | null>(null);
  const timetable = useQuery({ queryKey: keys.timetable(), queryFn: () => timetableApi.retrieve() });
  const groupedSchedules = useMemo(() => {
    const schedules = timetable.data?.schedules ?? [];
    const groups = new Map<string, { title: string; classroom: string; instructor: string; slots: TimetableSchedule[] }>();
    for (const schedule of schedules) {
      const key = schedule.course_id || `${schedule.course_title}|${schedule.course_code}`;
      const group = groups.get(key) ?? {
        title: schedule.course_title,
        classroom: schedule.classroom,
        instructor: schedule.instructor_name,
        slots: [],
      };
      group.classroom ||= schedule.classroom;
      group.instructor ||= schedule.instructor_name;
      group.slots.push(schedule);
      groups.set(key, group);
    }
    for (const group of groups.values()) {
      group.slots.sort((left, right) => left.weekday - right.weekday || left.start_period - right.start_period);
    }
    return [...groups.values()].sort((left, right) => left.slots[0]!.weekday - right.slots[0]!.weekday);
  }, [timetable.data]);
  const imports = useQuery({ queryKey: keys.timetableImports(), queryFn: timetableApi.imports });
  const job = useQuery({
    queryKey: keys.timetableImport(jobId), queryFn: () => timetableApi.importJob(jobId), enabled: Boolean(jobId),
    refetchInterval: (query) => query.state.data?.status === "RUNNING" ? 2000 : false,
  });
  useEffect(() => {
    if (job.data?.status === "COMPLETED") {
      void client.invalidateQueries({ queryKey: keys.timetable() });
      void client.invalidateQueries({ queryKey: keys.timetableImports() });
    }
  }, [client, job.data?.status]);
  const storeJob = (data: TimetableImport) => {
    client.setQueryData(keys.timetableImport(data.public_id), data);
    setJobId(data.public_id);
    setMapping(null);
    void imports.refetch();
  };
  const upload = useMutation({
    mutationFn: (selected: File) => timetableApi.upload(selected, timetable.data?.term.public_id),
    onSuccess: (data) => {
      storeJob(data);
      if (uploadContainer) importResults.current?.focus();
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
  const uploadDisabled = pending || job.data?.status === "RUNNING";

  const uploadForm = (
    <form className="student-timetable-upload" onSubmit={(event) => { event.preventDefault(); if (file) upload.mutate(file); }}>
      <label className="form-label" htmlFor="timetable-file">导入个人课表（.xlsx，最大 10 MB）</label>
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
      <p className="subtle" id="timetable-upload-hint">导入课表仅记录上课安排。学习课程请使用「加入课程」。</p>
    </form>
  );

  return <Panel className="section student-timetable" title={<><h2>我的课表</h2><span className="subtle">{displayTermName(timetable.data?.term.name)}</span></>}>
    <RequestStateView loading={timetable.isLoading} error={timetable.error} onRetry={() => void timetable.refetch()}
      empty={!timetable.data?.schedules.length} emptyState={<EmptyState title="暂无已排课时间" hint="可在页面上方导入个人课表。" />}>
      {groupedSchedules.map((group) => <div className="item timetable-course-row" key={`${group.title}-${group.slots[0]?.weekday}-${group.slots[0]?.start_period}`}>
        <div><strong>{group.title}</strong><small>{group.classroom || "教室待定"} · {group.instructor || "教师待定"}</small></div>
        <div className="timetable-slots">
          {group.slots.map((schedule, index) => <span key={`${schedule.weekday}-${schedule.start_period}-${index}`}>
            {weekdays[schedule.weekday]} 第 {schedule.start_period}—{schedule.end_period} 节{schedule.week_start != null && schedule.week_end != null ? ` · 第 ${schedule.week_start}—${schedule.week_end} 周` : ""}
          </span>)}
        </div>
      </div>)}
    </RequestStateView>
    {uploadContainer ? createPortal(uploadForm, uploadContainer) : uploadContainer === undefined && uploadForm}
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
