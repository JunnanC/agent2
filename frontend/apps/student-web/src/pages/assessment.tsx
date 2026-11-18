import { AssetActions } from "@/components/asset-actions";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { assessmentApi, reportApi } from "@edu/api-client";
import type { Assessment, AssessmentLanguage, ChoiceQuestion, ProgrammingQuestion } from "@edu/api-client";
import { newIdempotencyKey } from "@edu/auth-client";
import { keys } from "@edu/query-keys";
import { CodeEditor, Icon, LoadingState, Modal, useToast } from "@edu/ui";
import { formatDateTime } from "@/lib/task-format";
import "./assessment.css";

type Flush = () => Promise<boolean>;
type Register = (key: string, flush: Flush | null) => void;
type HistoryRow = {
  kind: string; version_no: number; submitted_at: string; is_current: boolean;
  answers: Array<{ question_id: string; selected_option_ids: string[] }>;
};
const STATUS_LABEL: Record<string, string> = {
  NOT_SUBMITTED: "未提交", SUBMITTED: "已交卷", RETURNED: "待修改重交",
  PENDING: "待评分", RUNNING: "运行中", RETRY: "服务重试中", COMPLETED: "已完成",
  PASSED: "运行成功", COMPILE_ERROR: "编译失败", RUNTIME_ERROR: "运行错误",
  TIMEOUT: "运行超时", MEMORY_LIMIT: "内存超限", OUTPUT_LIMIT: "输出超限",
};

type Section = Assessment["sections"][number];

function sectionLabel(kind: "CHOICE" | "PROGRAMMING", section?: Section): string {
  const name = kind === "CHOICE" ? "选择题" : "编程与报告";
  if (!section || section.status === "NOT_SUBMITTED") return `${name}：未提交`;
  if (section.status === "RETURNED") return `${name}：已退回，需要重交`;
  if (section.status !== "SUBMITTED") return `${name}：${STATUS_LABEL[section.status] ?? section.status}`;
  if (section.grading_status === "COMPLETED") {
    return section.score != null
      ? `${name}：已交卷 · 已批改 · ${section.score} / ${section.max_score ?? "—"} 分`
      : `${name}：已交卷 · 已批改（成绩由老师公布）`;
  }
  if (section.grading_status === "RETURNED") return `${name}：已交卷 · 已退回，需要重交`;
  return `${name}：已交卷 · 待批改`;
}

