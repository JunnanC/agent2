import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { studentApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Breadcrumbs, Button, EmptyState, Panel, RequestStateView, StatusBadge } from "@edu/ui";
import { formatDate } from "@/lib/task-format";

export function Courses() {
  const enrollments = useQuery({ queryKey: keys.enrollments({}), queryFn: () => studentApi.myEnrollments({ page_size: 100 }) });

  return (
    <>
      <Breadcrumbs items={[{ label: "学生门户" }]} current="我的课程" />
      <Panel>
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
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>课程</th><th>申请说明</th><th>申请时间</th><th>状态</th><th /></tr>
              </thead>
              <tbody>
                {(enrollments.data?.rows ?? []).map((enrollment) => (
                  <tr key={enrollment.public_id}>
                    <td style={{ minWidth: 180 }}>
                      <strong>{enrollment.course_title}</strong>
                      <small style={{ display: "block" }}>{enrollment.course_code}</small>
                    </td>
                    <td data-wrap style={{ maxWidth: 260 }}>{enrollment.application_message || "—"}</td>
                    <td>{formatDate(enrollment.applied_at)}</td>
                    <td>
                      <StatusBadge tone={enrollment.status === "ACTIVE" ? "good" : enrollment.status === "PENDING" ? "warn" : "neutral"}>
                        {enrollment.status === "ACTIVE" ? "已加入"
                          : enrollment.status === "PENDING" ? "审核中"
                            : enrollment.status === "REJECTED" ? "未通过"
                              : enrollment.status === "REMOVED" ? "已移出"
                                : enrollment.status === "DROPPED" ? "已退出"
                                  : "已结束"}
                      </StatusBadge>
                    </td>
                    <td className="table-actions">
                      {enrollment.status === "ACTIVE"
                        ? <Link className="btn sm primary" to={`/courses/${enrollment.course_id}`}>进入课程</Link>
                        : enrollment.status === "PENDING"
                          ? <Button size="sm" onClick={() => void enrollments.refetch()}>查看最新状态</Button>
                          : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </RequestStateView>
      </Panel>
    </>
  );
}
