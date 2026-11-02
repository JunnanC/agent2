import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { studentApi, taskApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Breadcrumbs, EmptyState, Panel, RequestStateView, StatusBadge } from "@edu/ui";
import { formatDate, formatDateTime, taskStatusLabel, taskStatusTone } from "@/lib/task-format";

export function CourseDetail() {
  const { courseId = "" } = useParams();
  const [selectedChapterId, setSelectedChapterId] = useState<string | null>(null);
  const detail = useQuery({ queryKey: keys.course(courseId), queryFn: () => studentApi.courseDetail(courseId) });
  const chapters = useQuery({ queryKey: keys.courseResource(courseId, "chapters"), queryFn: () => studentApi.courseChapters(courseId) });
  const materials = useQuery({ queryKey: keys.courseResource(courseId, "materials"), queryFn: () => studentApi.courseMaterials(courseId) });
  const announcements = useQuery({ queryKey: keys.courseResource(courseId, "announcements"), queryFn: () => studentApi.courseAnnouncements(courseId) });
  const events = useQuery({ queryKey: keys.courseResource(courseId, "calendar-events"), queryFn: () => studentApi.courseCalendarEvents(courseId) });
  const tasks = useQuery({ queryKey: keys.tasks({ course_id: courseId }), queryFn: () => taskApi.list({ course_id: courseId }) });
  const selectedChapter = useMemo(() => {
    const rows = chapters.data?.rows ?? [];
    return rows.find((chapter) => chapter.public_id === selectedChapterId) ?? rows[0] ?? null;
  }, [chapters.data, selectedChapterId]);

  return (
    <>
      <Breadcrumbs
        items={[{ label: "学生门户", onClick: () => { window.location.assign("/"); } }, { label: "我的课程", onClick: () => { window.location.assign("/courses"); } }]}
        current={detail.data?.title ?? "课程详情"}
      />
      <div className="course-learning-shell">
        <aside className="panel course-chapter-nav">
          <div className="panel-title">
            <h2 style={{ fontSize: 15 }}>课程章节</h2>
            {detail.data ? <StatusBadge tone={detail.data!.status === "ACTIVE" ? "good" : "neutral"}>{detail.data!.status === "ACTIVE" ? "已加入" : detail.data!.status}</StatusBadge> : null}
          </div>
          <RequestStateView loading={chapters.isLoading} error={chapters.error}
            onRetry={() => void chapters.refetch()}
            empty={!chapters.data?.rows.length}
            emptyState={<div className="state-block"><strong>暂无章节</strong><p>教师尚未发布课程章节。</p></div>}>
            <div>
              {(chapters.data?.rows ?? []).map((chapter, index) => (
                <button type="button" key={chapter.public_id}
                  className={`course-chapter-row${chapter.public_id === selectedChapter?.public_id ? " active" : ""}`}
                  aria-pressed={chapter.public_id === selectedChapter?.public_id}
                  onClick={() => setSelectedChapterId(chapter.public_id)}>
                  <span>{index + 1}</span>
                  <strong>{chapter.title}</strong>
                  {chapter.description ? <small>章节说明</small> : null}
                </button>
              ))}
            </div>
          </RequestStateView>
        </aside>

        <section className="course-learning-main">
          <Panel title={<><h2>课程信息</h2></>}>
            <div className="grid equal section" style={{ marginTop: 0 }}>
              <div>
                <span className="eyebrow">课程代码</span>
                <strong style={{ display: "block" }}>{detail.data?.code ?? "—"}</strong>
                <span className="eyebrow" style={{ marginTop: 10, display: "block" }}>课程负责人</span>
                <strong style={{ display: "block" }}>{detail.data?.owner_name ?? "—"}</strong>
                <span className="eyebrow" style={{ marginTop: 10, display: "block" }}>教学周期</span>
                <strong style={{ display: "block" }}>{formatDate(detail.data?.teaching_start)} — {formatDate(detail.data?.teaching_end)}</strong>
              </div>
              <div>
                <span className="eyebrow">申请状态</span>
                <div style={{ margin: "4px 0 10px" }}>
                  <StatusBadge tone={detail.data?.enrollment_mode === "OPEN" ? "blue" : "warn"}>
                    {detail.data?.enrollment_mode === "OPEN" ? "直接加入" : "需要审核"}
                  </StatusBadge>
                </div>
                <span className="eyebrow">申请截止</span>
                <strong style={{ display: "block" }}>{formatDate(detail.data?.enrollment_end)}</strong>
              </div>
            </div>
          </Panel>

          {selectedChapter ? (
            <Panel title={<><h2>{selectedChapter.title}</h2><span className="subtle">课程章节</span></>}>
              <p className="course-chapter-description">
                {selectedChapter.description || "本章节暂未提供说明。"}
              </p>
            </Panel>
          ) : null}

          <Panel id="course-tasks" title={<><h2>本课程实验任务</h2><span className="subtle">按截止时间处理</span></>}>
            <RequestStateView loading={tasks.isLoading} error={tasks.error}
              onRetry={() => void tasks.refetch()}
              empty={!tasks.data?.rows.length}
              emptyState={<EmptyState title="本课程暂无实验任务" hint="实验发布后任务会出现在这里。" />}>
              <div>
                {(tasks.data?.rows ?? []).map((task) => (
                  <div className="task-row" key={task.public_id}>
                    <div>
                      <Link className="task-title" to={`/experiments/${task.public_id}`}>{task.title}</Link>
                      <div className="task-meta">完成度 {task.progress}% · 截止 {formatDateTime(task.effective_deadline)}</div>
                    </div>
                    <div className="task-side">
                      <StatusBadge tone={taskStatusTone(task.status)}>{taskStatusLabel(task.status)}</StatusBadge>
                      {task.allowed_actions.includes("enter") && !task.blockers.length
                        ? <Link className="btn sm primary" to={`/experiments/${task.public_id}/workbench`}>进入工作台</Link>
                        : <Link className="btn sm" to={`/experiments/${task.public_id}`}>查看详情</Link>}
                    </div>
                  </div>
                ))}
              </div>
            </RequestStateView>
          </Panel>

          <div className="grid two">
            <Panel title={<h2>课程材料</h2>}>
              <RequestStateView loading={materials.isLoading} error={materials.error}
                onRetry={() => void materials.refetch()}
                empty={!materials.data?.rows.length}
                emptyState={<EmptyState title="暂无课程材料" hint="教师上传材料后会显示在这里。" />}>
                <div>
                  {(materials.data?.rows ?? []).map((material) => (
                    <div className="item" key={material.public_id}>
                      <div><strong>{material.title}</strong><small>{material.type ?? "材料"}</small></div>
                      <span className="status neutral">{material.status === "PUBLISHED" ? "已发布" : material.status ?? ""}</span>
                    </div>
                  ))}
                </div>
              </RequestStateView>
            </Panel>
            <Panel title={<h2>课程公告</h2>}>
              <RequestStateView loading={announcements.isLoading} error={announcements.error}
                onRetry={() => void announcements.refetch()}
                empty={!announcements.data?.rows.length}
                emptyState={<EmptyState title="暂无公告" />}>
                <div>
                  {(announcements.data?.rows ?? []).slice(0, 5).map((announcement) => (
                    <div className="item" key={announcement.public_id}>
                      <div><strong>{announcement.title}</strong><small>{formatDateTime(announcement.published_at)}</small></div>
                    </div>
                  ))}
                </div>
              </RequestStateView>
            </Panel>
          </div>

          <div className="grid two">
            <Panel title={<><h2>课程日历</h2><span className="subtle">截止与关键时间</span></>}>
              <RequestStateView loading={events.isLoading} error={events.error}
                onRetry={() => void events.refetch()}
                empty={!events.data?.rows.length}
                emptyState={<EmptyState title="暂无日历事件" />}>
                <div>
                  {(events.data?.rows ?? []).slice(0, 8).map((event) => (
                    <div className="item" key={event.public_id}>
                      <div><strong>{event.title}</strong><small>{formatDateTime(event.start_at)}</small></div>
                      {event.kind ? <span className="status blue">{event.kind}</span> : null}
                    </div>
                  ))}
                </div>
              </RequestStateView>
            </Panel>
            <Panel title={<h2>课程问答</h2>} actions={<span className="status blue">Agent 助教</span>}>
              <div className="section" style={{ marginTop: 4 }}>
                <p className="subtle">在任务进行中遇到问题时，可进入实验任务详情向课程 Agent 提问；Agent 工具调用仅在获得确认后执行。</p>
                <Link className="btn" to={`/experiments/${(tasks.data?.rows ?? [])[0]?.public_id ?? ""}`}>进入最近实验提问</Link>
              </div>
            </Panel>
          </div>
        </section>
      </div>
    </>
  );
}