function useAutosave<T>({ load, save, register, draftKey, immediate = false, saveOnLoad = false }: {
  load: () => Promise<{ value: T; version: number }>;
  save: (value: T, version: number) => Promise<{ value: T; version: number }>;
  register: Register; draftKey: string; immediate?: boolean; saveOnLoad?: boolean;
}) {
  const [value, setValue] = useState<T | null>(null);
  const [status, setStatus] = useState("载入中");
  const [touched, setTouched] = useState(false);
  const current = useRef<{ value: T; version: number; generation: number; saved: number } | null>(null);
  const queue = useRef<Promise<boolean>>(Promise.resolve(true));
  const conflict = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const saveRef = useRef(save);
  useEffect(() => { saveRef.current = save; }, [save]);

  const flush = useCallback((): Promise<boolean> => {
    clearTimeout(timer.current);
    queue.current = queue.current.then(async () => {
      if (!current.current || conflict.current) return false;
      try {
        while (current.current.generation !== current.current.saved) {
          const { value: pending, version, generation } = current.current;
          setStatus("保存中");
          const result = await saveRef.current(pending, version);
          current.current.version = result.version;
          current.current.saved = generation;
        }
        setStatus("已保存");
        return true;
      } catch (error) {
        const candidate = error as { status?: number };
        if (candidate.status === 412) conflict.current = true;
        setStatus(conflict.current ? "版本冲突：本地内容已保留，请复制后刷新比较" : "保存失败，内容仍在本页，请重试");
        return false;
      }
    });
    return queue.current;
  }, []);

  useEffect(() => {
    let mounted = true;
    void load().then((draft) => {
      if (!mounted) return;
      current.current = { ...draft, generation: saveOnLoad ? 1 : 0, saved: 0 };
      setValue(draft.value); setStatus("已保存");
      if (saveOnLoad) void flush();
    }).catch(() => { if (mounted) setStatus("载入失败，请刷新重试"); });
    register(draftKey, flush);
    const beforeUnload = (event: BeforeUnloadEvent) => {
      const draft = current.current;
      if (draft && draft.generation !== draft.saved) { event.preventDefault(); }
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => {
      mounted = false; clearTimeout(timer.current); register(draftKey, null);
      window.removeEventListener("beforeunload", beforeUnload);
    };
    // Mount identity is the question/language key. Callbacks read the same fixed scope.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey, flush, register]);

  const change = (next: T) => {
    if (!current.current) return;
    setTouched(true);
    current.current.value = next; current.current.generation += 1;
    setValue(next); setStatus("有未保存修改");
    clearTimeout(timer.current);
    const saveWithRetry = async () => {
      if (!await flush() && !conflict.current) {
        timer.current = setTimeout(() => { void saveWithRetry(); }, 5000);
      }
    };
    timer.current = setTimeout(() => { void saveWithRetry(); }, immediate ? 0 : 2000);
  };
  return { value, change, status, touched, failed: /保存失败|版本冲突/.test(status), flush };
}

function ChoiceAnswer({ taskId, question, register, disabled, submittedSelected, result }: {
  taskId: string; question: ChoiceQuestion; register: Register; disabled: boolean;
  submittedSelected?: string[]; result?: { score: string | null; max_score: string };
}) {
  const draft = useAutosave<string[]>({
    draftKey: question.id, register, immediate: true,
    load: async () => { const data = await assessmentApi.choiceDraft(taskId, question.id); return { value: data.selected_option_ids, version: data.row_version }; },
    save: async (value, version) => { const data = await assessmentApi.saveChoice(taskId, question.id, value, version); return { value: data.selected_option_ids, version: data.row_version }; },
  });
  const selected = disabled && submittedSelected ? submittedSelected : draft.value;
  let verdict: string | null = null;
  if (disabled && submittedSelected && question.correct_option_ids) {
    verdict = submittedSelected.length === 0
      ? "漏答"
      : sameOptions(submittedSelected, question.correct_option_ids) ? "正确" : "错误";
  }
  return <article className="panel assessment-choice">
    <h2 className="assessment-question-title">{question.title} <small>{question.max_score} 分</small></h2>
    <p className="assessment-question-text">{question.description}</p>
    <fieldset disabled={disabled || draft.value === null}>
      <legend>{question.task_type === "SINGLE_CHOICE" ? "单选题" : "多选题（完全正确才得分）"}</legend>
      {question.options.map((option) => <label className="item choice-option" key={option.id}>
        <input type={question.task_type === "SINGLE_CHOICE" ? "radio" : "checkbox"} name={question.id}
          checked={selected?.includes(option.id) ?? false} onChange={(event) => {
            const current = draft.value ?? [];
            draft.change(question.task_type === "SINGLE_CHOICE" ? [option.id] : event.target.checked ? [...current, option.id] : current.filter((id) => id !== option.id));
          }} /> {option.text}
      </label>)}
    </fieldset>
    {result && <p>本题得分：{result.score ?? "0"} / {result.max_score}{verdict ? ` · ${verdict}` : ""}</p>}
    {!disabled && draft.touched && <p role="status" className="subtle">自动保存：{draft.status}
      {draft.failed && <button className="btn sm" onClick={() => void draft.flush()}>重试保存</button>}
    </p>}
    {question.correct_option_ids && <div className="section">
      <p>正确选项：{question.options.filter((o) => question.correct_option_ids!.includes(o.id)).map((o) => o.text).join("；")}</p>
      <p>{question.explanation}</p>
    </div>}
  </article>;
}

function sameOptions(left: string[], right: string[]): boolean {
  if (left.length !== right.length) return false;
  const expected = new Set(right);
  return left.every((id) => expected.has(id));
}

function AnswerSheet({ submission, questions, result }: {
  submission: HistoryRow; questions: ChoiceQuestion[];
  result?: Array<{ id: string; score: string | null; max_score: string }>;
}) {
  return <div>
    {submission.answers.map((answer) => {
      const question = questions.find((item) => item.id === answer.question_id);
      if (!question) return null;
      const selectedText = question.options
        .filter((option) => answer.selected_option_ids.includes(option.id))
        .map((option) => option.text)
        .join("；");
      const correctText = question.options
        .filter((option) => question.correct_option_ids?.includes(option.id))
        .map((option) => option.text)
        .join("；");
      const score = result?.find((item) => item.id === question.id);
      return <article className="panel" key={question.id}>
        <h3>{question.title}</h3>
        <p>你的选择：{selectedText || "未作答"}</p>
        {correctText && <p>正确答案：{correctText}</p>}
        {score && <p>本题得分：{score.score ?? "0"} / {score.max_score}</p>}
      </article>;
    })}
  </div>;
}

function CodeAnswer({ taskId, question, language, onLanguageChange, register, disabled }: {
  taskId: string; question: ProgrammingQuestion; language: AssessmentLanguage;
  onLanguageChange: (language: AssessmentLanguage) => void;
  register: Register; disabled: boolean;
}) {
  const [path, setPath] = useState("");
  const [stdin, setStdin] = useState("");
  const [runId, setRunId] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const toast = useToast();
  const command = useRef<string | null>(null);
  const commandPayload = useRef("");
  const draft = useAutosave<Record<string, string>>({
    draftKey: `${question.id}:${language}`, register, saveOnLoad: !disabled,
    load: async () => { const data = await assessmentApi.codeDraft(taskId, question.id, language); return { value: data.files, version: data.row_version }; },
    save: async (value, version) => { const data = await assessmentApi.saveCode(taskId, question.id, language, value, version); return { value: data.files, version: data.row_version }; },
  });
  const selectedPath = path && draft.value && path in draft.value ? path : Object.keys(draft.value ?? {})[0] ?? "";
  const run = useQuery({
    queryKey: ["assessment-run", taskId, runId],
    queryFn: () => assessmentApi.runResult(taskId, runId!), enabled: runId !== null,
    refetchInterval: (query) => query.state.data?.status === "COMPLETED" ? false : 1500,
  });
  const runCode = async () => {
    setRunning(true);
    try {
      if (!await draft.flush()) return;
      const saved = await assessmentApi.codeDraft(taskId, question.id, language);
      const payload = JSON.stringify([question.id, language, saved.row_version, stdin]);
      if (commandPayload.current !== payload) command.current = null;
      commandPayload.current = payload;
      command.current ??= newIdempotencyKey();
      const result = await assessmentApi.run(taskId, question.id, language, saved.row_version, stdin, command.current);
      command.current = null; setRunId(result.id);
    } catch (error) { toast.notify(error instanceof Error ? error.message : "运行请求失败", "error"); }
    finally { setRunning(false); }
  };
  return <article className="assessment-programming">
    <section className="assessment-statement" aria-labelledby="assessment-question-title">
      <h2 className="assessment-question-title" id="assessment-question-title">{question.title} <small>{question.max_score} 分</small></h2>
      {question.description && <p className="assessment-question-text">{question.description}</p>}
      {question.instructions && <p className="assessment-question-text">{question.instructions}</p>}
      {question.samples.length > 0 && <div className="assessment-samples">
        {question.samples.slice(0, 2).map((sample, index) => <details open key={index}>
          <summary>示例 {index + 1}</summary>
          <div className="assessment-sample-content">
            <div><p>输入</p><pre>{sample.input}</pre></div>
            <div><p>输出</p><pre>{sample.output}</pre></div>
          </div>
          <button type="button" className="btn sm" onClick={() => setStdin(sample.input)}>填入运行输入</button>
        </details>)}
      </div>}
    </section>

    <section className="assessment-code-workspace" aria-label="代码与调试">
      <header className="assessment-editor-toolbar">
        <h2>代码编辑器</h2>
        <label className="assessment-language">语言
          <select className="field" value={language} disabled={disabled} onChange={(event) => onLanguageChange(event.currentTarget.value as AssessmentLanguage)}>
            {question.allowed_languages.map((value) => <option key={value}>{value}</option>)}
          </select>
        </label>
      </header>
      <div className="assessment-code-layout">
        <aside className="assessment-file-pane" aria-label="代码文件">
          <h3>文件</h3>
          <div className="assessment-file-list">
            {Object.keys(draft.value ?? {}).map((file) => <button type="button" key={file} className="btn assessment-file"
              aria-pressed={selectedPath === file} onClick={() => setPath(file)}>
              <Icon name="file-text" size={16} /><span>{file}</span>
            </button>)}
          </div>
          <div className="assessment-file-actions">
            <button type="button" className="btn sm" disabled={disabled || !draft.value} onClick={() => {
              const name = window.prompt("相对文件路径，例如 helper.py");
              if (name && draft.value && !(name in draft.value)) { draft.change({ ...draft.value, [name]: "" }); setPath(name); }
            }}>新增文件</button>
            <button type="button" className="btn sm" disabled={disabled || !selectedPath} onClick={() => {
              const name = window.prompt("新文件路径", selectedPath);
              if (name && draft.value && !(name in draft.value)) {
                const files = { ...draft.value, [name]: draft.value[selectedPath] ?? "" }; delete files[selectedPath];
                draft.change(files); setPath(name);
              }
            }}>重命名</button>
            <button type="button" className="btn sm" disabled={disabled || !selectedPath} onClick={() => {
              if (draft.value && window.confirm(`删除 ${selectedPath}？`)) { const files = { ...draft.value }; delete files[selectedPath]; draft.change(files); }
            }}>删除文件</button>
          </div>
        </aside>
        <div className="assessment-editor-canvas">
          {draft.value && selectedPath ? <CodeEditor key={`${question.id}:${language}:${selectedPath}`}
            value={draft.value[selectedPath] ?? ""} language={language} readOnly={disabled}
            ariaLabel={`代码 ${selectedPath}`} onChange={(content) => draft.change({ ...draft.value!, [selectedPath]: content })} />
            : <p>{draft.value ? "请新增代码文件" : "载入代码中…"}</p>}
        </div>
      </div>
      {draft.touched && <p role="status" className="assessment-save-status">自动保存：{draft.status}
        {draft.failed && <button type="button" className="btn sm" onClick={() => void draft.flush()}>重试保存</button>}
      </p>}
      <section className="assessment-run-panel" aria-labelledby="assessment-run-title">
        <header>
          <h3 id="assessment-run-title">运行调试</h3>
          <button type="button" className="btn primary" disabled={disabled || running || draft.value === null || run.data?.status === "RUNNING" || run.data?.status === "PENDING"} onClick={() => void runCode()}>
            <Icon name="play" size={16} /> 运行代码
          </button>
        </header>
        <label>自定义输入<textarea className="field" rows={3} value={stdin} onChange={(e) => { setStdin(e.target.value); command.current = null; }} /></label>
        <p className="subtle">运行仅使用本页输入。隐藏测试只在正式交卷后执行。</p>
        {run.data && <section className="assessment-run-result" aria-label="运行结果">
          <h3>{STATUS_LABEL[run.data.result_status || run.data.status] ?? run.data.status}</h3>
          <h4>标准输出</h4><pre>{run.data.stdout || "（无输出）"}</pre>
          <h4>错误输出</h4><pre>{run.data.stderr || "（无错误输出）"}</pre>
        </section>}
      </section>
    </section>
  </article>;
}

function ReportAnswer({ taskId, register, disabled }: { taskId: string; register: Register; disabled: boolean }) {
  const toast = useToast();
  const [uploading, setUploading] = useState(false);
  useEffect(() => {
    register("report-upload", () => Promise.resolve(!uploading));
    return () => register("report-upload", null);
  }, [register, uploading]);
  const attachments = useQuery({
    queryKey: ["assessment-attachments", taskId], queryFn: () => assessmentApi.reportDraft(taskId),
    refetchInterval: (query) => {
      const data = query.state.data as { attachments?: Array<{ scan_status: string }> } | undefined;
      return (data?.attachments ?? []).some((a) => a.scan_status === "PENDING") ? 3000 : false;
    },
  });
  return <section className="panel"><h2>实验总报告</h2>
    <p>请上传报告附件。安全扫描完成后可交卷。</p>
    <label>报告附件<input type="file" accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg" disabled={disabled || uploading} onChange={(event) => {
      const file = event.target.files?.[0]; if (!file) return;
      void (async () => {
        setUploading(true);
        try {
          const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
          const mediaTypes: Record<string, string> = { pdf: "application/pdf", docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", txt: "text/plain", md: "text/markdown", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg" };
          if (!mediaTypes[extension]) throw new Error("请选择 PDF、DOCX、文本或图片报告");
          const mediaType = mediaTypes[extension];
          const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
          const digestHex = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
          const created = await reportApi.uploadAttachment(taskId, {
            file_name: file.name, media_type: mediaType, size_bytes: file.size, digest_sha256: digestHex,
          });
          const form = new FormData();
          const upload = created.upload as { url: string; fields: Record<string, string> };
          Object.entries(upload.fields).forEach(([key, value]) => form.append(key, value));
          form.append("file", file);
          const response = await fetch(upload.url, { method: "POST", body: form });
          if (!response.ok) throw new Error("附件上传失败");
          await reportApi.completeAttachment(taskId, created.asset.public_id, created.asset.row_version);
          await attachments.refetch(); toast.notify("附件已上传，安全扫描完成后才能交卷");
        } catch (error) { toast.notify(error instanceof Error ? error.message : "上传失败", "error"); }
        finally { setUploading(false); }
      })();
    }} /></label>
    {attachments.data?.attachments?.map((attachment) => <p key={attachment.asset_id}>{attachment.file_name} · {attachment.scan_status}{attachment.scan_status === "CLEAN" && <AssetActions assetId={attachment.asset_id} title={attachment.file_name} />}</p>)}
  </section>;
}

export function AssessmentWorkbench() {
  const { taskId = "" } = useParams();
  return <AssessmentPage key={taskId} taskId={taskId} />;
}

function downloadSubmittedReport(
  submission: { version_no: number; submitted_at: string; report: string | null },
  taskId: string, score: string | null, maxScore: string | null,
) {
  if (!submission.report) return;
  const submittedAt = new Date(submission.submitted_at).toLocaleString("zh-CN");
  const header = [
    "# 实验报告",
    "",
    `- 任务：${taskId}`,
    `- 提交版本：第 ${submission.version_no} 次`,
    `- 提交时间：${submittedAt}`,
    `- 本部分得分：${score == null ? "待评分" : `${score} / ${maxScore ?? "—"}`}`,
    "",
    "---",
    "",
  ].join("\n");
  const blob = new Blob([header + submission.report], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `experiment-report-${taskId}-v${submission.version_no}-${new Date(submission.submitted_at).toISOString().slice(0, 10)}.md`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function AssessmentPage({ taskId }: { taskId: string }) {
  const toast = useToast();
  const [section, setSection] = useState<"CHOICE" | "PROGRAMMING">("CHOICE");
  const [active, setActive] = useState("");
  const [selectedLanguages, setSelectedLanguages] = useState<Record<string, AssessmentLanguage>>({});
  const [busy, setBusy] = useState(false);
  const [confirmation, setConfirmation] = useState<{ message: string; execute: () => Promise<unknown> } | null>(null);
  const [viewing, setViewing] = useState<HistoryRow | null>(null);
  const [receipt, setReceipt] = useState<{ kind: "CHOICE" | "PROGRAMMING"; version: number; at: string } | null>(null);
  const historyRef = useRef<HTMLDetailsElement>(null);
  const flushes = useRef(new Map<string, Flush>());
  const submitKey = useRef<string | null>(null);
  const submitPayload = useRef("");
  const register = useCallback<Register>((key, flush) => { if (flush) flushes.current.set(key, flush); else flushes.current.delete(key); }, []);
  const assessment = useQuery({ queryKey: keys.assessment(taskId), queryFn: () => assessmentApi.get(taskId), refetchInterval: 10000 });
  const history = useQuery({ queryKey: ["assessment-history", taskId], queryFn: () => assessmentApi.history(taskId), refetchInterval: 10000 });
  const data = assessment.data;
  const choices = data?.questions.filter((q): q is ChoiceQuestion => q.task_type !== "PROGRAMMING") ?? [];
  const programs = data?.questions.filter((q): q is ProgrammingQuestion => q.task_type === "PROGRAMMING") ?? [];
  const selectedSection = choices.length ? section : "PROGRAMMING";
  const selectedQuestion = programs.find((q) => q.id === active) ?? programs[0];
  const language = selectedQuestion ? selectedLanguages[selectedQuestion.id] ?? selectedQuestion.selected_language : "python";
  const sectionState = data?.sections.find((s) => s.kind === selectedSection);
  const choiceSubmission = history.data?.find(
    (row) => row.kind === "CHOICE" && row.is_current,
  ) ?? null;
  const currentReport = history.data?.find(
    (row) => row.kind === "PROGRAMMING" && row.is_current && row.report,
  ) ?? null;
  const programmingState = data?.sections.find((s) => s.kind === "PROGRAMMING");
  const choiceState = data?.sections.find((s) => s.kind === "CHOICE");
  const partLabels = [
    choices.length > 0 ? sectionLabel("CHOICE", choiceState) : null,
    programs.length > 0 ? sectionLabel("PROGRAMMING", programmingState) : null,
  ].filter((label): label is string => Boolean(label));
  const missingParts = [
    choices.length > 0 && choiceState?.status !== "SUBMITTED" ? "选择题" : null,
    programs.length > 0 && programmingState?.status !== "SUBMITTED" ? "编程与报告" : null,
  ].filter((label): label is string => Boolean(label));
  const serverNow = data ? new Date(data.server_time).getTime() + Date.now() - assessment.dataUpdatedAt : Date.now();
  const disabled = !!sectionState && (
    sectionState.editable === false || serverNow >= new Date(sectionState.deadline).getTime()
  );

  async function flushAll() {
    for (const flush of flushes.current.values()) if (!await flush()) return false;
    return true;
  }
  async function switchView(change: () => void) {
    if (await flushAll()) { submitKey.current = null; change(); }
    else toast.notify("请先处理未保存内容或版本冲突", "error");
  }
  async function submit() {
    setBusy(true);
    try {
      if (!await flushAll()) throw new Error("存在未保存内容，请先处理保存失败或冲突");
      submitKey.current ??= newIdempotencyKey();
      if (selectedSection === "CHOICE") {
        const drafts = await Promise.all(choices.map(async (q) => ({ id: q.id, ...await assessmentApi.choiceDraft(taskId, q.id) })));
        const missing = drafts.filter((draft) => !draft.selected_option_ids.length).length;
        const payload = JSON.stringify([selectedSection, drafts]);
        if (submitPayload.current !== payload) submitKey.current = newIdempotencyKey();
        submitPayload.current = payload;
        const key = submitKey.current;
        setConfirmation({
          message: `提交选择题卷？${missing ? `有 ${missing} 道题未作答，将计零分。` : ""}`,
          execute: () => assessmentApi.submitChoices(taskId, Object.fromEntries(drafts.map((d) => [d.id, d.row_version])), key),
        });
      } else {
        const drafts = await Promise.all(programs.map(async (q) => {
          const chosen = selectedLanguages[q.id] ?? q.selected_language;
          return { id: q.id, ...await assessmentApi.codeDraft(taskId, q.id, chosen) };
        }));
        const report = await assessmentApi.reportDraft(taskId);
        const missing = drafts.filter((d) => !Object.values(d.files).some((text) => text.trim())).length;
        const payload = JSON.stringify([selectedSection, drafts, report.row_version]);
        if (submitPayload.current !== payload) submitKey.current = newIdempotencyKey();
        submitPayload.current = payload;
        const key = submitKey.current;
        setConfirmation({
          message: `提交全部编程题和实验总报告？${missing ? `有 ${missing} 道题代码为空，将计零分。` : ""}`,
          execute: () => assessmentApi.submitProgramming(taskId, Object.fromEntries(drafts.map((d) => [d.id, { language: d.language, row_version: d.row_version }])), report.row_version, key),
        });
      }
    } catch (error) { toast.notify(error instanceof Error ? error.message : "交卷失败，请重试", "error"); }
    finally { setBusy(false); }
  }
  async function confirmSubmit() {
    if (!confirmation) return;
    setBusy(true);
    try {
      await confirmation.execute(); submitKey.current = null; setConfirmation(null);
      const kind = selectedSection === "CHOICE" ? "CHOICE" : "PROGRAMMING";
      const result = await history.refetch();
      const rows = (result.data ?? []) as HistoryRow[];
      const latest = rows.find((row) => row.kind === kind && row.is_current) ?? rows.find((row) => row.kind === kind);
      setReceipt({ kind, version: latest?.version_no ?? 1, at: latest?.submitted_at ?? new Date().toISOString() });
      historyRef.current?.setAttribute("open", "");
      window.scrollTo({ top: 0, behavior: "smooth" });
      toast.notify("交卷成功，已固定本次提交版本"); await assessment.refetch();
    } catch (error) { toast.notify(error instanceof Error ? error.message : "交卷失败，请重试", "error"); }
    finally { setBusy(false); }
  }

  if (assessment.isPending) return <LoadingState label="正在载入实验题目" />;
  if (!data) {
    const error = assessment.error as { payload?: { message?: string; detail?: { window?: string } } } | null;
    const windowState = error?.payload?.detail?.window;
    const message = windowState === "not_started"
      ? "实验尚未开放，请在开放时间后再进入。"
      : windowState === "ended"
        ? "实验已截止，无法再进入答题。"
        : error?.payload?.message ?? "实验暂时无法打开";
    return <div className="state-block"><p role="alert">{message}</p><button className="btn" onClick={() => void assessment.refetch()}>重试</button><Link to="/experiments">返回实验列表</Link></div>;
  }
  return <main className="assessment-workbench">
    <Modal open={confirmation !== null} onClose={() => { if (!busy) setConfirmation(null); }} title="确认交卷"
      actions={<><button className="btn" disabled={busy} onClick={() => setConfirmation(null)}>返回检查</button><button className="btn primary" disabled={busy} onClick={() => void confirmSubmit()}>{busy ? "提交中…" : "确认交卷"}</button></>}>
      <p>{confirmation?.message}</p><p>提交后本次内容不能再修改，已提交的版本会保留在交卷历史里。</p>
    </Modal>
    <header className="assessment-header">
      <div>
        {(data.course_title || data.chapter_title) && <p className="assessment-course">
          {[data.course_title, data.chapter_title].filter(Boolean).join(" / ")}
        </p>}
        <h1>{data.title || "实验答题"}</h1>
        {sectionState?.deadline && <p className="assessment-deadline"><Icon name="clock" size={15} /> 本部分截止 {formatDateTime(sectionState.deadline)}</p>}
      </div>
      <Link className="btn assessment-back" to="/experiments" onClick={(e) => { e.preventDefault(); void switchView(() => { window.location.assign("/experiments"); }); }}>
        <Icon name="arrow-left" size={16} /> 返回实验列表
      </Link>
    </header>
    {receipt && <p role="status" className="assessment-receipt">
      <strong>{receipt.kind === "CHOICE" ? "选择题卷" : "编程与报告"}已提交</strong>
      <span>{formatDateTime(receipt.at)} · 第 {receipt.version} 次</span>
      <button className="btn sm" onClick={() => { historyRef.current?.setAttribute("open", ""); historyRef.current?.scrollIntoView({ block: "center" }); }}>查看交卷历史</button>
    </p>}
    <div className="assessment-section-bar">
      <nav className="assessment-sections" aria-label="试卷部分">
        {choices.length > 0 && <button className="btn" aria-pressed={selectedSection === "CHOICE"} onClick={() => void switchView(() => setSection("CHOICE"))}>选择题</button>}
        {programs.length > 0 && <button className="btn" aria-pressed={selectedSection === "PROGRAMMING"} onClick={() => void switchView(() => setSection("PROGRAMMING"))}>编程与报告</button>}
      </nav>
      <p role="status" className="assessment-meta">
        {partLabels.map((label, index) => <span key={label}>
          {index > 0 && <span aria-hidden="true"> · </span>}{label}
        </span>)}
      </p>
    </div>
    {sectionState?.feedback && <p className="assessment-feedback" role="note">教师评语：{sectionState.feedback}</p>}
    {selectedSection === "CHOICE" ? choices.map((question) => <ChoiceAnswer key={question.id} taskId={taskId} question={question} register={register} disabled={disabled}
      submittedSelected={disabled ? choiceSubmission?.answers.find((answer) => answer.question_id === question.id)?.selected_option_ids ?? [] : undefined}
      result={disabled ? sectionState?.questions?.find((item) => item.id === question.id) : undefined} />) : <>
      <nav className="assessment-question-list" aria-label="编程题列表">
        {programs.map((question, index) => <button type="button" className="btn" key={question.id}
          aria-pressed={question.id === selectedQuestion?.id} onClick={() => void switchView(() => setActive(question.id))}>
          {index + 1}. {question.title}
        </button>)}
      </nav>
      {selectedQuestion && <CodeAnswer key={`${selectedQuestion.id}:${language}`} taskId={taskId} question={selectedQuestion}
        language={language} register={register} disabled={disabled} onLanguageChange={(nextLanguage) => {
          void switchView(() => setSelectedLanguages((current) => ({ ...current, [selectedQuestion.id]: nextLanguage })));
        }} />}
      {data.report_required !== false && <>
        {data.report_template && <p className="assessment-report-template">教师报告附件：{data.report_template.file_name}<AssetActions assetId={data.report_template.asset_id} title={data.report_template.file_name} /></p>}
        <ReportAnswer taskId={taskId} register={register} disabled={disabled} />
      </>}
    </>}
    <footer className="panel assessment-submission">
      <div className="assessment-submit-row">
        <div>
          <p>{missingParts.length ? `本实验还有未交部分：${missingParts.join("、")}。` : "本实验各部分已交齐。"}</p>
          {sectionState?.score != null && <p>本部分得分：{sectionState.score} / {sectionState.max_score ?? "—"}</p>}
        </div>
        <button className="btn primary" disabled={busy || disabled} onClick={() => void submit()}>{busy ? "提交中…" : selectedSection === "CHOICE"
          ? (sectionState?.status === "SUBMITTED" ? `再次提交选择题卷（将记为第 ${(sectionState.submission_version ?? 0) + 1} 次）` : "提交选择题卷")
          : (programmingState?.status === "SUBMITTED" ? `再次提交编程与报告卷（将记为第 ${(programmingState.submission_version ?? 0) + 1} 次）` : "提交编程与报告卷")}</button>
      </div>
      {receipt && <p className="subtle"><strong>{receipt.kind === "CHOICE" ? "选择题卷" : "编程与报告"}已提交</strong> · 第 {receipt.version} 次 · {formatDateTime(receipt.at)}。再次提交会记为第 {receipt.version + 1} 次，以最后一次为准。</p>}
      {currentReport && <p><button className="btn" onClick={() => downloadSubmittedReport(currentReport, taskId, programmingState?.score ?? null, programmingState?.max_score ?? null)}>下载已提交报告</button> <span className="subtle">第 {currentReport.version_no} 次提交，不含后续草稿</span></p>}
      <details className="assessment-history" ref={historyRef}>
        <summary>交卷历史</summary>
        {history.data?.length ? history.data.map((submission) => <p key={`${submission.kind}:${submission.version_no}`}>
          {submission.kind === "CHOICE" ? "选择题" : "编程与报告"} · 第 {submission.version_no} 次 · {formatDateTime(submission.submitted_at)}{submission.is_current ? "（当前有效）" : ""}
          {submission.kind === "CHOICE" && <button className="btn sm" onClick={() => setViewing(submission)}>查看答卷</button>}
        </p>) : <p className="subtle">还没有提交记录。提交后这里会显示每次交卷的时间与版本。</p>}
      </details>
    </footer>
    <Modal open={viewing !== null} onClose={() => setViewing(null)} wide
      title={viewing ? `第 ${viewing.version_no} 次提交答卷` : ""}
      actions={<button className="btn" onClick={() => setViewing(null)}>关闭</button>}>
      {viewing && <AnswerSheet submission={viewing} questions={choices}
        result={viewing.is_current ? sectionState?.questions : undefined} />}
    </Modal>
  </main>;
}
