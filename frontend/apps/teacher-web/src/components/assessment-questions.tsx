import { useState } from "react";
import { assessmentTeachingApi, teachingApi } from "@edu/api-client";
import type { AssessmentLanguage, HiddenGroup, TeacherQuestion, TemplateChapter, TemplateVersion } from "@edu/api-client";
import { newIdempotencyKey } from "@edu/auth-client";
import { useToast } from "@edu/ui";
import { importErrorText } from "@/lib/import-errors";
import "./assessment-questions.css";

const languages: AssessmentLanguage[] = ["python", "c", "cpp", "java", "go"];
const entrypoints = { python: "main.py", c: "main.c", cpp: "main.cpp", java: "Main.java", go: "main.go" };
const questionTypeLabels: Record<TeacherQuestion["task_type"], string> = {
  SINGLE_CHOICE: "单选题",
  MULTIPLE_CHOICE: "多选题",
  PROGRAMMING: "编程题",
};
type Option = { id: string; text: string };

export function AssessmentQuestions({ courseId, templateId, version, refresh }: {
  courseId: string; templateId: string; version?: TemplateVersion; refresh: () => Promise<unknown>;
}) {
  const toast = useToast();
  const [chapterId, setChapterId] = useState("");
  const [chapterTitle, setChapterTitle] = useState("");
  const [createdChapters, setCreatedChapters] = useState<TemplateChapter[]>([]);
  const [groupFormOpen, setGroupFormOpen] = useState(false);
  const [questionFormOpen, setQuestionFormOpen] = useState(false);
  const [kind, setKind] = useState<TeacherQuestion["task_type"]>("SINGLE_CHOICE");
  const [editing, setEditing] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [stem, setStem] = useState("");
  const [points, setPoints] = useState("5");
  const [options, setOptions] = useState<Option[]>([{ id: crypto.randomUUID(), text: "" }, { id: crypto.randomUUID(), text: "" }]);
  const [correct, setCorrect] = useState<string[]>([]);
  const [explanation, setExplanation] = useState("");
  const [allowed, setAllowed] = useState<AssessmentLanguage[]>(["python"]);
  const [samples, setSamples] = useState([{ input: "", output: "" }]);
  const [groups, setGroups] = useState<HiddenGroup[]>([{ id: "group1", score: "5", cases: [{ input: "", output: "" }] }]);
  const [referenceLanguage, setReferenceLanguage] = useState<AssessmentLanguage>("python");
  const [reference, setReference] = useState("");
  const [starters, setStarters] = useState<Partial<Record<AssessmentLanguage, Record<string, string>>>>({});
  const [limits, setLimits] = useState<Partial<Record<AssessmentLanguage, { timeout_seconds: number; memory_mb: number }>>>({});
  const [referenceFiles, setReferenceFiles] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importPreview, setImportPreview] = useState<Awaited<ReturnType<typeof assessmentTeachingApi.previewImport>> | null>(null);
  const [importKey, setImportKey] = useState("");
  const serverChapters = version?.chapters ?? [];
  const chapters = [...serverChapters, ...createdChapters.filter(
    created => !serverChapters.some(chapter => chapter.public_id === created.public_id),
  )];
  const selectedChapter = chapters.some(chapter => chapter.public_id === chapterId) ? chapterId : chapters[0]?.public_id || "";
  const locked = version?.status === "PUBLISHED" || version?.status === "PRECHECKING" || busy;

  async function act(operation: () => Promise<unknown>): Promise<unknown | null> {
    setBusy(true);
    try {
      const result = await operation();
      await refresh();
      return result;
    }
    catch (error) { toast.notify(error instanceof Error ? error.message : "操作失败", "error"); return null; }
    finally { setBusy(false); }
  }

  async function addGroup(title: string) {
    if (!version || !title.trim()) return;
    const result = await act(() => teachingApi.createTemplateChapter(
      courseId, version.public_id, { title: title.trim() }, version.row_version,
    ));
    if (!result) return;
    const created = result as TemplateChapter;
    setCreatedChapters(current => [...current, created]);
    setChapterId(created.public_id);
    setChapterTitle("");
    setGroupFormOpen(false);
  }

  async function startQuestion(nextKind: TeacherQuestion["task_type"]) {
    if (!version) return;
    if (!selectedChapter) {
      const result = await act(() => teachingApi.createTemplateChapter(
        courseId, version.public_id, { title: "题目" }, version.row_version,
      ));
      if (!result) return;
      const created = result as TemplateChapter;
      setCreatedChapters(current => [...current, created]);
      setChapterId(created.public_id);
    }
    setEditing(null);
    setTitle("");
    setStem("");
    setPoints("5");
    setOptions([{ id: crypto.randomUUID(), text: "" }, { id: crypto.randomUUID(), text: "" }]);
    setCorrect([]);
    setExplanation("");
    setAllowed(["python"]);
    setSamples([{ input: "", output: "" }]);
    setGroups([{ id: "group1", score: "5", cases: [{ input: "", output: "" }] }]);
    setReferenceLanguage("python");
    setReference("");
    setStarters({});
    setLimits({});
    setReferenceFiles({});
    setPreview(false);
    setKind(nextKind);
    setQuestionFormOpen(true);
  }

  async function save() {
    if (!version || !selectedChapter) return;
    let rowVersion: string | number = version.row_version;
    let questionSpec: Record<string, unknown> = { options };
    let markingSpec: Record<string, unknown> = { correct_option_ids: correct, explanation };
    if (kind === "PROGRAMMING") {
      if (!allowed.includes(referenceLanguage)) throw new Error("参考解语言必须属于允许语言");
      const stored = await assessmentTeachingApi.storeTests(courseId, version.public_id, groups, rowVersion);
      rowVersion = stored.row_version;
      questionSpec = {
        allowed_languages: allowed, samples,
        starter_files: Object.fromEntries(allowed.map((language) => [language, starters[language] ?? { [entrypoints[language]]: "" }])),
        limits: Object.fromEntries(allowed.map((language) => [language, {
          timeout_seconds: ["c", "cpp"].includes(language) ? 2 : 3,
          memory_mb: language === "java" ? 512 : 256,
          ...limits[language],
        }])),
      };
      markingSpec = {
        tests_asset_id: stored.asset_id, groups: groups.map(({ id, score }) => ({ id, score })),
        reference_solutions: { [referenceLanguage]: { ...referenceFiles, [entrypoints[referenceLanguage]]: reference } },
      };
    }
    await assessmentTeachingApi.saveQuestion(courseId, selectedChapter, editing, {
      title, description: stem, instructions: "", task_type: kind,
      max_score: points, question_spec: questionSpec, marking_spec: markingSpec,
    }, rowVersion);
    setEditing(null); setQuestionFormOpen(false); setTitle(""); setStem(""); setCorrect([]);
    toast.notify("题目已保存，请在发布前重新预检");
  }

  async function edit(question: TeacherQuestion, parent: string, copy = false) {
    setEditing(copy ? null : question.public_id); setChapterId(parent); setKind(question.task_type);
    setQuestionFormOpen(true); setPreview(false);
    setTitle(question.title + (copy ? "（副本）" : "")); setStem(question.description || ""); setPoints(question.max_score);
    if (question.task_type !== "PROGRAMMING") {
      setOptions(question.question_spec.options as Option[]);
      setCorrect(question.marking_spec.correct_option_ids as string[]);
      setExplanation(String(question.marking_spec.explanation ?? ""));
    } else {
      const selected = question.question_spec.allowed_languages as AssessmentLanguage[];
      setAllowed(selected); setSamples(question.question_spec.samples as typeof samples);
      setStarters(question.question_spec.starter_files as typeof starters);
      setLimits(question.question_spec.limits as typeof limits);
      const references = question.marking_spec.reference_solutions as Partial<Record<AssessmentLanguage, Record<string, string>>>;
      const language = Object.keys(references)[0] as AssessmentLanguage;
      setReferenceLanguage(language); setReference(references[language]?.[entrypoints[language]] ?? "");
      setReferenceFiles(references[language] ?? {});
      const tests = await assessmentTeachingApi.tests(courseId, question.public_id);
      const scores = question.marking_spec.groups as Array<{ id: string; score: string }>;
      setGroups(tests.groups.map((group) => ({ ...group, score: scores.find((s) => s.id === group.id)?.score ?? "0" })));
    }
  }

  if (!version) return <div className="state-block">
    <p>创建草稿版本后即可添加选择题或编程题。</p>
    <button className="btn primary" disabled={busy} onClick={() => void act(() => teachingApi.createTemplateVersion(courseId, templateId, {}))}>创建空白版本</button>
  </div>;

  return <section className="assessment-editor" aria-label="实验题目编辑">
    <header className="assessment-editor-heading">
      <div>
        <h2>题目</h2>
        <p className="subtle">选择题和编程题分别编辑；题目及答案在发布时固定。</p>
      </div>
      <div className="actions">
        <button type="button" className="btn" disabled={locked} onClick={() => void startQuestion("SINGLE_CHOICE")}>新增选择题</button>
        <button type="button" className="btn primary" disabled={locked} onClick={() => void startQuestion("PROGRAMMING")}>新增编程题</button>
      </div>
    </header>

    {!chapters.length && <div className="state-block">
      <strong>还没有题目</strong>
      <p>第一次添加题目时会自动创建默认分组。</p>
    </div>}
    {chapters.length > 1 && <label className="form-label">新题目所属分组
      <select className="field" value={selectedChapter} onChange={(event) => { setChapterId(event.target.value); setImportPreview(null); }}>
        {chapters.map(chapter => <option key={chapter.public_id} value={chapter.public_id}>{chapter.title}</option>)}
      </select>
    </label>}
    {chapters.map((chapter) => <section className="assessment-question-group" key={chapter.public_id}>
      <h3>{chapter.title}</h3>
      {chapter.tasks.map((raw, position) => {
        const question = raw as unknown as TeacherQuestion;
        return <div className="assessment-question-row" key={question.public_id}>
          <div className="assessment-question-summary">
            <strong>{question.title}</strong>
            <span>{questionTypeLabels[question.task_type]} · {question.max_score ?? "0"} 分</span>
          </div>
          <div className="assessment-question-actions">
            <button type="button" className="btn sm" disabled={locked} onClick={() => void act(() => edit(question, chapter.public_id))}>编辑</button>
            <button type="button" className="btn sm" disabled={locked} onClick={() => void act(() => edit(question, chapter.public_id, true))}>复制</button>
            <button type="button" className="btn sm" disabled={locked || position === 0} onClick={() => void act(() => {
              const ids = chapter.tasks.map((task) => task.public_id);
              [ids[position - 1], ids[position]] = [ids[position]!, ids[position - 1]!];
              return assessmentTeachingApi.reorderQuestions(courseId, chapter.public_id, ids, version.row_version);
            })}>上移</button>
            <button type="button" className="btn sm" disabled={locked} onClick={() => {
              if (window.confirm(`删除题目“${question.title}”？`)) void act(() => assessmentTeachingApi.deleteQuestion(courseId, question.public_id, version.row_version));
            }}>删除</button>
          </div>
        </div>;
      })}
      {!chapter.tasks.length && <p className="subtle">该分组还没有题目。</p>}
    </section>)}

    {chapters.length > 0 && <details className="assessment-editor-optional section">
      <summary>题目分组管理（可选）</summary>
      <p className="subtle">分组只用于整理题目，不影响实验归属。</p>
      {!groupFormOpen
        ? <button type="button" className="btn sm" disabled={locked} onClick={() => setGroupFormOpen(true)}>新增分组</button>
        : <div className="assessment-group-form">
          <label>分组名称<input className="field" value={chapterTitle} onChange={(event) => setChapterTitle(event.target.value)} placeholder="例如：基础练习" /></label>
          <div className="actions">
            <button type="button" className="btn sm" onClick={() => { setGroupFormOpen(false); setChapterTitle(""); }}>取消</button>
            <button type="button" className="btn sm primary" disabled={locked || !chapterTitle.trim()} onClick={() => void addGroup(chapterTitle)}>创建分组</button>
          </div>
        </div>}
    </details>}

    {locked && <p className="subtle">{busy ? "正在处理，请稍候。" : "当前版本已发布或正在预检，不能编辑。请先创建草稿版本。"}</p>}
    {questionFormOpen && selectedChapter && <fieldset className="assessment-question-form" disabled={locked}>
      <legend>{editing ? "编辑题目" : "新增题目"}</legend>
      <div className="assessment-type-switch" role="group" aria-label="题目类型">
        <button type="button" className={`btn sm${kind !== "PROGRAMMING" ? " primary" : ""}`} aria-pressed={kind !== "PROGRAMMING"}
          disabled={locked || Boolean(editing)} onClick={() => { setKind(kind === "MULTIPLE_CHOICE" ? kind : "SINGLE_CHOICE"); setCorrect([]); }}>选择题</button>
        <button type="button" className={`btn sm${kind === "PROGRAMMING" ? " primary" : ""}`} aria-pressed={kind === "PROGRAMMING"}
          disabled={locked || Boolean(editing)} onClick={() => { setKind("PROGRAMMING"); setCorrect([]); }}>编程题</button>
      </div>
      {kind !== "PROGRAMMING" && <label>选择题类型<select className="field" value={kind} onChange={(event) => { setKind(event.target.value as typeof kind); setCorrect([]); }}>
        <option value="SINGLE_CHOICE">单选题</option><option value="MULTIPLE_CHOICE">多选题</option>
      </select></label>}
      <label>标题<input className="field" value={title} onChange={(e) => setTitle(e.target.value)} /></label>
      <label>题干<textarea className="field" rows={5} value={stem} onChange={(e) => setStem(e.target.value)} /></label>
      <label>分值<input className="field" type="number" min="0.01" step="0.01" value={points} onChange={(e) => setPoints(e.target.value)} /></label>
      {kind !== "PROGRAMMING" ? <>
        {options.map((option, index) => <div className="item" key={option.id}>
          <input aria-label={`正确选项 ${index + 1}`} type={kind === "SINGLE_CHOICE" ? "radio" : "checkbox"} name="correct-answer" checked={correct.includes(option.id)} onChange={(e) => setCorrect(kind === "SINGLE_CHOICE" ? [option.id] : e.target.checked ? [...correct, option.id] : correct.filter((id) => id !== option.id))} />
          <label>选项 {index + 1}<textarea className="field" value={option.text} onChange={(e) => setOptions(options.map((o) => o.id === option.id ? { ...o, text: e.target.value } : o))} /></label>
          <button className="btn" disabled={options.length <= 2} onClick={() => { setOptions(options.filter((o) => o.id !== option.id)); setCorrect(correct.filter((id) => id !== option.id)); }}>删除选项</button>
          <button className="btn" disabled={index === 0} onClick={() => {
            const reordered = [...options]; [reordered[index - 1], reordered[index]] = [reordered[index]!, reordered[index - 1]!]; setOptions(reordered);
          }}>选项上移</button>
        </div>)}
        <button className="btn" disabled={options.length >= 6} onClick={() => setOptions([...options, { id: crypto.randomUUID(), text: "" }])}>添加选项</button>
        <label>解析<textarea className="field" value={explanation} onChange={(e) => setExplanation(e.target.value)} /></label>
      </> : <>
        <p>允许语言</p>{languages.map((language) => <label key={language} style={{ marginRight: 16 }}>
          <input type="checkbox" checked={allowed.includes(language)} onChange={(e) => setAllowed(e.target.checked ? [...allowed, language] : allowed.filter((v) => v !== language))} />{language}
        </label>)}
        {allowed.map((language) => <details key={language}><summary>{language} 初始文件与运行限制</summary>
          <label>单用例超时（秒）<input className="field" type="number" min="1" value={limits[language]?.timeout_seconds ?? (["c", "cpp"].includes(language) ? 2 : 3)} onChange={(e) => setLimits({ ...limits, [language]: { memory_mb: limits[language]?.memory_mb ?? (language === "java" ? 512 : 256), timeout_seconds: Number(e.target.value) } })} /></label>
          <label>内存（MiB）<input className="field" type="number" min="1" value={limits[language]?.memory_mb ?? (language === "java" ? 512 : 256)} onChange={(e) => setLimits({ ...limits, [language]: { timeout_seconds: limits[language]?.timeout_seconds ?? 3, memory_mb: Number(e.target.value) } })} /></label>
          <p>入口：{entrypoints[language]}</p>
          {Object.entries(starters[language] ?? { [entrypoints[language]]: "" }).map(([path, content]) => <label key={path}>{path}<textarea className="field" rows={5} value={content} onChange={(e) => setStarters({ ...starters, [language]: { ...(starters[language] ?? {}), [path]: e.target.value } })} /></label>)}
          <label>上传初始源文件<input type="file" multiple onChange={(e) => {
            const files = Array.from(e.target.files ?? []);
            void act(async () => {
              const loaded = await Promise.all(files.map(async (file) => [file.name, await file.text()] as const));
              setStarters((current) => ({ ...current, [language]: { [entrypoints[language]]: "", ...current[language], ...Object.fromEntries(loaded) } }));
            });
          }} /></label>
        </details>)}
        <h3>公开示例</h3>{samples.map((sample, index) => <div key={index} className="section">
          <label>示例输入<textarea className="field" value={sample.input} onChange={(e) => setSamples(samples.map((v, i) => i === index ? { ...v, input: e.target.value } : v))} /></label>
          <label>示例输出<textarea className="field" value={sample.output} onChange={(e) => setSamples(samples.map((v, i) => i === index ? { ...v, output: e.target.value } : v))} /></label>
          <button className="btn" disabled={samples.length <= 1} onClick={() => setSamples(samples.filter((_, i) => i !== index))}>删除示例</button>
        </div>)}
        <button className="btn" onClick={() => setSamples([...samples, { input: "", output: "" }])}>新增示例</button>
        <h3>隐藏测试组（学生不可见）</h3>
        <label>导入隐藏用例 JSON<input type="file" accept=".json" onChange={(e) => {
          const file = e.target.files?.[0]; if (!file) return;
          void act(async () => {
            const parsed: unknown = JSON.parse(await file.text());
            if (!parsed || typeof parsed !== "object" || !("groups" in parsed) || !Array.isArray(parsed.groups)) throw new Error("需要包含 groups 数组的固定 JSON");
            setGroups(parsed.groups as HiddenGroup[]);
          });
        }} /></label>
        <button className="btn" onClick={() => {
          const url = URL.createObjectURL(new Blob([JSON.stringify({ groups }, null, 2)], { type: "application/json" }));
          const a = document.createElement("a"); a.href = url; a.download = "hidden-tests.json"; a.click(); URL.revokeObjectURL(url);
        }}>导出隐藏用例 JSON</button>
        {groups.map((group, index) => <div className="section" key={group.id}>
          <label>本组分值<input className="field" type="number" min="0.01" step="0.01" value={group.score} onChange={(e) => setGroups(groups.map((v, i) => i === index ? { ...v, score: e.target.value } : v))} /></label>
          {group.cases.map((test, caseIndex) => <div key={caseIndex}>
            <label>隐藏输入<textarea className="field" value={test.input} onChange={(e) => setGroups(groups.map((g, i) => i === index ? { ...g, cases: g.cases.map((c, n) => n === caseIndex ? { ...c, input: e.target.value } : c) } : g))} /></label>
            <label>预期输出<textarea className="field" value={test.output} onChange={(e) => setGroups(groups.map((g, i) => i === index ? { ...g, cases: g.cases.map((c, n) => n === caseIndex ? { ...c, output: e.target.value } : c) } : g))} /></label>
            <button className="btn" disabled={group.cases.length <= 1} onClick={() => setGroups(groups.map((g, i) => i === index ? { ...g, cases: g.cases.filter((_, n) => n !== caseIndex) } : g))}>删除用例</button>
          </div>)}
          <button className="btn" onClick={() => setGroups(groups.map((g, i) => i === index ? { ...g, cases: [...g.cases, { input: "", output: "" }] } : g))}>本组新增用例</button>
          <button className="btn" disabled={groups.length <= 1} onClick={() => setGroups(groups.filter((_, i) => i !== index))}>删除测试组</button>
        </div>)}
        <button className="btn" onClick={() => setGroups([...groups, { id: crypto.randomUUID(), score: "1", cases: [{ input: "", output: "" }] }])}>新增测试组</button>
        <label>参考解语言<select className="field" value={referenceLanguage} onChange={(e) => setReferenceLanguage(e.target.value as AssessmentLanguage)}>{allowed.map((language) => <option key={language}>{language}</option>)}</select></label>
        <label>参考解代码<textarea className="field" rows={10} value={reference} onChange={(e) => setReference(e.target.value)} /></label>
        <label>参考解的其他源文件<input type="file" multiple onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          void act(async () => setReferenceFiles(Object.fromEntries(await Promise.all(files.map(async (file) => [file.name, await file.text()])))));
        }} /></label>
      </>}
      <button className="btn" onClick={() => setPreview(!preview)}>预览题面</button>
      <button type="button" className="btn" onClick={() => { setQuestionFormOpen(false); setEditing(null); setPreview(false); }}>取消</button>
      <button className="btn primary" disabled={!title.trim()} onClick={() => void act(save)}>保存题目</button>
    </fieldset>}
    {preview && <article className="panel"><h3>{title}</h3><pre style={{ whiteSpace: "pre-wrap" }}>{stem}</pre>
      {kind === "PROGRAMMING" ? samples.map((s, i) => <div key={i}><pre>{s.input}</pre><pre>{s.output}</pre></div>) : options.map((o) => <p key={o.id}>○ {o.text}</p>)}
    </article>}
    <details className="assessment-editor-optional">
      <summary>批量导入选择题（Excel / Word）</summary>
      <p className="subtle">此处只导入选择题；编程题请使用上方“新增编程题”。导入前会先预检格式和分值。</p>
      {!selectedChapter && <button type="button" className="btn sm" disabled={locked} onClick={() => void startQuestion("SINGLE_CHOICE")}>创建题目分组</button>}
      {selectedChapter && <>
        <a className="btn sm" href="/api/v2/teaching/choice-import-template" download>下载选择题导入模板</a>
        <p className="subtle">Word 格式：题干以“1. ”开头，选项单独成段，答案、分值和解析各占一行。</p>
        <input aria-label="导入选择题 Excel 或 Word" type="file" accept=".xlsx,.docx" onChange={(event) => { setImportFile(event.target.files?.[0] ?? null); setImportPreview(null); }} />
        <button type="button" className="btn sm" disabled={!importFile || busy} onClick={() => void act(async () => {
          const result = await assessmentTeachingApi.previewImport(courseId, selectedChapter, importFile!);
          setImportPreview(result); setImportKey(newIdempotencyKey());
        })}>预检导入</button>
        {importPreview && <div className="assessment-import-preview">
          {importPreview.errors.length > 0
            ? <p>预检通过 {importPreview.rows.length} 道题，共 {importPreview.total_score} 分；有 {importPreview.errors.length} 行错误，请修正后重试。</p>
            : <p>将追加 {importPreview.count} 道题，共 {importPreview.total_score} 分。</p>}
          {importPreview.rows.map((question, index) => <p key={index}>{index + 1}. {question.description}（{question.max_score} 分）</p>)}
          {importPreview.errors.map((error) => <p role="alert" key={error.row}>第 {error.row} 行：{importErrorText(error.error)}</p>)}
          <button type="button" className="btn sm primary" disabled={!importPreview.token || busy} onClick={() => void act(async () => {
            await assessmentTeachingApi.confirmImport(courseId, selectedChapter, importFile!, importPreview.token!, importKey);
            setImportPreview(null);
          })}>确认导入</button>
        </div>}
      </>}
    </details>
  </section>;
}
