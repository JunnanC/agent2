import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { studentApi } from "@edu/api-client";
import { ApiError } from "@edu/auth-client";
import { keys } from "@edu/query-keys";
import { useToast } from "@edu/ui";
import { Breadcrumbs, Button, EmptyState, FilterBar, Modal, Panel,  RequestStateView } from "@edu/ui";
import { formatDate } from "@/lib/task-format";
import { EnrollmentExit } from "@/components/enrollment-exit";

export function JoinCourses() {
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"discover" | "enrollments">("discover");
  const [search, setSearch] = useState("");
  const [applyTarget, setApplyTarget] = useState<{ courseId: string; title: string } | null>(null);
  const [invitationCode, setInvitationCode] = useState("");
  const [applicationMessage, setApplicationMessage] = useState("");
  const [invitationSearch, setInvitationSearch] = useState("");

  const catalog = useQuery({ queryKey: keys.courses({}), queryFn: () => studentApi.courses({ page_size: 100 }) });
  const enrollments = useQuery({ queryKey: keys.enrollments({}), queryFn: () => studentApi.myEnrollments({ page_size: 100 }) });

  const joinMutation = useMutation({
    mutationFn: (input: { courseId: string; payload: { invitation_code?: string; application_message?: string } }) =>
      studentApi.joinCourse(input.courseId, input.payload),
    onSuccess: (enrollment) => {
      toast.notify(enrollment.status === "ACTIVE" ? "已加入课程" : "申请已提交，等待教师审核");
      void catalog.refetch();
      void enrollments.refetch();
      setApplyTarget(null);
      setInvitationCode("");
      setApplicationMessage("");
      void queryClient.invalidateQueries({ queryKey: keys.enrollments() });
      void queryClient.invalidateQueries({ queryKey: ["student"] });
      void queryClient.invalidateQueries({ queryKey: keys.context() });
      if (enrollment.status === "ACTIVE") navigate(`/courses/${enrollment.course_id}`);
    },
    onError: (error) => {
      const apiError = error instanceof ApiError ? error : null;
      const message = apiError?.payload?.code === "VALIDATION_ERROR"
        ? "表单校验失败，请检查填写内容。"
        : apiError?.payload?.code === "IDEMPOTENCY_KEY_REUSED"
          ? "该申请正在提交中，请勿重复点击。"
          : apiError?.payload?.message ?? "提交失败，请稍后重试。";
      toast.notify(message, "error");
    },
  });

  const resolveInvitation = useMutation({
    mutationFn: (code: string) => studentApi.resolveInvitation(code),
    onSuccess: (course, code) => {
      joinMutation.mutate({ courseId: course.public_id, payload: { invitation_code: code } });
    },
    onError: (error) => toast.notify(error instanceof ApiError ? error.payload?.message ?? "邀请码无效或已失效" : "邀请码无效或已失效", "error"),
  });

  const joinedCourseIds = useMemo(() => {
    const map = new Map<string, string>();
    for (const row of enrollments.data?.rows ?? []) {
      if (["ACTIVE", "PENDING"].includes(row.status)) map.set(row.course_id, row.status);
    }
    return map;
  }, [enrollments.data]);

  const enrollmentByCourseId = useMemo(() => new Map(
    (enrollments.data?.rows ?? []).filter((enrollment) => ["PENDING", "ACTIVE"].includes(enrollment.status))
      .map((enrollment) => [enrollment.course_id, enrollment]),
  ), [enrollments.data]);

  const courses = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (catalog.data?.rows ?? [])
      .filter((course) => tab === "discover"
        ? !joinedCourseIds.has(course.public_id)
        : joinedCourseIds.get(course.public_id) === "PENDING")
      .filter((course) => !query || `${course.title} ${course.code} ${course.summary ?? ""}`.toLowerCase().includes(query));
  }, [catalog.data, tab, search, joinedCourseIds]);

  const statusWording = (courseId: string) => {
    const status = joinedCourseIds.get(courseId);
    if (status === "ACTIVE") return { label: "已加入", tone: "good" as const };
    if (status === "PENDING") return { label: "审核中", tone: "warn" as const };
    return { label: "", tone: "neutral" as const };
  };

  return (
    <>
      <Breadcrumbs items={[{ label: "学生门户" }]} current="加入课程" />
      

      <div className="join-course-tabs" role="tablist" aria-label="课程列表">
        <button type="button" role="tab" aria-selected={tab === "discover"}
          className={`join-course-tab${tab === "discover" ? " active" : ""}`} onClick={() => setTab("discover")}>
          发现课程 <span>{courses.length}</span>
        </button>
        <button type="button" role="tab" aria-selected={tab === "enrollments"}
          className={`join-course-tab${tab === "enrollments" ? " active" : ""}`} onClick={() => setTab("enrollments")}>
          我的申请 <span>{[...joinedCourseIds.values()].filter((status) => status === "PENDING").length}</span>
        </button>
      </div>

      <Panel>
          <FilterBar
            search={{ value: search, onChange: setSearch, label: "搜索课程", placeholder: "搜索课程名称或课程代码" }}
          />
          <form className="page-actions section" onSubmit={(event) => {
            event.preventDefault();
            const code = invitationSearch.trim();
            if (code && !resolveInvitation.isPending && !joinMutation.isPending) resolveInvitation.mutate(code);
          }}>
            <label className="form-label" htmlFor="direct-invitation-code" style={{ margin: 0 }}>邀请码直达</label>
            <input id="direct-invitation-code" className="field" value={invitationSearch} onChange={(event) => setInvitationSearch(event.target.value)} placeholder="输入邀请码直接加入关联课程" />
            <Button type="submit" variant="primary" disabled={!invitationSearch.trim() || resolveInvitation.isPending || joinMutation.isPending}>
              {resolveInvitation.isPending || joinMutation.isPending ? "提交中…" : "使用邀请码加入"}
            </Button>
          </form>
        <RequestStateView
          loading={catalog.isLoading || enrollments.isLoading}
          error={catalog.error ?? enrollments.error}
          onRetry={() => { void catalog.refetch(); void enrollments.refetch(); }}
          empty={!courses.length}
          emptyState={(
            <EmptyState
              title={tab === "discover" ? "没有找到匹配的开放课程" : "暂无申请记录"}
              hint={tab === "discover" ? "试试其他关键词或使用邀请码加入。" : "先去「发现课程」查看本学期可申请的课程。"}
            />
          )}
        >
          <div className="section">
            <div className="join-grid">
              {courses.map((course) => {
                const status = statusWording(course.public_id);
                const enrollment = enrollmentByCourseId.get(course.public_id);
                return (
                  <article className="join-course-card" key={course.public_id}>
                    <div className="join-course-card-top">
                      <div>
                        <div className="join-course-code">{course.code}</div>
                        <h2 style={{ fontSize: 16 }}>{course.title}</h2>
                      </div>
                      <span className="join-course-subject-icon" aria-hidden="true">书</span>
                    </div>
                    <p className="join-course-summary">{course.summary || "课程简介由教师后续补充。"}</p>
                    <div className="join-course-meta">
                      <span>{course.owner_name ?? "—"}</span>
                      <span>{course.active_enrollment_count}{course.capacity ? ` / ${course.capacity} 人` : " 人已加入"}</span>
                      <span>截止 {formatDate(course.enrollment_end)}</span>
                    </div>
                    <div className="join-course-card-footer">
                      <span className="join-course-mode-note">
                        {status.label
                          ? status.label === "已加入" ? `${course.active_enrollment_count} 人课程进行中` : "申请已提交，等待教师审核"
                          : "填写有效邀请码立即加入，否则提交后等待教师审核"}
                      </span>
                      <div className="join-course-card-actions">
                        {status.label
                          ? <>
                            <Button size="sm" onClick={() => {
                              if (status.label === "已加入") navigate(`/courses/${course.public_id}`);
                              else void enrollments.refetch();
                            }}>{status.label === "已加入" ? "进入课程" : "查看申请状态"}</Button>
                            {tab === "enrollments" && enrollment
                              ? <EnrollmentExit enrollment={enrollment} />
                              : null}
                          </>
                          : <Button size="sm" variant="primary" onClick={() => {
                            setInvitationCode("");
                            setApplicationMessage("");
                            setApplyTarget({ courseId: course.public_id, title: course.title });
                          }}>
                            申请加入
                          </Button>}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          </div>
        </RequestStateView>
      </Panel>

      <Modal open={applyTarget != null} onClose={() => { setApplyTarget(null); setInvitationCode(""); setApplicationMessage(""); }}
        title={applyTarget ? `加入 ${applyTarget.title}` : "加入课程"}
        eyebrow="课程加入申请"
        actions={(
          <>
            <Button onClick={() => { setApplyTarget(null); setInvitationCode(""); setApplicationMessage(""); }}>取消</Button>
            <Button variant="primary" disabled={joinMutation.isPending}
              onClick={() => { if (applyTarget) joinMutation.mutate({ courseId: applyTarget.courseId, payload: {
                invitation_code: invitationCode.trim() || undefined,
                application_message: applicationMessage.trim() || undefined,
              } }); }}>
              {joinMutation.isPending ? "提交中…" : invitationCode.trim() ? "使用邀请码加入" : "提交加入申请"}
            </Button>
          </>
        )}
      >
        <p className="subtle">
          {invitationCode.trim()
            ? "邀请码校验成功后将直接加入课程。"
            : "未填写邀请码时需要教师审核，提交后可在「我的申请」中查看进度。"}
        </p>
        <label className="form-label" htmlFor="invitation-code">课程邀请码 <span>选填</span></label>
        <input id="invitation-code" className="field" value={invitationCode} onChange={(event) => setInvitationCode(event.target.value)} />
        <label className="form-label" htmlFor="application-message">申请说明 <span>选填</span></label>
        <textarea id="application-message" className="field" rows={3} value={applicationMessage} onChange={(event) => setApplicationMessage(event.target.value)} />
      </Modal>
    </>
  );
}
