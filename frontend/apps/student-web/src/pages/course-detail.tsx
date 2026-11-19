import { ChapterResources } from "@/components/chapter-resources";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { studentApi, taskApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Breadcrumbs, EmptyState, Markdown, PageHeader, Panel, RequestStateView, StatusBadge } from "@edu/ui";
import { formatDate, formatDateTime, taskStatusLabel, taskStatusTone } from "@/lib/task-format";
import { CourseDiscussion } from "@/components/course-discussion";
import { CourseAgent } from "@/components/course-agent";
import { EnrollmentExit } from "@/components/enrollment-exit";
import { ApiError } from "@edu/auth-client";

function hasIndependentScroll(content: HTMLElement) {
  return ["auto", "scroll"].includes(window.getComputedStyle(content).overflowY);
}

export function CourseDetail({ discussionPage = false }: { discussionPage?: boolean }) {
  const { courseId = "", chapterId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [activeChapterId, setActiveChapterId] = useState<string | null>(null);
  const contentRef = useRef<HTMLElement>(null);
  const chapterNavRef = useRef<HTMLElement>(null);
  const lastOpenedChapter = useRef<string | null>(null);
  const detail = useQuery({ queryKey: keys.course(courseId), queryFn: () => studentApi.courseDetail(courseId),
    staleTime: 0, refetchOnMount: "always", retry: false });
  const canRead = detail.isSuccess && !detail.isFetching;
  const loadOverview = canRead && !discussionPage && !chapterId;
  const enrollments = useQuery({ queryKey: keys.enrollments({ status: "ACTIVE" }),
    queryFn: () => studentApi.myEnrollments({ page_size: 100, status: "ACTIVE" }), enabled: loadOverview });
  const enrollment = enrollments.data?.rows.find((row) => row.course_id === courseId && row.status === "ACTIVE");
  const chapters = useQuery({ queryKey: keys.courseResource(courseId, "chapters"), queryFn: () => studentApi.courseChapters(courseId), enabled: canRead });
  const announcements = useQuery({ queryKey: keys.courseResource(courseId, "announcements"), queryFn: () => studentApi.courseAnnouncements(courseId), enabled: loadOverview });
  const events = useQuery({ queryKey: keys.courseResource(courseId, "calendar-events"), queryFn: () => studentApi.courseCalendarEvents(courseId), enabled: loadOverview });
  const tasks = useQuery({ queryKey: keys.tasks({ course_id: courseId }), queryFn: () => taskApi.list({ course_id: courseId }), enabled: loadOverview });
  const chapterRows = chapters.data?.rows ?? [];
  const currentChapterId = chapterId ?? activeChapterId ?? chapterRows[0]?.public_id ?? null;

  useLayoutEffect(() => {
    if (!chapterId || discussionPage) {
      lastOpenedChapter.current = null;
      return;
    }
    const content = contentRef.current;
    if (!canRead || !chapters.isSuccess || !content || lastOpenedChapter.current === location.pathname) return;
    lastOpenedChapter.current = location.pathname;
    if (location.hash) return;

    if (hasIndependentScroll(content)) {
      content.scrollTop = 0;
    } else {
      content.scrollIntoView({ behavior: "instant", block: "start" });
    }
  }, [canRead, chapterId, chapters.isSuccess, discussionPage, location.hash, location.pathname]);

  useEffect(() => {
    if (!canRead || discussionPage || !chapters.data?.rows.length) return;
    const rows = chapters.data.rows;
    const firstChapterId = rows[0]?.public_id;
    if (!firstChapterId) return;
    let frame = 0;
    const updateChapter = () => {
      frame = 0;
      let current = firstChapterId;
      const container = contentRef.current;
      const rootTop = container && hasIndependentScroll(container)
        ? container.getBoundingClientRect().top : 0;
      for (const chapter of rows) {
        const panel = document.getElementById(`course-chapter-${chapter.public_id}`);
        if (!panel) continue;
        const offset = rootTop + (parseFloat(window.getComputedStyle(panel).scrollMarginTop) || 0);
        if (panel.getBoundingClientRect().top <= offset + 1) current = chapter.public_id;
        else break;
      }
      setActiveChapterId(current);
    };
    const scheduleUpdate = () => {
      if (!frame) frame = window.requestAnimationFrame(updateChapter);
    };
    updateChapter();
    const content = contentRef.current;
    content?.addEventListener("scroll", scheduleUpdate, { passive: true });
    window.addEventListener("scroll", scheduleUpdate, { passive: true });
    window.addEventListener("resize", scheduleUpdate);
    return () => {
      window.cancelAnimationFrame(frame);
      content?.removeEventListener("scroll", scheduleUpdate);
      window.removeEventListener("scroll", scheduleUpdate);
      window.removeEventListener("resize", scheduleUpdate);
    };
  }, [canRead, chapters.data, courseId, discussionPage]);

  useEffect(() => {
    if (!canRead || discussionPage || !chapters.isSuccess || !location.hash) return;
    const id = decodeURIComponent(location.hash.slice(1));
    const frame = window.requestAnimationFrame(() => {
      document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [canRead, discussionPage, chapters.isSuccess, location.hash]);

  useEffect(() => {
    const nav = chapterNavRef.current;
    const active = nav?.querySelector<HTMLElement>('[aria-current="location"]');
    if (!nav || !active || nav.scrollHeight <= nav.clientHeight) return;
    const bounds = nav.getBoundingClientRect();
    const row = active.getBoundingClientRect();
    if (row.top < bounds.top) nav.scrollTop += row.top - bounds.top;
    else if (row.bottom > bounds.bottom) nav.scrollTop += row.bottom - bounds.bottom;
  }, [currentChapterId, discussionPage]);

  const scrollToChapter = (chapterId: string) => {
    navigate(`/courses/${courseId}/chapters/${encodeURIComponent(chapterId)}`);
  };

  if (detail.error instanceof ApiError && ["ACTIVE_ENROLLMENT_REQUIRED", "RESOURCE_NOT_FOUND"].includes(detail.error.payload?.code ?? "")) {
    return <EmptyState title="暂时无法进入课程" hint="需要教师通过选课申请后才能查看课程内容。"
      action={<Link className="btn primary" to="/courses">返回我的课程</Link>} />;
  }
  if (detail.isPending || detail.isFetching || detail.error || !detail.data) {
    return <RequestStateView loading={detail.isPending || detail.isFetching} error={detail.error} empty={!detail.data}
      onRetry={() => void detail.refetch()} emptyState={<EmptyState title="无法进入课程" hint="请先等待教师审核通过，课程才会加入我的课程。" />} />;
  }

  return (
    <>
      <Breadcrumbs
        items={[{ label: "学生门户", onClick: () => { window.location.assign("/"); } }, { label: "我的课程", onClick: () => { window.location.assign("/courses"); } }]}
        current={discussionPage ? `${detail.data.title} · 课程问答` : detail.data.title}
      />
      <PageHeader title={discussionPage ? `${detail.data.title} · 课程问答` : detail.data.title} />
      <div className="course-learning-shell">
        <aside ref={chapterNavRef} className="panel course-chapter-nav">
          <div className="panel-title">
            <h2 style={{ fontSize: 15 }}>课程章节</h2>
            <StatusBadge tone="good">已加入</StatusBadge>
          </div>
          <RequestStateView loading={chapters.isLoading} error={chapters.error}
            onRetry={() => void chapters.refetch()}
            empty={!chapters.data?.rows.length}
            emptyState={<div className="state-block"><strong>暂无章节</strong><p>教师尚未发布课程章节。</p></div>}>
            <div>
              {chapterRows.map((chapter, index) => (
                <button type="button" key={chapter.public_id}
                  className={`course-chapter-row${!discussionPage && chapter.public_id === currentChapterId ? " active" : ""}`}
                  aria-current={!discussionPage && chapter.public_id === currentChapterId ? "location" : undefined}
                  onClick={() => scrollToChapter(chapter.public_id)}>
                  <span>{index + 1}</span>
                  <strong>{chapter.title}</strong>
                  {chapter.description ? <small>章节说明</small> : null}
                </button>
              ))}
            </div>
          </RequestStateView>
          {chapters.isSuccess ? <Link to={`/courses/${courseId}/questions`}
            className={`course-chapter-row${discussionPage ? " active" : ""}`}
            aria-current={discussionPage ? "page" : undefined}>
            <span>{chapterRows.length + 1}</span><strong>课程问答</strong>
          </Link> : null}
        </aside>

        <section ref={contentRef} className="course-learning-main" aria-label="课程内容">
          {chapterId || discussionPage ? <Link className="btn" to={`/courses/${courseId}`}>返回课程介绍</Link> : null}
          {chapterId ? <><RequestStateView loading={chapters.isLoading} error={chapters.error} onRetry={() => void chapters.refetch()} empty={!chapterRows.some((chapter) => chapter.public_id === chapterId)} emptyState={<EmptyState title="章节不存在或尚未发布" />} >{chapterRows.filter((chapter) => chapter.public_id === chapterId).map((chapter) => <Panel key={chapter.public_id} title={<h2>{chapter.title}</h2>}><p className="course-chapter-description">{chapter.description || "本章节暂未提供说明。"}</p>{chapter.content ? <Markdown source={chapter.content} /> : null}</Panel>)}</RequestStateView>{chapterRows.some(chapter => chapter.public_id === chapterId) && <ChapterResources key={chapterId} courseId={courseId} chapterId={chapterId} />}</> : discussionPage ? <CourseDiscussion key={courseId} courseId={courseId} /> : <>
          <Panel title={<><h2>课程信息</h2></>} actions={enrollment ? <EnrollmentExit enrollment={enrollment} onExited={() => navigate("/courses", { replace: true })} /> : undefined}>
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
                <span className="eyebrow">课程状态</span>
                <div style={{ margin: "4px 0 10px" }}>
                  <StatusBadge tone="good">已加入</StatusBadge>
                </div>
                <span className="eyebrow">课程截止</span>
                <strong style={{ display: "block" }}>{formatDate(detail.data?.teaching_end)}</strong>
              </div>
            </div>
          </Panel>

          {chapterRows.map((chapter, index) => (
            <Panel id={`course-chapter-${chapter.public_id}`} key={chapter.public_id}
              title={<><h2>{chapter.title}</h2><span className="subtle">章节 {index + 1}</span></>}>
              <p className="course-chapter-description">
                {chapter.description || "本章节暂未提供说明。"}
              </p>
              <Link className="btn" to={`/courses/${courseId}/chapters/${chapter.public_id}`}>进入章节 · 材料与实验</Link>
            </Panel>
          ))}

          <Panel id="course-tasks" title={<><h2>本课程实验任务</h2><span className="subtle">按截止时间处理</span></>}>
            <RequestStateView loading={tasks.isLoading} error={tasks.error}
              onRetry={() => void tasks.refetch()}
              empty={!tasks.data?.rows.length}
              emptyState={<EmptyState title="本课程暂无实验任务" hint="实验发布后会出现在这里。" />}>
              <div>
                {(tasks.data?.rows ?? []).map((task) => (
                  <div className="task-row" key={task.public_id}>
                    <div>
                      <Link className="task-title" to={`/experiments/${task.public_id}`}>{task.title}</Link>
                      <div className="task-meta">完成度 {task.progress}% · 截止 {formatDateTime(task.effective_deadline)}</div>
                    </div>
                    <div className="task-side">
                      <StatusBadge tone={taskStatusTone(task.status)}>{taskStatusLabel(task.status)}</StatusBadge>
                      {task.assessment_available
                        ? <Link className="btn sm primary" to={`/experiments/${task.public_id}/assessment`}>进入实验答题</Link>
                        : <Link className="btn sm" to={`/experiments/${task.public_id}`}>查看详情</Link>}
                    </div>
                  </div>
                ))}
              </div>
            </RequestStateView>
          </Panel>

          <div className="grid equal">
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

            <Panel title={<h2>课程日历</h2>}>
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
          </div>
          <CourseAgent key={courseId} courseId={courseId} />
          </>}
        </section>
      </div>
    </>
  );
}
