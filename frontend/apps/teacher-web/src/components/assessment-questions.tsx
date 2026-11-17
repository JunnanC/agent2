import { useQuery } from "@tanstack/react-query";
import { keys } from "@edu/query-keys";
import { useState } from "react";
import { assessmentTeachingApi, teachingApi } from "@edu/api-client";
import type { AssessmentLanguage, HiddenGroup, TeacherQuestion, TemplateVersion } from "@edu/api-client";
import { request, newIdempotencyKey } from "@edu/auth-client";
import { useToast } from "@edu/ui";
import { importErrorText } from "@/lib/import-errors";

const languages: AssessmentLanguage[] = ["python", "c", "cpp", "java", "go"];
const entrypoints = { python: "main.py", c: "main.c", cpp: "main.cpp", java: "Main.java", go: "main.go" };
type Option = { id: string; text: string };

export function AssessmentQuestions({ courseId, templateId, version, refresh }: {
  courseId: string; templateId: string; version?: TemplateVersion; refresh: () => Promise<unknown>;
}) {
  const toast = useToast();
  const [chapterId, setChapterId] = useState("");
  const [sourceChapter, setSourceChapter] = useState("");
  const sourceChapters = useQuery({ queryKey: keys.courseResource(courseId, "chapters"), queryFn: () => teachingApi.courseResource<{public_id: string; title: string}>(courseId, "chapters") });
  const [chapterTitle, setChapterTitle] = useState("");
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
  const chapters = version?.chapters ?? [];
  const selectedChapter = chapters.some(chapter => chapter.public_id === chapterId) ? chapterId : chapters[0]?.public_id || "";
  const locked = version?.status === "PUBLISHED" || version?.status === "PRECHECKING" || busy;

  async function act(operation: () => Promise<unknown>) {
    setBusy(true);
    try { await operation(); await refresh(); }
    catch (error) { toast.notify(error instanceof Error ? error.message : "操作失败", "error"); }
    finally { setBusy(false); }
  }

  async function save() {
    if (!version) return;
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
    setEditing(null); setTitle(""); setStem(""); setCorrect([]);
    toast.notify("题目已保存，请在发布前重新预检");
  }

  async function edit(question: TeacherQuestion, parent: string, copy = false) {
    setEditing(copy ? null : question.public_id); setChapterId(parent); setKind(question.task_type);
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
    <p>先创建空白草稿版本，再添加章节和题目。纯选择题无需配置运行环境。</p>
    <button className="btn primary" disabled={busy} onClick={() => void act(() => teachingApi.createTemplateVersion(courseId, templateId, {}))}>创建空白版本</button>
  </div>;

  return <section aria-label="实验题目编辑">
    <h2>选择题与编程题</h2>
    <p className="subtle">题目及答案在发布时冻结；标准答案、隐藏用例和参考解仅教师可见。</p>
    {chapters.map((chapter) => <div className="section" key={chapter.public_id}>
      <h3>{chapter.title}</h3>
      {chapter.tasks.map((raw, position) => {
        const question = raw as unknown as TeacherQuestion;
        return <div className="item" key={question.public_id}>
          <strong>{question.title}</strong>　{question.task_type}　{question.max_score ?? "0"} 分
          <button className="btn" disabled={locked} onClick={() => void act(() => edit(question, chapter.public_id))}>编辑</button>
          <button className="btn" disabled={locked} onClick={() => void act(() => edit(question, chapter.public_id, true))}>复制</button>
          <button className="btn" disabled={locked || position === 0} onClick={() => void act(() => {
            const ids = chapter.tasks.map((q) => q.public_id);
            [ids[position - 1], ids[position]] = [ids[position]!, ids[position - 1]!];
            return assessmentTeachingApi.reorderQuestions(courseId, chapter.public_id, ids, version.row_version);
          })}>上移</button>
          <button className="btn" disabled={locked} onClick={() => {
            if (window.confirm(`删除题目“${question.title}”？`)) void act(() => assessmentTeachingApi.deleteQuestion(courseId, question.public_id, version.row_version));
          }}>删除</button>
        </div>;
      })}
    </div>)}
    {locked && <p className="subtle">{busy ? "正在处理，请稍候。" : "当前版本已发布或正在预检，章节和题目暂不可编辑。请创建草稿版本后修改。"}</p>}
    <fieldset disabled={locked}>
      <legend>模板内部章节与批量导入</legend>
      <p className="subtle">模板内部章节用于组织题目；实验所属课程章节在发布时选择。</p>
      <label>导入课程章节<select className="field" value={sourceChapter} onChange={event => setSourceChapter(event.target.value)}><option value="">选择要复制内容的课程章节</option>{sourceChapters.data?.rows.map(chapter => <option key={chapter.public_id} value={chapter.public_id}>{chapter.title}</option>)}</select></label>
      <button className="btn" disabled={!sourceChapter} onClick={() => void act(async () => { await request(`/teaching/courses/${courseId}/template-versions/${version.public_id}/import-course-chapter`, {method: "POST", body: {chapter_id: sourceChapter}, ifMatch: version.row_version, idempotencyKey: newIdempotencyKey()}); setSourceChapter(""); })}>导入为模板章节</button>
      {sourceChapters.error ? <p role="alert">课程章节加载失败。</p> : null}
      {!chapters.length && <p>暂无模板章节，请新增或导入章节后再添加题目。</p>}
      <label>章节名称<input className="field" value={chapterTitle} onChange={(e) => setChapterTitle(e.target.value)} /></label>
      <button className="btn" disabled={!chapterTitle.trim()} onClick={() => void act(() => teachingApi.createTemplateChapter(courseId, version.public_id, { title: chapterTitle }, version.row_version))}>新增章节</button>
      <label>当前章节<select className="field" value={selectedChapter} onChange={(e) => { setChapterId(e.target.value); setImportPreview(null); }}>
        {chapters.map((c) => <option key={c.public_id} value={c.public_id}>{c.title}</option>)}
      </select></label>
      <a className="btn" href="/api/v2/teaching/choice-import-template" download>下载 Excel 模板</a>
      <p className="subtle">Word 支持 .docx：每题以“1. 题干”开始，选项各占一段（A.、B.），随后填写“答案：B”“分值：5”“解析：说明”。</p>
      <p className="subtle">多选题的正确答案用英文逗号分隔，例如 A,C；答案必须是该题已填写的选项。</p>
      <input aria-label="导入选择题 Excel 或 Word" type="file" accept=".xlsx,.docx" onChange={(e) => { setImportFile(e.target.files?.[0] ?? null); setImportPreview(null); }} />
      <button className="btn" disabled={!importFile || !selectedChapter} onClick={() => void act(async () => {
        const result = await assessmentTeachingApi.previewImport(courseId, selectedChapter, importFile!);
        setImportPreview(result); setImportKey(newIdempotencyKey());
      })}>预检导入</button>
      {importPreview && <div className="section">
        {importPreview.errors.length > 0
          ? <p>预检通过 {importPreview.rows.length} 道题，共 {importPreview.total_score} 分；有 {importPreview.errors.length} 行错误，修正全部错误后才能追加。</p>
          : <p>将追加 {importPreview.count} 道题，共 {importPreview.total_score} 分。</p>}
        {importPreview.rows.map((q, i) => <p key={i}>{i + 1}. {q.description}（{q.max_score} 分）</p>)}
        {importPreview.errors.map((error) => <p role="alert" key={error.row}>第 {error.row} 行：{importErrorText(error.error)}</p>)}
        <button className="btn primary" disabled={!importPreview.token} onClick={() => void act(async () => {
          await assessmentTeachingApi.confirmImport(courseId, selectedChapter, importFile!, importPreview.token!, importKey);
          setImportPreview(null);
        })}>确认追加</button>
      </div>}
    </fieldset>
    <fieldset disabled={locked || !selectedChapter}>
      <legend>{editing ? "编辑题目" : "新增题目"}</legend>
      <label>题型<select className="field" value={kind} onChange={(e) => { setKind(e.target.value as typeof kind); setCorrect([]); }}>
        <option value="SINGLE_CHOICE">单选题</option><option value="MULTIPLE_CHOICE">多选题</option><option value="PROGRAMMING">编程题</option>
      </select></label>
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
      <button className="btn primary" disabled={!title.trim()} onClick={() => void act(save)}>保存题目</button>
    </fieldset>
    {preview && <article className="panel"><h3>{title}</h3><pre style={{ whiteSpace: "pre-wrap" }}>{stem}</pre>
      {kind === "PROGRAMMING" ? samples.map((s, i) => <div key={i}><pre>{s.input}</pre><pre>{s.output}</pre></div>) : options.map((o) => <p key={o.id}>○ {o.text}</p>)}
    </article>}
  </section>;
}
