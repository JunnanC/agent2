import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { fileApi, studentApi, taskApi } from "@edu/api-client";
import type { Material } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Breadcrumbs, Button, EmptyState, Panel, RequestStateView, StatusBadge, useToast } from "@edu/ui";
import { formatDate, formatDateTime, taskStatusLabel, taskStatusTone } from "@/lib/task-format";
import { CourseDiscussion } from "@/components/course-discussion";
import { CourseAgent } from "@/components/course-agent";
import { EnrollmentExit } from "@/components/enrollment-exit";
import { ApiError } from "@edu/auth-client";

export function CourseDetail({ discussionPage = false }: { discussionPage?: boolean }) {
  const { courseId = "", chapterId } = useParams();
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [activeChapterId, setActiveChapterId] = useState<string | null>(null);
  const chapterNavRef = useRef<HTMLElement>(null);
  const [openTextMaterialId, setOpenTextMaterialId] = useState<string | null>(null);
  const detail = useQuery({ queryKey: keys.course(courseId), queryFn: () => studentApi.courseDetail(courseId),
    staleTime: 0, refetchOnMount: "always", retry: false });
  const canRead = detail.isSuccess && !detail.isFetching;
  const loadOverview = canRead && !discussionPage && !chapterId;
  const enrollments = useQuery({ queryKey: keys.enrollments({ status: "ACTIVE" }),
    queryFn: () => studentApi.myEnrollments({ page_size: 100, status: "ACTIVE" }), enabled: loadOverview });
  const enrollment = enrollments.data?.rows.find((row) => row.course_id === courseId && row.status === "ACTIVE");
  const chapters = useQuery({ queryKey: keys.courseResource(courseId, "chapters"), queryFn: () => studentApi.courseChapters(courseId), enabled: canRead });
  const materials = useQuery({ queryKey: keys.courseResource(courseId, "materials"), queryFn: () => studentApi.courseMaterials(courseId), enabled: loadOverview });
  const announcements = useQuery({ queryKey: keys.courseResource(courseId, "announcements"), queryFn: () => studentApi.courseAnnouncements(courseId), enabled: loadOverview });
  const events = useQuery({ queryKey: keys.courseResource(courseId, "calendar-events"), queryFn: () => studentApi.courseCalendarEvents(courseId), enabled: loadOverview });
  const tasks = useQuery({ queryKey: keys.tasks({ course_id: courseId }), queryFn: () => taskApi.list({ course_id: courseId }), enabled: loadOverview });
  const openFile = useMutation({
    mutationFn: (material: Material) => {
      if (!material.object_asset_id) throw new Error("该材料暂时没有可打开的文件");
      return fileApi.createDownloadGrant(material.object_asset_id);
    },
    onSuccess: (grant) => {
      if (grant.download_path.startsWith("/files/") && !grant.download_path.includes("\\")) {
        window.location.assign(grant.download_path);
      } else toast.notify("文件打开地址无效", "error");
    },
    onError: (error) => toast.notify(error.message, "error"),
  });
  const chapterRows = chapters.data?.rows ?? [];
  const currentChapterId = chapterId ?? activeChapterId ?? chapterRows[0]?.public_id ?? null;
  useEffect(() => {
    if (!canRead || discussionPage || !chapters.data?.rows.length) return;
    const rows = chapters.data.rows;
    const firstChapterId = rows[0]?.public_id;
    if (!firstChapterId) return;
    let frame = 0;
    const updateChapter = () => {
      frame = 0;
      let current = firstChapterId;
      for (const chapter of rows) {
        const panel = document.getElementById(`course-chapter-${chapter.public_id}`);
        if (!panel) continue;
        const offset = parseFloat(window.getComputedStyle(panel).scrollMarginTop) || 0;
        if (panel.getBoundingClientRect().top <= offset + 1) current = chapter.public_id;
        else break;
      }
      setActiveChapterId(current);
    };
    const scheduleUpdate = () => {
      if (!frame) frame = window.requestAnimationFrame(updateChapter);
    };
    updateChapter();
    window.addEventListener("scroll", scheduleUpdate, { passive: true });
    window.addEventListener("resize", scheduleUpdate);
    return () => {
      window.cancelAnimationFrame(frame);
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
    return <EmptyState title="暂时无法进入课程" hint="课程申请需要教师同意后才能进入；撤回或退出后也无法访问课程内容。"
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

        <section className="course-learning-main">
          {chapterId || discussionPage ? <Link className="btn" to={`/courses/${courseId}`}>返回课程介绍</Link> : null}
          {chapterId ? <><RequestStateView loading={chapters.isLoading} error={chapters.error} onRetry={() => void chapters.refetch()} empty={!chapterRows.some((chapter) => chapter.public_id === chapterId)} emptyState={<EmptyState title="章节不存在或尚未发布" />} >{chapterRows.filter((chapter) => chapter.public_id === chapterId).map((chapter) => <Panel key={chapter.public_id} title={<h2>{chapter.title}</h2>}><p className="course-chapter-description">{chapter.description || "本章节暂未提供说明。"}</p></Panel>)}</RequestStateView></> : discussionPage ? <CourseDiscussion key={courseId} courseId={courseId} /> : <>
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
            </Panel>
          ))}

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
                      {task.assessment_available
                        ? <Link className="btn sm primary" to={`/experiments/${task.public_id}/assessment`}>进入实验答题</Link>
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
                      <div>
                        {material.kind === "LINK" && material.link_url ? (
                          <a className="task-title" href={material.link_url} target="_blank" rel="noreferrer">{material.title}</a>
                        ) : material.kind === "TEXT" ? (
                          <Button size="sm" onClick={() => setOpenTextMaterialId((current) => current === material.public_id ? null : material.public_id)}>{material.title}</Button>
                        ) : (
                          <Button size="sm" disabled={openFile.isPending || !material.object_asset_id} onClick={() => openFile.mutate(material)}>{material.title}</Button>
                        )}
                        <small>{material.kind === "FILE" ? "讲义 / 实验指导书" : material.kind === "LINK" ? "外部链接" : "在线阅读"}</small>
                        {material.kind === "TEXT" && openTextMaterialId === material.public_id ? <p className="course-chapter-description">{material.text_content || "暂无正文"}</p> : null}
                      </div>
                      <span className="status neutral">{material.version_status === "PUBLISHED" ? "已发布" : material.status ?? ""}</span>
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
          <CourseAgent key={courseId} courseId={courseId} />
          </>}
        </section>
      </div>
    </>
  );
}
