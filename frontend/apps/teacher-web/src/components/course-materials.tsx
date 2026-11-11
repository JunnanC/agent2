import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { teachingApi } from "@edu/api-client";
import { newIdempotencyKey, request } from "@edu/auth-client";
import { Button, EmptyState, Panel, RequestStateView, useToast } from "@edu/ui";
import { keys } from "@edu/query-keys";

type Chapter = { public_id: string; title: string; status: string; row_version: number };
type Material = { public_id: string; title: string; current_version_id: string; version_status: string };

export function CourseMaterials({ courseId }: { courseId: string }) {
  const base = `/teaching/courses/${courseId}`;
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [chapterId, setChapterId] = useState("");
  const [chapterTitle, setChapterTitle] = useState("");
  const [kind, setKind] = useState("TEXT");
  const [content, setContent] = useState("");
  const [templateId, setTemplateId] = useState("");
  const chapters = useQuery({ queryKey: keys.courseResource(courseId, "chapters"), queryFn: () => teachingApi.courseResource<Chapter>(courseId, "chapters") });
  const materials = useQuery({ queryKey: keys.courseResource(courseId, "materials"), queryFn: () => teachingApi.courseResource<Material>(courseId, "materials") });
  const templates = useQuery({ queryKey: keys.templates(courseId), queryFn: () => teachingApi.templates(courseId), enabled: kind === "FILE" });
  const template = templates.data?.rows.find((row) => row.public_id === templateId);
  const assets = useQuery({ queryKey: ["course-material-assets", courseId, templateId, template?.current_version_id], queryFn: () => teachingApi.templateAssets(courseId, templateId, template?.current_version_id ?? ""), enabled: kind === "FILE" && Boolean(template?.current_version_id) });
  const addChapter = useMutation({
    mutationFn: async () => {
      const chapter = (await request<Chapter>(`${base}/chapters`, { method: "POST", body: { title: chapterTitle.trim(), position: Math.max(0, ...(chapters.data?.rows ?? []).map((row) => Number((row as Chapter & { position?: number }).position ?? 0))) + 1 }, idempotencyKey: newIdempotencyKey() })).data;
      return request<Chapter>(`${base}/chapters/${chapter.public_id}/published`, { method: "POST", body: {}, ifMatch: chapter.row_version, idempotencyKey: newIdempotencyKey() });
    },
    onSuccess: (result) => { setChapterId(result.data.public_id); setChapterTitle(""); void chapters.refetch(); toast.notify("章节已创建并发布"); },
    onError: (error) => { void chapters.refetch(); toast.notify(error.message, "error"); },
  });
  const publish = useMutation({
    mutationFn: async (material: Material) => {
      const versions = (await request<Array<{ public_id: string; row_version: number }>>(`${base}/materials/${material.public_id}/versions`)).data;
      const version = versions.find((row) => row.public_id === material.current_version_id);
      if (!version) throw new Error("未找到材料版本，请刷新后重试");
      await request(`${base}/material-versions/${version.public_id}/published`, { method: "POST", body: {}, ifMatch: version.row_version, idempotencyKey: newIdempotencyKey() });
    },
    onSuccess: () => { void materials.refetch(); toast.notify("材料已发布，学生可在课程介绍查看"); },
    onError: (error) => toast.notify(error.message, "error"),
  });
  const create = useMutation({
    mutationFn: () => request<Material>(`${base}/materials`, { method: "POST", idempotencyKey: newIdempotencyKey(), body: { title: title.trim(), chapter_id: chapterId, kind, ...(kind === "TEXT" ? { text_content: content } : kind === "LINK" ? { link_url: content } : { object_asset_id: content }) } }),
    onSuccess: () => { setTitle(""); setContent(""); void materials.refetch(); toast.notify("材料草稿已保存，请在下方发布"); },
    onError: (error) => toast.notify(error.message, "error"),
  });
  return <Panel className="section" title={<h2>课程材料</h2>}>
    <p className="subtle">发布的材料供本课程学生查看。附件可选用实验设计中已上传且扫描通过的指导书、报告模板等文件。</p>
    <RequestStateView loading={chapters.isLoading || materials.isLoading} error={chapters.error ?? materials.error} onRetry={() => { void chapters.refetch(); void materials.refetch(); }} empty={false}>
      <label className="form-label">新章节名称<input className="field" value={chapterTitle} onChange={(event) => setChapterTitle(event.target.value)} /></label><Button disabled={!chapterTitle.trim() || addChapter.isPending} onClick={() => addChapter.mutate()}>创建并发布章节</Button>
      <form className="section" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
        <label className="form-label">所属章节<select className="field" value={chapterId} onChange={(event) => setChapterId(event.target.value)}><option value="">选择已发布章节</option>{chapters.data?.rows.filter((row) => row.status === "PUBLISHED").map((row) => <option key={row.public_id} value={row.public_id}>{row.title}</option>)}</select></label>
        <label className="form-label">材料标题<input className="field" value={title} onChange={(event) => setTitle(event.target.value)} /></label>
        <label className="form-label">材料类型<select className="field" value={kind} onChange={(event) => { setKind(event.target.value); setContent(""); }}><option value="TEXT">在线文本</option><option value="LINK">外部链接</option><option value="FILE">已上传附件</option></select></label>
        {kind === "FILE" ? <RequestStateView loading={templates.isLoading || assets.isLoading} error={templates.error ?? assets.error} onRetry={() => { void templates.refetch(); void assets.refetch(); }} empty={false}>
          <label className="form-label">附件所在实验<select className="field" value={templateId} onChange={(event) => { setTemplateId(event.target.value); setContent(""); }}><option value="">选择实验</option>{templates.data?.rows.map((row) => <option key={row.public_id} value={row.public_id}>{row.name}</option>)}</select></label>
          <label className="form-label">扫描通过的附件<select className="field" value={content} onChange={(event) => setContent(event.target.value)}><option value="">选择附件</option>{(assets.data?.rows ?? []).filter((row) => row["scan_status"] === "CLEAN" && ["MANUAL", "REPORT_TEMPLATE"].includes(String(row["purpose"]))).map((row) => <option key={String(row["public_id"])} value={String(row["public_id"])}>{String(row["file_name"] ?? row["public_id"])}</option>)}</select></label>
        </RequestStateView> : <label className="form-label">{kind === "LINK" ? "链接地址" : "材料正文"}<textarea className="field" value={content} onChange={(event) => setContent(event.target.value)} /></label>}
        <Button type="submit" disabled={!chapterId || !title.trim() || !content.trim() || create.isPending}>保存材料草稿</Button>
      </form>
      {materials.data?.rows.map((row) => <div className="item" key={row.public_id}><strong>{row.title}</strong><span>{row.version_status === "PUBLISHED" ? "已发布" : <Button disabled={publish.isPending} onClick={() => publish.mutate(row)}>发布材料 {row.title}</Button>}</span></div>)}
      {!materials.data?.rows.length && <EmptyState title="暂无课程材料" />}
    </RequestStateView>
  </Panel>;
}
