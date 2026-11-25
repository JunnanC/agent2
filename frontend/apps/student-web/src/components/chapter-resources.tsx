import { AssetActions } from "./asset-actions";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { studentApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { EmptyState, Panel, RequestStateView, isSafeUrl } from "@edu/ui";
import { listStudentTasks } from "@/lib/student-tasks";

export function ChapterResources({ courseId, chapterId }: { courseId: string; chapterId: string }) {
  const materials = useQuery({ queryKey: keys.courseResource(courseId, "materials"), queryFn: () => studentApi.courseMaterials(courseId) });
  const tasks = useQuery({ queryKey: keys.tasks({ course_id: courseId }), queryFn: () => listStudentTasks({ course_id: courseId }) });
  const files = materials.data?.rows.filter(row => row.chapter_id === chapterId) ?? [];
  const experiments = tasks.data?.rows.filter(row => row.course_chapter_id === chapterId) ?? [];
  return <>
    <Panel title={<h2>学习材料</h2>}>
      <RequestStateView loading={materials.isLoading} error={materials.error} onRetry={() => void materials.refetch()} empty={!files.length} emptyState={<EmptyState title="本章暂无已发布材料" />}>
        {files.map(material => <div className="item" key={material.public_id}>
          {material.kind === "LINK" ? (isSafeUrl(material.link_url) ? <a href={material.link_url} target="_blank" rel="noreferrer">{material.title}</a> : <span>{material.title}</span>) : material.kind === "TEXT" ? <details><summary>{material.title}</summary><p className="course-chapter-description">{material.text_content}</p></details> : <><span>{material.title}</span>{material.object_asset_id && <AssetActions assetId={material.object_asset_id} title={material.title} />}</>}
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
