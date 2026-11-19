import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { studentApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Breadcrumbs, Button, EmptyState, Panel, RequestStateView, StatusBadge } from "@edu/ui";
import { formatDate } from "@/lib/task-format";
import { StudentTimetable } from "@/components/student-timetable";
import { LearningHistory } from "@/components/learning-history";
import { EnrollmentExit } from "@/components/enrollment-exit";

function enrollmentStatus(status: string): { label: string; tone: "good" | "warn" | "blue" | "bad" | "neutral" } {
  if (status === "ACTIVE" || status === "APPROVED") return { label: "进行中", tone: "good" };
  if (status === "PENDING") return { label: "审核中", tone: "warn" };
  if (status === "REJECTED") return { label: "未通过", tone: "bad" };
  if (status === "DROPPED") return { label: "已退出", tone: "neutral" };
  if (status === "REMOVED") return { label: "已移出", tone: "neutral" };
  return { label: "已结束", tone: "neutral" };
}

export function Courses() {
  const [timetableUploadContainer, setTimetableUploadContainer] = useState<HTMLDivElement | null>(null);
  const enrollments = useQuery({ queryKey: keys.enrollments({ status: "ACTIVE" }), queryFn: () => studentApi.myEnrollments({ page_size: 100, status: "ACTIVE" }) });
  const applications = useQuery({ queryKey: keys.enrollments({ status: "PENDING" }), queryFn: () => studentApi.myEnrollments({ page_size: 100, status: "PENDING" }) });

  return (
    <>
      <Breadcrumbs items={[{ label: "学生门户" }]} current="我的课程" />
      <header className="student-overview-heading student-courses-heading">
        <div><h1>我的课程</h1><p>选择一门课程，进入学习空间</p></div>
        <Link className="btn primary" to="/courses/join">加入课程</Link>
        <div className="student-timetable-upload-slot" ref={setTimetableUploadContainer} />
      </header>
      <Panel className="courses-browser">
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
                    <h3>{enrollment.course_title || "未命名课程"}</h3>
                    <p>{enrollment.application_message || "查看章节、实验任务与课程资料"}</p>
                  </div>
                  <div className="course-card-footer">
                    <span>申请于 {formatDate(enrollment.applied_at)}</span>
                    <strong>{active ? "进入课程" : "查看状态"}<span aria-hidden="true"> →</span></strong>
                  </div>
                </>
              );

              return <div className="student-course-entry" key={enrollment.public_id}>
                {active ? <Link className="course-card" to={`/courses/${enrollment.course_id}`} aria-label={`进入课程 ${enrollment.course_title || enrollment.course_code || "未命名课程"}`}>{content}</Link> :
                  <article className="course-card is-disabled">{content}
                    {enrollment.status === "PENDING" ? <Button size="sm" onClick={() => void enrollments.refetch()}>查看最新状态</Button> : null}
                  </article>}
                <div className="page-actions course-exit-actions"><EnrollmentExit enrollment={enrollment} /></div>
              </div>;
            })}
          </div>
        </RequestStateView>
      </Panel>
      <Panel className="section" title={<h2>申请中的课程</h2>}>
        <RequestStateView loading={applications.isLoading} error={applications.error}
          onRetry={() => void applications.refetch()} empty={!applications.data?.rows.length}
          emptyState={<EmptyState title="暂无待审核申请" hint="提交课程申请后，可在这里查看进度或撤回。" />}>
          {(applications.data?.rows ?? []).filter((enrollment) => enrollment.status === "PENDING").map((enrollment) => (
            <div className="item" key={enrollment.public_id}>
              <div><strong>{enrollment.course_title || enrollment.course_code}</strong>
                <small>申请于 {formatDate(enrollment.applied_at)} · 教师同意后才能进入课程</small></div>
              <div className="page-actions"><StatusBadge tone="warn">审核中</StatusBadge><EnrollmentExit enrollment={enrollment} /></div>
            </div>
          ))}
        </RequestStateView>
      </Panel>
      <StudentTimetable uploadContainer={timetableUploadContainer} />
      <LearningHistory />
    </>
  );
}
