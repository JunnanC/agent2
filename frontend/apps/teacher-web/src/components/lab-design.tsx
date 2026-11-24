import { useId, useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { labAssessmentApi, type LabCase, type LabDesignInput, type LabEnvironment, type LabQuestion } from "@edu/api-client";
import { Modal, useToast } from "@edu/ui";
import { apiErrorMessage } from "@/lib/format";
import "./lab-workbench.css";

const fieldLabels = { CHOICE: "选择题", PROGRAMMING: "编程题", REPORT: "报告" } as const;
const kindLabels = { SINGLE_CHOICE: "单选题", MULTIPLE_CHOICE: "多选题", PROGRAMMING: "编程题" } as const;
const codeEntry = { python: "main.py", c: "main.c", cpp: "main.cpp", java: "Main.java", go: "main.go" } as const;

function localDate(value: string) {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function blankDesign(): LabDesignInput {
  return {
    title: "", guidance: "", report_requirements: "", environment_id: "",
    window_start: localDate(new Date().toISOString()), window_end: "",
    questions: [], part_maxima: { CHOICE: "0", PROGRAMMING: "0", REPORT: "0" },
  };
}

function newQuestion(task_type: LabQuestion["task_type"]): LabQuestion {
  return task_type === "PROGRAMMING"
    ? { task_type, title: "", description: "", explanation: "", starter_code: "", timeout_seconds: 5,
        samples: [{ input: "", output: "" }], hidden_cases: [{ input: "", output: "" }] }
    : { task_type, title: "", description: "", explanation: "",
        options: [{ id: "A", text: "" }, { id: "B", text: "" }], correct_option_ids: [] };
}

export function LabDesignDialog({ courseId, publicationId, onClose, onSaved }: {
  courseId: string;
  publicationId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const formId = useId();
  const [busy, setBusy] = useState(false);
  const saved = useQuery({
    queryKey: ["experiment-design", courseId, publicationId],
    queryFn: () => labAssessmentApi.design(courseId, publicationId), enabled: Boolean(publicationId),
  });
  const environments = useQuery({
    queryKey: ["lab-environments", courseId],
    queryFn: () => labAssessmentApi.environments(courseId),
  });
  let initial: LabDesignInput | undefined;
  if (saved.data) {
    const { design, title, window_start, window_end, environment_id } = saved.data;
    initial = {
      ...design, title, environment_id: environment_id ?? "",
      window_start: localDate(window_start), window_end: localDate(window_end),
      questions: design.questions.map((item) => {
        const language = item.question_spec.allowed_languages?.[0];
        const code = language ? item.question_spec.starter_files?.[language]?.[codeEntry[language]] : "";
        return {
          task_type: item.task_type, title: item.title, description: item.description,
          explanation: item.marking_spec.explanation ?? "", options: item.question_spec.options,
          correct_option_ids: item.marking_spec.correct_option_ids, samples: item.question_spec.samples,
          hidden_cases: item.marking_spec.hidden_cases, starter_code: code,
          timeout_seconds: language ? item.question_spec.limits?.[language]?.timeout_seconds : undefined,
        };
      }),
    };
  }
  const formReady = Boolean((initial || !publicationId) && environments.data && !environments.isError && !saved.isError);
  return <Modal open wide title={publicationId ? "编辑实验草稿" : "新建实验"}
    onClose={() => { if (!busy) onClose(); }}
    actions={<>
      <button className="btn" type="button" disabled={busy} onClick={onClose}>取消</button>
      <button className="btn primary" type="submit" form={formId}
        disabled={!formReady || busy}>保存实验草稿</button>
    </>}>
    {saved.isError || environments.isError
      ? <p role="alert">读取失败。 <button className="btn" onClick={() => {
          if (publicationId) void saved.refetch();
          void environments.refetch();
        }}>重试</button></p>
      : publicationId && !initial || environments.isPending ? <p role="status">正在加载实验配置…</p>
      : <LabDesignForm key={publicationId} courseId={courseId}
          initial={initial ?? blankDesign()} environments={environments.data?.rows ?? []}
          target={saved.data ? { id: publicationId, version: saved.data.row_version } : undefined}
          formId={formId} onBusyChange={setBusy} onSaved={onSaved} />}
  </Modal>;
}

function LabDesignForm({ courseId, initial, environments, target, formId, onBusyChange, onSaved }: {
  courseId: string;
  initial: LabDesignInput;
  environments: LabEnvironment[];
  target?: { id: string; version: number };
  formId: string;
  onBusyChange: (busy: boolean) => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [form, setForm] = useState(initial);
  const [purpose, setPurpose] = useState("");
  const [active, setActive] = useState(0);
  const question = form.questions[active];
  const environment = environments.find((item) => item.public_id === form.environment_id);
  function update<K extends keyof LabDesignInput>(key: K, value: LabDesignInput[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }
  const changeQuestion = (changed: LabQuestion) =>
    setForm((current) => ({ ...current, questions: current.questions.map((item, index) => index === active ? changed : item) }));
  function addQuestion(kind: LabQuestion["task_type"]) {
    update("questions", [...form.questions, newQuestion(kind)]);
    setActive(form.questions.length);
  }

  const suggest = useMutation({
    mutationFn: () => labAssessmentApi.suggest(courseId, purpose.trim(), environment?.language),
    onMutate: () => onBusyChange(true),
    onSettled: () => onBusyChange(false),
    onSuccess: (draft) => {
      setActive(form.questions.length);
      setForm((current) => ({
        ...current,
        guidance: current.guidance || draft.guidance,
        report_requirements: current.report_requirements || draft.report_requirements,
        questions: [...current.questions, ...draft.questions.slice(0, 50 - current.questions.length)],
      }));
      toast.notify("AI 草稿已加入，请核对题意、答案和报告要求");
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });
  const save = useMutation({
    mutationFn: () => labAssessmentApi.saveDesign(courseId, {
      ...form,
      window_start: new Date(form.window_start).toISOString(),
      window_end: new Date(form.window_end).toISOString(),
    }, target),
    onSuccess: () => { toast.notify("实验草稿已保存"); onSaved(); },
    onMutate: () => onBusyChange(true),
    onSettled: () => onBusyChange(false),
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!save.isPending && !suggest.isPending) save.mutate();
  }

  return <form className="lab-form" id={formId} onSubmit={submit}>
    <div className="lab-fields">
      <label>实验名称<input className="field" value={form.title} required maxLength={180}
        onChange={(event) => update("title", event.target.value)} /></label>
      <label>实验环境<select className="field" value={form.environment_id}
        onChange={(event) => update("environment_id", event.target.value)}>
        <option value="">请选择环境（编程题必选）</option>
        {environments.map((item) => <option key={item.public_id} value={item.public_id}>{item.display_name}</option>)}
      </select></label>
      <label>开放时间<input className="field" type="datetime-local" value={form.window_start} required
        onChange={(event) => update("window_start", event.target.value)} /></label>
      <label>截止时间<input className="field" type="datetime-local" value={form.window_end} required
        onChange={(event) => update("window_end", event.target.value)} /></label>
    </div>
    <div className="lab-fields lab-maxima">
      {Object.entries(fieldLabels).map(([key, label]) => {
        const kind = key as keyof LabDesignInput["part_maxima"];
        return <label key={kind}>{label}满分<input className="field" type="number" step="0.01" required
          min="0" max="999.99" value={form.part_maxima[kind]}
          onChange={(event) => update("part_maxima", { ...form.part_maxima, [kind]: event.target.value })} /></label>;
      })}
    </div>
    <label>实验指导<textarea className="field" rows={4} maxLength={30000} value={form.guidance}
      onChange={(event) => update("guidance", event.target.value)} /></label>
    <label>Word 报告要求<textarea className="field" rows={3} maxLength={16000} value={form.report_requirements}
      placeholder="写明须提交的代码、截图和格式"
      onChange={(event) => update("report_requirements", event.target.value)} /></label>
    <section className="lab-section">
      <h3>题目</h3>
      <div className="lab-inline-action">
        <label>实验目的<input className="field" value={purpose} maxLength={4000}
          onChange={(event) => setPurpose(event.target.value)} /></label>
        <button className="btn" type="button"
          disabled={!purpose.trim() || form.questions.length >= 50 || suggest.isPending || save.isPending}
          onClick={() => suggest.mutate()}>{suggest.isPending ? "正在生成…" : "生成 AI 草稿"}</button>
      </div>
      <div className="page-actions">
        {Object.entries(kindLabels).map(([kind, label]) => (
          <button className="btn sm" type="button" key={kind} disabled={form.questions.length >= 50}
            onClick={() => addQuestion(kind as LabQuestion["task_type"])}>添加{label}</button>
        ))}
      </div>
      {form.questions.length > 0 && <div className="lab-question-workspace">
        <nav aria-label="题目列表" className="lab-question-tabs">
          {form.questions.map((item, index) => <button type="button" className="btn" key={index}
            onClick={() => setActive(index)} aria-pressed={active === index}>
            {index + 1}. {item.title || kindLabels[item.task_type]}
          </button>)}
        </nav>
        {question && <div className="lab-form">
          <div className="lab-heading-row">
            <h4>{kindLabels[question.task_type]}</h4>
            <button className="btn sm" type="button" onClick={() => {
              update("questions", form.questions.filter((_, index) => index !== active));
              setActive(Math.max(0, active - 1));
            }}>删除本题</button>
          </div>
          <label>题目名称<input className="field" value={question.title} maxLength={160}
            onChange={(event) => changeQuestion({ ...question, title: event.target.value })} /></label>
          <label>题干<textarea className="field" rows={3} value={question.description} maxLength={20000}
            onChange={(event) => changeQuestion({ ...question, description: event.target.value })} /></label>
          {question.task_type === "PROGRAMMING"
            ? <>
                <label>初始代码 {environment && `· ${codeEntry[environment.language]}`}
                  <textarea className="field lab-code" rows={4} value={question.starter_code ?? ""}
                    onChange={(event) => changeQuestion({ ...question, starter_code: event.target.value })} /></label>
                <label>每例超时（秒）<input className="field" type="number" min="1" max="30"
                  value={question.timeout_seconds ?? 5}
                  onChange={(event) => changeQuestion({ ...question, timeout_seconds: Number(event.target.value) })} /></label>
                <Cases title="公开样例" rows={question.samples ?? []} maximum={20}
                  onChange={(samples) => changeQuestion({ ...question, samples })} />
                <Cases title="隐藏用例" rows={question.hidden_cases ?? []} maximum={100}
                  onChange={(hidden_cases) => changeQuestion({ ...question, hidden_cases })} />
              </>
            : <Choices value={question} onChange={changeQuestion} />}
          <label>题目解析（成绩发布后可见）<textarea className="field" rows={3} value={question.explanation}
            maxLength={20000}
            onChange={(event) => changeQuestion({ ...question, explanation: event.target.value })} /></label>
        </div>}
      </div>}
    </section>
    {save.isPending && <p role="status">正在保存实验草稿…</p>}
  </form>;
}

function Choices({ value, onChange }: { value: LabQuestion; onChange: (value: LabQuestion) => void }) {
  const options = value.options ?? [];
  const correct = value.correct_option_ids ?? [];
  const multi = value.task_type === "MULTIPLE_CHOICE";
  return <fieldset className="lab-cases">
    <legend>选项与正确答案</legend>
    {options.map((option, index) => <div className="lab-option" key={option.id}>
      <label><input type={multi ? "checkbox" : "radio"} name="lab-correct-option"
        checked={correct.includes(option.id)}
        onChange={() => onChange({ ...value, correct_option_ids: multi
          ? correct.includes(option.id) ? correct.filter((id) => id !== option.id) : [...correct, option.id]
          : [option.id] })} /> 正确</label>
      <input className="field" aria-label={`选项 ${index + 1}`} value={option.text} maxLength={20000}
        onChange={(event) => onChange({ ...value, options: options.map((item) => item.id === option.id
          ? { ...item, text: event.target.value } : item) })} />
      <button className="btn sm" type="button" disabled={options.length <= 2}
        onClick={() => onChange({ ...value, options: options.filter((item) => item.id !== option.id),
          correct_option_ids: correct.filter((id) => id !== option.id) })}>删除</button>
    </div>)}
    <button className="btn sm" type="button" disabled={options.length >= 6} onClick={() => {
      const id = ["A", "B", "C", "D", "E", "F"].find((candidate) => !options.some((item) => item.id === candidate))!;
      onChange({ ...value, options: [...options, { id, text: "" }] });
    }}>添加选项</button>
  </fieldset>;
}

function Cases({ title, rows, maximum, onChange }: {
  title: string; rows: LabCase[]; maximum: number; onChange: (value: LabCase[]) => void;
}) {
  return <fieldset className="lab-cases">
    <legend>{title}</legend>
    {rows.map((item, index) => <div className="lab-case-row" key={index}>
      <label>输入 {index + 1}<textarea className="field lab-code" rows={2} value={item.input}
        onChange={(event) => onChange(rows.map((row, position) => position === index ? { ...row, input: event.target.value } : row))} /></label>
      <label>预期输出<textarea className="field lab-code" rows={2} value={item.output}
        onChange={(event) => onChange(rows.map((row, position) => position === index ? { ...row, output: event.target.value } : row))} /></label>
      <button className="btn sm" type="button" disabled={rows.length <= 1}
        onClick={() => onChange(rows.filter((_, position) => position !== index))}>删除</button>
    </div>)}
    <button className="btn sm" type="button" disabled={rows.length >= maximum}
      onClick={() => onChange([...rows, { input: "", output: "" }])}>新增{title}</button>
  </fieldset>;
}
