import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { request, newIdempotencyKey } from "@edu/auth-client";
import { fileApi, teachingApi } from "@edu/api-client";
import type { Material } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, EmptyState, Icon, Modal, Panel, RequestStateView, useToast } from "@edu/ui";
import { chapterLabel, chapterName, chapterTitle } from "@/lib/chapter-title";
import { apiErrorMessage } from "@/lib/format";
import "./course-materials.css";

type Chapter = { public_id: string; title: string; summary?: string; content?: string; status: string; position: number; row_version: number };
type MaterialVersion = { public_id: string; row_version: number; status: string };
const statusName = (status?: string | null) => status === "PUBLISHED" ? "已发布" : status === "WITHDRAWN" ? "已撤回" : "草稿";
const sizeLabel = (size?: number | null) => size == null ? "—" : size >= 1048576 ? `${(size / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.ceil(size / 1024))} KB`;

export function CourseMaterials({ courseId }: { courseId: string }) {
  const toast = useToast();
  const base = `/teaching/courses/${courseId}`;
  const initialized = useRef(false);
  const nameInput = useRef<HTMLInputElement>(null);
  const [editing, setEditing] = useState<Chapter | null>(null);
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [aiDraft, setAiDraft] = useState<string | null>(null);
  const [materialChapterId, setMaterialChapterId] = useState("");
  const [materialName, setMaterialName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileKey, setFileKey] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [textMaterial, setTextMaterial] = useState<Material | null>(null);
  const chapters = useQuery({ queryKey: keys.courseResource(courseId, "chapters"), queryFn: () => teachingApi.courseResource<Chapter>(courseId, "chapters") });
  const materials = useQuery({ queryKey: keys.courseResource(courseId, "materials"), queryFn: () => teachingApi.courseResource<Material>(courseId, "materials") });
  const rows = useMemo(() => [...(chapters.data?.rows ?? [])].sort((a, b) => a.position - b.position), [chapters.data]);
  const nextPosition = Math.max(0, ...rows.map(row => row.position)) + 1;
  const position = editing?.position ?? nextPosition;
  const materialChapter = rows.find(row => row.public_id === materialChapterId) ?? rows[0];
  const materialRows = (materials.data?.rows ?? []).filter(row => row.chapter_id === materialChapter?.public_id);
  const publishedCount = materialRows.filter(row => row.version_status === "PUBLISHED").length;
  const readOnly = editing?.status === "PUBLISHED";

  useEffect(() => {
    if (chapters.isSuccess && !initialized.current) {
      initialized.current = true;
      const chapter = rows[0];
      if (chapter) {
        setEditing(chapter); setName(chapterName(chapter.title)); setContent(chapter.content || chapter.summary || "");
      }
    }
  }, [chapters.isSuccess, rows]);

  const notifyError = (error: Error) => toast.notify("payload" in error ? apiErrorMessage(error) : error.message, "error");
  const refreshChapters = () => { void chapters.refetch(); };
  const refreshMaterials = () => { void materials.refetch(); };
  const loadEditor = (chapter: Chapter) => {
    setEditing(chapter); setName(chapterName(chapter.title)); setContent(chapter.content || chapter.summary || ""); setAiDraft(null);
  };
  const persistChapter = async (): Promise<Chapter> => {
    const title = chapterTitle(position, name);
    if (!chapterName(name)) throw new Error("请填写章节名称");
    if (editing && title === editing.title && content === (editing.content || editing.summary || "")) return editing;
    const result = await request<Chapter>(editing ? `${base}/chapters/${editing.public_id}` : `${base}/chapters`, {
      method: editing ? "PATCH" : "POST", ifMatch: editing?.row_version, idempotencyKey: newIdempotencyKey(),
      body: { title, content, summary: content.slice(0, 500), ...(editing ? {} : { position }) },
    });
    // Preserve the fresh version even when a following publish request fails.
    setEditing(result.data);
    return result.data;
  };
  const save = useMutation({
    mutationFn: persistChapter,
    onSuccess: chapter => { loadEditor(chapter); refreshChapters(); toast.notify("章节草稿已保存，评审后可单独发布"); },
    onError: (error: Error) => { notifyError(error); refreshChapters(); },
  });
  const generate = useMutation({
    mutationFn: () => request<{ content: string }>(`${base}/chapter-drafts/generate`, {
      method: "POST", body: { title: chapterTitle(position, name) }, idempotencyKey: newIdempotencyKey(),
    }),
    onSuccess: result => setAiDraft(result.data.content), onError: notifyError,
  });
  const chapterStatus = useMutation({
    mutationFn: async () => {
      const chapter = readOnly ? editing! : await persistChapter();
      return request<Chapter>(`${base}/chapters/${chapter.public_id}/${readOnly ? "withdrawn" : "published"}`, {
        method: "POST", body: {}, ifMatch: chapter.row_version, idempotencyKey: newIdempotencyKey(),
      });
    },
    onSuccess: result => { loadEditor(result.data); refreshChapters(); toast.notify("章节状态已更新，学习材料仍需单独发布"); },
    onError: (error: Error) => { notifyError(error); refreshChapters(); },
  });
  const resetUpload = () => { setMaterialName(""); setFile(null); setFileKey(key => key + 1); };
  const chooseFile = (selectedFile?: File) => {
    if (selectedFile && (selectedFile.size > 10 * 1024 * 1024 || !/\.(pdf|docx|pptx|xlsx|txt|md|csv|png|jpe?g)$/i.test(selectedFile.name))) {
      setFile(null); setFileKey(key => key + 1);
      toast.notify(selectedFile.size > 10 * 1024 * 1024 ? "附件不能超过 10 MB" : "请选择支持的文件类型", "error"); return;
    }
    setFile(selectedFile ?? null);
    if (selectedFile && !materialName.trim()) setMaterialName(selectedFile.name.replace(/\.[^.]+$/, "").slice(0, 180));
  };
  const upload = useMutation({
    mutationFn: () => {
      if (!materialChapter || !file) throw new Error("请选择章节和附件");
      const body = new FormData(); body.append("title", materialName.trim()); body.append("file", file);
      return request(`${base}/chapters/${materialChapter.public_id}/materials/upload`, { method: "POST", body, idempotencyKey: newIdempotencyKey() });
    },
    onSuccess: () => { resetUpload(); refreshMaterials(); toast.notify("附件扫描通过，材料草稿已保存"); }, onError: notifyError,
  });
  const materialStatus = useMutation({
    mutationFn: async ({ material, action }: { material: Material; action: "published" | "withdrawn" }) => {
      const versions = await request<MaterialVersion[]>(`${base}/materials/${material.public_id}/versions`);
      let version = (action === "published" ? versions.data.find(row => row.status === "DRAFT") : undefined)
        ?? versions.data.find(row => row.public_id === material.current_version_id) ?? versions.data[0];
      if (!version) throw new Error("材料版本不存在，请刷新");
      if (action === "published" && version.status === "WITHDRAWN") {
        const draft = await request<MaterialVersion>(`${base}/materials/${material.public_id}/versions`, {
          method: "POST", idempotencyKey: newIdempotencyKey(),
          body: { text_content: material.text_content || "", link_url: material.link_url || "", object_asset_id: material.object_asset_id || "" },
        });
        version = draft.data;
      }
      return request(`${base}/material-versions/${version.public_id}/${action}`, { method: "POST", body: {}, ifMatch: version.row_version, idempotencyKey: newIdempotencyKey() });
    },
    onSuccess: () => { refreshMaterials(); toast.notify("学习材料发布状态已更新，章节状态保持不变"); }, onError: notifyError,
  });
  const openFile = useMutation({
    mutationFn: (id: string) => fileApi.createDownloadGrant(id),
    onSuccess: grant => {
      if (grant.download_path.startsWith("/files/") && !grant.download_path.includes("\\")) window.location.assign(grant.download_path);
      else toast.notify("文件地址无效", "error");
    }, onError: notifyError,
  });
  const busy = save.isPending || chapterStatus.isPending || generate.isPending;
  const editorDisabled = busy || readOnly;
  const submitChapter = (event: FormEvent) => { event.preventDefault(); save.mutate(); };

  return <div className="course-content-modules">
    <Panel id="course-chapters-panel" className="course-content-module" title={<div className="content-module-title"><h2>课程章节</h2><span>{rows.length} 个章节</span></div>}
      actions={<Button disabled={busy || chapters.isPending || chapters.isError} onClick={() => { setEditing(null); setName(""); setContent(""); setAiDraft(null); requestAnimationFrame(() => nameInput.current?.focus()); }}><Icon name="plus" size={16} />新建章节</Button>}>
      <RequestStateView loading={chapters.isLoading} error={chapters.error} onRetry={refreshChapters} empty={false}>
        <div className="chapter-workspace">
          <nav aria-label="课程章节列表" className="chapter-list">
            {rows.map(row => <button type="button" key={row.public_id} disabled={busy} className={`chapter-list-item${editing?.public_id === row.public_id ? " active" : ""}`}
              aria-label={chapterTitle(row.position, row.title)} aria-current={editing?.public_id === row.public_id ? "true" : undefined} onClick={() => loadEditor(row)}>
              <span className="chapter-list-number">{row.position}</span><span><strong>{chapterTitle(row.position, row.title)}</strong><span className={`content-status${row.status === "PUBLISHED" ? " published" : ""}`}>{statusName(row.status)}</span></span>
            </button>)}
            {!rows.length && <EmptyState title="暂无章节" hint="填写名称与说明，创建第一章。" />}
          </nav>
          <form className="chapter-editor-form" aria-label="编辑课程章节" onSubmit={submitChapter}>
            <div className="content-form-field"><label htmlFor="chapter-name">章节名称</label><div className={`chapter-name-field${editorDisabled ? " disabled" : ""}`}>
              <span className="chapter-name-prefix" data-testid="chapter-prefix">{chapterLabel(position)}</span>
              <input ref={nameInput} id="chapter-name" value={name} disabled={editorDisabled} required maxLength={180 - chapterLabel(position).length - 1} onChange={event => setName(event.target.value)} placeholder="例如：云教学实验" />
            </div><p className="content-field-hint">章节序号自动生成，只需填写名称。</p></div>
            <div className="content-form-field"><label htmlFor="chapter-description">章节说明<span>介绍本章目标、准备事项与学习步骤</span></label>
              <textarea id="chapter-description" className="field" rows={6} value={content} disabled={editorDisabled} onChange={event => setContent(event.target.value)} placeholder="填写章节内容，也可以使用 AI 先生成草稿。" maxLength={100000} />
            </div>
            {readOnly && <p className="content-field-hint">该章节已发布。撤回后可修改，学习材料保持各自的发布状态。</p>}
            <footer className="chapter-editor-footer"><span className={`content-status${readOnly ? " published" : ""}`}>{editing ? statusName(editing.status) : "新章节"}</span><div className="actions">
              <Button disabled={editorDisabled || !chapterName(name)} onClick={() => generate.mutate()}>{generate.isPending ? "AI 正在生成…" : "AI 生成草稿"}</Button>
              <Button type="submit" disabled={editorDisabled || !chapterName(name)}>{save.isPending ? "保存中…" : "保存章节草稿"}</Button>
              <Button variant="primary" disabled={busy || (!readOnly && !chapterName(name))} onClick={() => chapterStatus.mutate()}>{chapterStatus.isPending ? "处理中…" : readOnly ? "撤回章节" : "发布章节"}</Button>
            </div></footer>
          </form>
        </div>
      </RequestStateView>
    </Panel>

    <Panel id="course-materials-panel" className="course-content-module" title={<div className="content-module-title"><h2>学习材料</h2><span>{materialRows.length} 份材料</span></div>}
      actions={<div className="material-chapter-scope"><label htmlFor="material-chapter">当前章节</label><select id="material-chapter" className="field" aria-label="学习材料所在章节" value={materialChapter?.public_id ?? ""} disabled={!rows.length || upload.isPending} onChange={event => { setMaterialChapterId(event.target.value); resetUpload(); }}>
        {!rows.length && <option value="">请先创建课程章节</option>}{rows.map(row => <option key={row.public_id} value={row.public_id}>{chapterTitle(row.position, row.title)}</option>)}
      </select></div>}>
      <RequestStateView loading={chapters.isLoading || materials.isLoading} error={chapters.error ?? materials.error} onRetry={() => { refreshChapters(); refreshMaterials(); }} empty={false}>
        <div className="learning-material-body"><form className="learning-material-upload" aria-label="添加学习材料" onSubmit={event => { event.preventDefault(); upload.mutate(); }}>
          <div className="content-form-field"><label htmlFor="material-name">材料名称</label><input id="material-name" className="field" value={materialName} required maxLength={180} disabled={!materialChapter || upload.isPending} onChange={event => setMaterialName(event.target.value)} placeholder="例如：环境配置指南" /></div>
          <div className="content-form-field"><label htmlFor="material-file">附件</label>
            <label className={`material-file-drop${dragging ? " dragging" : ""}${!materialChapter || upload.isPending ? " disabled" : ""}`}
              onDragOver={event => { event.preventDefault(); if (materialChapter && !upload.isPending) setDragging(true); }} onDragLeave={() => setDragging(false)}
              onDrop={event => { event.preventDefault(); setDragging(false); if (materialChapter && !upload.isPending) chooseFile(event.dataTransfer.files[0]); }}>
              <Icon name="paperclip" size={16} /><span>{file?.name ?? "选择文件或拖拽到此处"}</span>
              <input key={fileKey} id="material-file" type="file" aria-label="附件" accept=".pdf,.docx,.pptx,.xlsx,.txt,.md,.csv,.png,.jpg,.jpeg" disabled={!materialChapter || upload.isPending} onChange={event => chooseFile(event.target.files?.[0])} />
            </label><p className="content-field-hint">PDF、Word、PPT 等文件，单个不超过 10 MB</p>
          </div>
          <div className="material-upload-action"><Button type="submit" disabled={!materialChapter || !file || !materialName.trim() || upload.isPending}>{upload.isPending ? "上传并扫描中…" : "保存材料草稿"}</Button></div>
        </form>
        <div className="learning-material-table-wrap"><table className="learning-material-table"><thead><tr><th>材料名称</th><th className="number">文件大小</th><th>发布状态</th><th className="material-actions-heading">操作</th></tr></thead><tbody>
          {materialRows.map(row => <tr key={row.public_id}><td><div className="learning-material-name"><Icon name="file-text" size={18} /><div><strong>{row.title}</strong><small>{row.asset_name || (row.kind === "TEXT" ? "在线文本" : row.kind === "LINK" ? "外部链接" : "附件")}</small></div></div></td>
            <td className="number">{sizeLabel(row.size_bytes)}</td><td><span className={`content-status${row.version_status === "PUBLISHED" ? " published" : ""}`}>{statusName(row.version_status)}</span></td>
            <td><div className="learning-material-actions">
              {row.kind === "TEXT" ? <button className="material-text-action" type="button" onClick={() => setTextMaterial(row)}>查看</button> : row.kind === "LINK" && row.link_url ? <a className="material-text-action" href={row.link_url} target="_blank" rel="noreferrer">查看</a> : <button type="button" className="material-text-action" disabled={!row.object_asset_id || openFile.isPending} onClick={() => openFile.mutate(row.object_asset_id!)}>查看</button>}
              <button type="button" className="material-text-action" disabled={materialStatus.isPending || (row.version_status !== "PUBLISHED" && materialChapter?.status !== "PUBLISHED")}
                title={row.version_status !== "PUBLISHED" && materialChapter?.status !== "PUBLISHED" ? "请先发布对应章节" : undefined}
                aria-label={`${row.version_status === "PUBLISHED" ? "撤回材料" : "发布材料"} ${row.title}`} onClick={() => materialStatus.mutate({ material: row, action: row.version_status === "PUBLISHED" ? "withdrawn" : "published" })}>{row.version_status === "PUBLISHED" ? "撤回" : "发布材料"}</button>
            </div></td></tr>)}
        </tbody></table>{!materialRows.length && <p className="content-empty">{materialChapter ? "本章还没有学习材料，填写名称并上传第一个附件。" : "创建课程章节后，可在这里添加学习材料。"}</p>}</div></div>
        <footer className="learning-material-footer"><span>{materialRows.length} 份材料 · {publishedCount} 份已发布 · {materialRows.length - publishedCount} 份未发布</span><span>材料发布后，学生可在对应章节查看</span></footer>
      </RequestStateView>
    </Panel>

    <Modal open={aiDraft !== null} onClose={() => setAiDraft(null)} title="AI 章节草稿 · 教师评审" wide actions={<><Button onClick={() => setAiDraft(null)}>放弃草稿</Button><Button variant="primary" disabled={editorDisabled} onClick={() => { setContent(aiDraft ?? ""); setAiDraft(null); }}>采纳并替换章节说明</Button></>}>
      <p className="subtle">请审阅和修改生成内容，采纳后再保存章节草稿。</p><textarea aria-label="AI 章节草稿" className="field ai-chapter-draft" rows={12} value={aiDraft ?? ""} onChange={event => setAiDraft(event.target.value)} />
    </Modal>
    <Modal open={textMaterial !== null} onClose={() => setTextMaterial(null)} title={textMaterial?.title ?? "学习材料"} wide><p className="material-text-content">{textMaterial?.text_content}</p></Modal>
  </div>;
}
