import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { useState } from "react";
import { teachingApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, Modal, Breadcrumbs, Panel, RequestStateView, StatusBadge, useToast } from "@edu/ui";
import { apiErrorMessage } from "@/lib/format";

export function Courses() {
  const toast = useToast();
  const navigate = useNavigate();
  const [createOpen, setCreateOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [code, setCode] = useState("");
  const [summary, setSummary] = useState("");

  const courses = useQuery({ queryKey: keys.teachingCourses({}), queryFn: () => teachingApi.courses({ page_size: 50 }) });

  const create = useMutation({
    mutationFn: () => teachingApi.createCourse({ title: title.trim(), code: code.trim(), summary: summary.trim() }),
    onSuccess: (course) => {
      toast.notify(`课程「${course.title}」已创建`);
      setCreateOpen(false);
      setTitle(""); setCode(""); setSummary("");
      void courses.refetch();
      navigate(`/courses/${course.public_id}/enrollments`);
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
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>课程</th><th>选课方式</th><th>学生</th><th>状态</th><th /></tr>
              </thead>
              <tbody>
                {(courses.data?.rows ?? []).map((course) => (
                  <tr key={course.public_id}>
                    <td><strong>{course.title}</strong><small style={{ display: "block" }}>{course.code} · {course.owner_name ?? ""}</small></td>
                    <td>{course.enrollment_mode === "OPEN" ? "直接加入" : "需要审核"}</td>
                    <td>{course.active_enrollment_count}{course.capacity ? ` / ${course.capacity}` : ""}</td>
                    <td><StatusBadge tone={course.status === "ACTIVE" ? "good" : course.status === "FROZEN" ? "bad" : "neutral"}>{course.status === "ACTIVE" ? "进行中" : course.status}</StatusBadge></td>
                    <td className="table-actions">
                      <Link className="btn sm" to={`/courses/${course.public_id}/enrollments`}>选课管理</Link>
                      <Link className="btn sm" to={`/courses/${course.public_id}/templates`}>实验设计</Link>
                      <Link className="btn sm" to={`/courses/${course.public_id}/publishing`}>实验发布</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </RequestStateView>
      </Panel>

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} eyebrow="课程"
        title="新建课程"
        actions={(
          <>
            <Button onClick={() => setCreateOpen(false)}>取消</Button>
            <Button variant="primary" disabled={!title.trim() || !code.trim() || create.isPending} onClick={() => create.mutate()}>
              {create.isPending ? "创建中…" : "创建课程"}
            </Button>
          </>
        )}>
        <label className="form-label" htmlFor="c-title">课程名称 <span>必填</span></label>
        <input id="c-title" className="field" value={title} onChange={(event) => setTitle(event.target.value)} />
        <label className="form-label" htmlFor="c-code">课程代码 <span>必填</span></label>
        <input id="c-code" className="field" value={code} onChange={(event) => setCode(event.target.value)} placeholder="如 CS-NET-2026" />
        <label className="form-label" htmlFor="c-summary">课程简介 <span>选填</span></label>
        <textarea id="c-summary" className="field" rows={3} value={summary} onChange={(event) => setSummary(event.target.value)} />
      </Modal>
    </>
  );
}
