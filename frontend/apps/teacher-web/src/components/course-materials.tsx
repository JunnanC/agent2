import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { request, newIdempotencyKey } from "@edu/auth-client";
import { teachingApi } from "@edu/api-client";
import type { Material } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, EmptyState, Panel, RequestStateView, useToast } from "@edu/ui";

type Chapter = { public_id: string; title: string; summary?: string; content?: string; status: string; position: number; row_version: number };

export function CourseMaterials({ courseId }: { courseId: string }) {
  const toast = useToast();
  const base = `/teaching/courses/${courseId}`;
  const [selectedId, setSelectedId] = useState("");
  const [editing, setEditing] = useState<Chapter | null>(null);
  const [chapterTitle, setChapterTitle] = useState("");
  const [content, setContent] = useState("");
  const [aiDraft, setAiDraft] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileKey, setFileKey] = useState(0);
  const chapters = useQuery({ queryKey: keys.courseResource(courseId, "chapters"), queryFn: () => teachingApi.courseResource<Chapter>(courseId, "chapters") });
  const materials = useQuery({ queryKey: keys.courseResource(courseId, "materials"), queryFn: () => teachingApi.courseResource<Material>(courseId, "materials") });
  const rows = chapters.data?.rows ?? [];
  const selected = rows.find(row => row.public_id === selectedId);
  const notifyError = (error: Error) => toast.notify(error.message, "error");
  const refresh = () => { void chapters.refetch(); void materials.refetch(); };
  const save = useMutation({
    mutationFn: () => request<Chapter>(editing ? `${base}/chapters/${editing.public_id}` : `${base}/chapters`, {
      method: editing ? "PATCH" : "POST", ifMatch: editing?.row_version, idempotencyKey: newIdempotencyKey(),
      body: { title: chapterTitle.trim(), content, summary: content.slice(0, 500), ...(editing ? {} : { position: Math.max(0, ...rows.map(row => row.position)) + 1 }) },
    }),
    onSuccess: result => { setEditing(result.data); setSelectedId(result.data.public_id); refresh(); toast.notify("章节草稿已保存，评审后可单独发布"); }, onError: notifyError,
  });
  const generate = useMutation({
    mutationFn: () => request<{ content: string }>(`${base}/chapter-drafts/generate`, { method: "POST", body: { title: chapterTitle.trim() }, idempotencyKey: newIdempotencyKey() }),
    onSuccess: result => setAiDraft(result.data.content), onError: notifyError,
  });
  const status = useMutation({
    mutationFn: ({ chapter, action }: { chapter: Chapter; action: string }) => request(`${base}/chapters/${chapter.public_id}/${action}`, { method: "POST", body: {}, ifMatch: chapter.row_version, idempotencyKey: newIdempotencyKey() }),
    onSuccess: () => { setEditing(null); setChapterTitle(""); setContent(""); refresh(); toast.notify("章节状态已更新，材料需单独发布"); }, onError: notifyError,
  });
  const upload = useMutation({
    mutationFn: () => {
      const body = new FormData(); body.append("title", title.trim()); body.append("file", file!);
      return request(`${base}/chapters/${selectedId}/materials/upload`, { method: "POST", body, idempotencyKey: newIdempotencyKey() });
    },
    onSuccess: () => { setTitle(""); setFile(null); setFileKey(key => key + 1); refresh(); toast.notify("附件扫描通过，材料草稿已保存"); }, onError: notifyError,
  });
  const publish = useMutation({
    mutationFn: async (material: Material) => {
      const versions = await request<Array<{ public_id: string; row_version: number }>>(`${base}/materials/${material.public_id}/versions`);
      const version = versions.data.find(row => row.public_id === material.current_version_id) ?? versions.data[0];
      if (!version) throw new Error("材料版本不存在，请刷新");
      return request(`${base}/material-versions/${version.public_id}/published`, { method: "POST", body: {}, ifMatch: version.row_version, idempotencyKey: newIdempotencyKey() });
    }, onSuccess: () => { refresh(); toast.notify("材料已发布，学生可在对应章节查看"); }, onError: notifyError,
  });
  const readOnly = editing?.status === "PUBLISHED";
  return <Panel className="section" title={<h2>课程章节</h2>}>
    <p className="subtle">先编写章节说明，再在章节中添加学习材料和实验。章节与材料分别发布。</p>
    <RequestStateView loading={chapters.isLoading || materials.isLoading} error={chapters.error ?? materials.error} onRetry={refresh} empty={false}>
      <div className="chapter-authoring">
        <nav aria-label="管理课程章节" className="chapter-authoring-nav">
          <Button onClick={() => { setEditing(null); setChapterTitle(""); setContent(""); setAiDraft(null); }}>新建章节</Button>
          {rows.map(row => <div className="section" key={row.public_id}>
            <Button variant={selectedId === row.public_id ? "primary" : "default"} onClick={() => { setSelectedId(row.public_id); setEditing(row); setChapterTitle(row.title); setContent(row.content || row.summary || ""); setAiDraft(null); }}>{row.title}</Button>
            <p className="subtle">{row.status === "PUBLISHED" ? "已发布" : row.status === "WITHDRAWN" ? "已撤回" : "草稿"}</p>
            <Button disabled={status.isPending} onClick={() => status.mutate({ chapter: row, action: row.status === "PUBLISHED" ? "withdrawn" : "published" })}>{row.status === "PUBLISHED" ? "撤回章节" : "发布章节"}</Button>
          </div>)}
          {!rows.length && <EmptyState title="暂无章节" hint="填写标题与说明，保存第一章。" />}
        </nav>
        <div>
          <form onSubmit={event => { event.preventDefault(); save.mutate(); }}>
            <label className="form-label">章节名称<input className="field" value={chapterTitle} disabled={readOnly || save.isPending} onChange={event => setChapterTitle(event.target.value)} placeholder="第一章 环境准备与平台导览" maxLength={180} /></label>
            <label className="form-label">章节说明<textarea className="field" rows={10} value={content} disabled={readOnly || save.isPending} onChange={event => setContent(event.target.value)} placeholder="介绍本章目标、准备事项与学习步骤，也可用 AI 先生成草稿。" maxLength={100000} /></label>
            {readOnly && <p className="subtle">已发布内容需先撤回章节，再编辑并重新发布。</p>}
            <div className="page-actions">
              <Button type="submit" disabled={readOnly || !chapterTitle.trim() || save.isPending}>{save.isPending ? "保存中…" : "保存章节草稿"}</Button>
              <Button disabled={readOnly || !chapterTitle.trim() || generate.isPending} onClick={() => generate.mutate()}>{generate.isPending ? "AI 正在生成…" : "AI 生成章节内容"}</Button>
            </div>
          </form>
          {aiDraft !== null && <Panel title={<h3>AI 草稿 · 等待教师评审</h3>}>
            <textarea aria-label="AI 章节草稿" className="field" rows={12} value={aiDraft} onChange={event => setAiDraft(event.target.value)} />
            <Button disabled={readOnly} onClick={() => { setContent(aiDraft); setAiDraft(null); }}>采纳草稿并替换章节说明</Button>
            <Button onClick={() => setAiDraft(null)}>放弃草稿</Button>
          </Panel>}
        </div>
      </div>
      {selected ? <section className="section">
        <h3>{selected.title} · 学习材料</h3>
        <form onSubmit={event => { event.preventDefault(); upload.mutate(); }}>
          <label className="form-label">材料名称<input className="field" value={title} maxLength={180} disabled={upload.isPending} onChange={event => setTitle(event.target.value)} /></label>
          <label className="form-label">附件<input key={fileKey} className="field" type="file" accept=".pdf,.docx,.pptx,.xlsx,.txt,.md,.csv,.png,.jpg,.jpeg" disabled={upload.isPending} onChange={event => setFile(event.target.files?.[0] ?? null)} /></label>
          <p className="subtle">最大 10 MB。上传并扫描通过后保存为草稿。</p>
          <Button type="submit" disabled={!file || !title.trim() || upload.isPending}>{upload.isPending ? "正在上传并扫描…" : "保存材料草稿"}</Button>
        </form>
        {(materials.data?.rows ?? []).filter(row => row.chapter_id === selectedId).map(row => <div className="item" key={row.public_id}><strong>{row.title}</strong>{row.version_status === "PUBLISHED" ? <span>已发布</span> : <Button disabled={publish.isPending || selected.status !== "PUBLISHED"} onClick={() => publish.mutate(row)}>发布材料 {row.title}</Button>}</div>)}
        {selected.status !== "PUBLISHED" && <p className="subtle">先发布章节，再单独发布其中的材料。</p>}
      </section> : <p className="subtle">选择或保存章节后，可在该章节添加材料。</p>}
    </RequestStateView>
  </Panel>;
}
