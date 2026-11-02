import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { studentApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Breadcrumbs, Button, EmptyState, Panel, RequestStateView, StatusBadge } from "@edu/ui";
import { formatDate } from "@/lib/task-format";

function enrollmentStatus(status: string): { label: string; tone: "good" | "warn" | "blue" | "bad" | "neutral" } {
  if (status === "ACTIVE" || status === "APPROVED") return { label: "进行中", tone: "good" };
  if (status === "PENDING") return { label: "审核中", tone: "warn" };
  if (status === "REJECTED") return { label: "未通过", tone: "bad" };
  if (status === "DROPPED") return { label: "已退出", tone: "neutral" };
  if (status === "REMOVED") return { label: "已移出", tone: "neutral" };
  return { label: "已结束", tone: "neutral" };
}

export function Courses() {
  const enrollments = useQuery({ queryKey: keys.enrollments({}), queryFn: () => studentApi.myEnrollments({ page_size: 100 }) });

  return (
    <>
      <Breadcrumbs items={[{ label: "学生门户" }]} current="我的课程" />
      <Panel
        className="courses-browser"
        title={<><h2>我的课程</h2><span className="subtle">选择一门课程进入学习空间</span></>}
        actions={<Link className="btn primary" to="/courses/join">加入课程</Link>}
      >
        <RequestStateView
          loading={enrollments.isLoading}
          error={enrollments.error}
          onRetry={() => void enrollments.refetch()}
          empty={!enrollments.data?.rows.length}
          emptyState={(
            <EmptyState
              title="还没有加入课程"
              hint="在「加入课程」页面查看本学期开放课程并提交申请。"
              action={<Link className="btn primary" to="/courses/join">加入课程</Link>}
            />
          )}
        >
          <div className="course-card-grid">
            {(enrollments.data?.rows ?? []).map((enrollment) => {
              const status = enrollmentStatus(enrollment.status);
              const active = enrollment.status === "ACTIVE" || enrollment.status === "APPROVED";
              const content = (
                <>
                  <div className="course-card-head">
                    <span className="course-card-code">{enrollment.course_code || "课程"}</span>
                    <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
                  </div>
                  <div className="course-card-body">
                    <div className="course-card-emblem" aria-hidden="true">
                      {(enrollment.course_title || enrollment.course_code || "课").slice(0, 1)}
                    </div>
                    <h3>{enrollment.course_title || "未命名课程"}</h3>
                    <p>{enrollment.application_message || "欢迎进入课程学习空间，查看章节、实验任务和课程资料。"}</p>
                  </div>
                  <div className="course-card-footer">
                    <span>申请于 {formatDate(enrollment.applied_at)}</span>
                    <strong>{active ? "进入课程" : "查看状态"}<span aria-hidden="true"> →</span></strong>
                  </div>
                </>
              );

              return active ? (
                <Link className="course-card" key={enrollment.public_id} to={`/courses/${enrollment.course_id}`} aria-label={`进入课程 ${enrollment.course_title || enrollment.course_code || "未命名课程"}`}>
                  {content}
                </Link>
              ) : (
                <article className="course-card is-disabled" key={enrollment.public_id}>
                  {content}
                  {enrollment.status === "PENDING" ? <Button size="sm" onClick={() => void enrollments.refetch()}>查看最新状态</Button> : null}
                </article>
              );
            })}
          </div>
        </RequestStateView>
      </Panel>
    </>
  );
}
