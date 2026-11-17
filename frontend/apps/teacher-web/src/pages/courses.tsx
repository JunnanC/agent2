import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { useState } from "react";
import { teachingApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, Modal, Breadcrumbs, Panel, RequestStateView, useToast } from "@edu/ui";
import { CourseInvitation } from "@/components/course-invitation";
import { apiErrorMessage } from "@/lib/format";

export function Courses() {
  const toast = useToast();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [visibility, setVisibility] = useState<"PUBLIC" | "UNLISTED">("UNLISTED");

  const courses = useQuery({ queryKey: keys.teachingCourses({}), queryFn: () => teachingApi.courses({ page_size: 50 }) });

  const create = useMutation({
    mutationFn: () => teachingApi.createCourse({ title: title.trim(), summary: summary.trim(), visibility, enrollment_mode: "APPROVAL" }),
    onSuccess: (course) => {
      toast.notify(`课程「${course.title}」已创建`);
      setCreateOpen(false);
      setTitle(""); setSummary("");
      void courses.refetch();
      navigate(`/courses/${course.public_id}`);
    },
    onError: (error) => toast.notify(apiErrorMessage(error), "error"),
  });

  return (
    <>
      <Breadcrumbs items={[]} current="我的课程" />
      <div className="page-actions align-end">
        <Button variant="primary" onClick={() => setCreateOpen(true)}>新建课程</Button>
      </div>
      <Panel>
        <RequestStateView
          loading={courses.isLoading}
          error={courses.error}
          onRetry={() => void courses.refetch()}
          empty={!courses.data?.rows.length}
          emptyState={(
            <div className="state-block">
              <strong>还没有课程</strong>
              <p>创建课程后，再邀请学生并配置实验。</p>
              <Button variant="primary" onClick={() => setCreateOpen(true)}>新建课程</Button>
            </div>
          )}
        >
          <div className="page-actions"><input className="field" aria-label="搜索课程" placeholder="搜索课程" value={search} onChange={e => setSearch(e.target.value)} /></div>
          <div className="teacher-courses">{(courses.data?.rows ?? []).filter(course => `${course.title} ${course.code}`.includes(search.trim())).map(course => <article className="teacher-course" key={course.public_id}><small>{course.code} · {course.status === "ACTIVE" ? "进行中" : course.status}</small><h2>{course.title}</h2><p className="subtle">{course.summary || "管理课程实验、学生与教学数据"}</p><p>{course.active_enrollment_count} 名学生 · 教师邀请 / 邀请码审核</p><CourseInvitation courseId={course.public_id} /><footer><Link to={`/courses/${course.public_id}/analytics`}>教学分析</Link><Link className="btn primary" to={`/courses/${course.public_id}`}>进入课程</Link></footer></article>)}</div>
        </RequestStateView>
      </Panel>

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} eyebrow="课程"
        title="新建课程"
        actions={(
          <>
            <Button onClick={() => setCreateOpen(false)}>取消</Button>
            <Button variant="primary" disabled={!title.trim() || create.isPending} onClick={() => create.mutate()}>
              {create.isPending ? "创建中…" : "创建课程"}
            </Button>
          </>
        )}>
        <label className="form-label" htmlFor="c-title">课程名称 <span>必填</span></label>
        <input id="c-title" className="field" value={title} onChange={(event) => setTitle(event.target.value)} />
        <p className="subtle">课程代码在创建后自动生成。</p>
        <label className="form-label" htmlFor="c-summary">课程简介 <span>选填</span></label>
        <textarea id="c-summary" className="field" rows={3} value={summary} onChange={(event) => setSummary(event.target.value)} />
        <label className="form-label" htmlFor="c-visibility">课程可见性</label>
        <select id="c-visibility" className="field" value={visibility} onChange={(event) => setVisibility(event.target.value as typeof visibility)}>
          <option value="UNLISTED">不公开展示</option><option value="PUBLIC">公开展示</option>
        </select>
        <p className="subtle">教师邀请直接加入；学生使用邀请码申请，需教师审核。</p>
      </Modal>
    </>
  );
}
