import { CourseLayout } from "./course-layout";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { meApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { EmptyState, LoadingState } from "@edu/ui";
import { TeacherDialog, TeacherIcon } from "@/components/teacher-b";
import { TeacherHeader } from "@/components/teacher-header";
import { useSession } from "./session";
import { usePortalEvents } from "./providers";

export function PortalSSEBridge() {
  const session = useSession();
  const streamRef = useRef<import("@edu/event-client").PortalEventStream | null>(null);
  usePortalEvents({ enabled: session.me != null, streamRef });
  return null;
}

export function AuthGuard() {
  const session = useSession();
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  const homeSearch = useRef("");
  const [notificationsOpen, showNotifications] = useState(false);
  const eligible = session.me != null &&
    (session.me.portal === "TEACHING" || session.me.eligible_portals.includes("TEACHING"));
  const notifications = useQuery({
    queryKey: keys.notifications({}),
    queryFn: () => meApi.notifications({ page_size: 50 }),
    enabled: eligible,
    refetchInterval: 30_000,
  });
  useEffect(() => {
    if (pathname === "/") homeSearch.current = search;
  }, [pathname, search]);
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);

  if (session.loading || session.error?.kind === "auth") {
    return <div className="app-shell"><LoadingState label="正在确认登录会话" /></div>;
  }
  if (session.error) return <div className="app-shell">
    <EmptyState title="无法进入教师门户" hint={session.error.payload?.message ?? session.error.message}
      action={<button type="button" className="btn" onClick={session.reload}>重新加载</button>} />
  </div>;
  if (!session.me) return <div className="app-shell"><LoadingState label="正在确认登录会话" /></div>;
  if (!eligible) return <div className="app-shell">
    <EmptyState title="当前账号未开通教师门户" hint="请通过教师门户地址 teacher.localhost 登录教师账号。" icon="shield" />
  </div>;

  const rows = notifications.data?.rows ?? [];
  const home = "/" + homeSearch.current;
  const coursePage = pathname.startsWith("/courses/");
  return <div className="teacher-b">
    <TeacherHeader name={session.me.display_name || session.me.username} unread={rows.filter((item) => !item.read).length}
      onNotifications={() => showNotifications(true)}
      onLogout={() => { void session.logout().finally(() => navigate("/login", { replace: true })).catch(() => undefined); }} />
    <main className="wrap">
      {coursePage ? <CourseLayout home={home}><Outlet /></CourseLayout> : pathname === "/" ? <Outlet /> :
        <div className="subpage"><Link className="back" to={home}><TeacherIcon name="left" />返回教师工作台</Link><Outlet /></div>}
    </main>
    {notificationsOpen && <TeacherDialog title="通知中心" onClose={() => showNotifications(false)}>
      {notifications.isPending && <p role="status">正在读取通知…</p>}
      {notifications.isError && <p role="alert">无法读取通知。<button className="text-button" onClick={() => void notifications.refetch()}>重试</button></p>}
      {notifications.isSuccess && !rows.length && <p>暂无通知。</p>}
      {rows.slice(0, 5).map((item) => <article key={item.id}>
        <p className="notice">{item.title}</p>
        {item.links?.filter((link) => link.url?.startsWith("/courses/")).map((link) =>
          <Link className="text-button" key={link.url} to={link.url!} onClick={() => showNotifications(false)}>
            {link.url?.includes("/enrollments") ? "查看入班申请" : link.label || "查看详情"}
          </Link>)}
      </article>)}
      <Link className="text-button" to="/notifications" onClick={() => showNotifications(false)}>查看全部通知</Link>
    </TeacherDialog>}
  </div>;
}

