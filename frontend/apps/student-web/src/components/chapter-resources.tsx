import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { studentApi, taskApi, fileApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, EmptyState, Panel, RequestStateView, useToast } from "@edu/ui";

export function ChapterResources({ courseId, chapterId }: { courseId: string; chapterId: string }) {
  const toast = useToast();
  const materials = useQuery({ queryKey: keys.courseResource(courseId, "materials"), queryFn: () => studentApi.courseMaterials(courseId) });
  const tasks = useQuery({ queryKey: [...keys.tasks({ course_id: courseId }), "all-pages"], queryFn: async () => {
    const first = await taskApi.list({ course_id: courseId, page_size: 100 });
    const rows = [...first.rows];
    for (let page = 2; rows.length < first.total; page++) {
      const next = await taskApi.list({ course_id: courseId, page_size: 100, page });
      if (!next.rows.length) break;
      rows.push(...next.rows);
    }
    return { ...first, rows };
  } });
  const open = useMutation({
    mutationFn: (id: string) => fileApi.createDownloadGrant(id),
    onSuccess: grant => { if (grant.download_path.startsWith("/files/") && !grant.download_path.includes("\\")) window.location.assign(grant.download_path); else toast.notify("文件地址无效", "error"); },
    onError: (error: Error) => toast.notify(error.message, "error"),
  });
  const files = materials.data?.rows.filter(row => row.chapter_id === chapterId) ?? [];
  const experiments = tasks.data?.rows.filter(row => row.course_chapter_id === chapterId) ?? [];
  return <>
    <Panel title={<h2>学习材料</h2>}>
      <RequestStateView loading={materials.isLoading} error={materials.error} onRetry={() => void materials.refetch()} empty={!files.length} emptyState={<EmptyState title="本章暂无已发布材料" />}>
        {files.map(material => <div className="item" key={material.public_id}>
          {material.kind === "LINK" && material.link_url ? <a href={material.link_url} target="_blank" rel="noreferrer">{material.title}</a> : material.kind === "TEXT" ? <details><summary>{material.title}</summary><p className="course-chapter-description">{material.text_content}</p></details> : <Button disabled={!material.object_asset_id || open.isPending} onClick={() => open.mutate(material.object_asset_id!)}>{material.title}</Button>}
        </div>)}
      </RequestStateView>
    </Panel>
    <Panel title={<h2>本章实验</h2>}>
      <RequestStateView loading={tasks.isLoading} error={tasks.error} onRetry={() => void tasks.refetch()} empty={!experiments.length} emptyState={<EmptyState title="本章暂无分配给你的实验" />}>
        {experiments.map(task => <div className="item" key={task.public_id}><Link to={`/experiments/${task.public_id}`}>{task.title}</Link><Link className="btn" to={`/experiments/${task.public_id}${task.assessment_available ? "/assessment" : ""}`}>{task.assessment_available ? "进入实验答题" : "查看实验"}</Link></div>)}
      </RequestStateView>
    </Panel>
  </>;
}
