import { CourseLayout } from "./course-layout";
import { useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { meApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { AppShell, EmptyState, LoadingState } from "@edu/ui";
import type { NavEntry } from "@edu/ui";
import { useSession } from "./session";
import { usePortalEvents } from "./providers";

/** 一级扁平导航：不再使用下拉分组，点击即进入对应页面 */
const TEACHER_NAV: Array<NavEntry> = [
  { label: "教学概览", path: "/", icon: "layers" },
  { label: "我的课程", path: "/courses", icon: "book" },
  { label: "通知", path: "/notifications", icon: "bell" },
];

/** 全站 SSE 桥：会话就绪后连接 */
export function PortalSSEBridge() {
  const session = useSession();
  const streamRef = useRef<import("@edu/event-client").PortalEventStream | null>(null);
  usePortalEvents({ enabled: session.me != null, streamRef });
  return null;
}

export function AuthGuard() {
  const session = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const params = useParams();
  const notifications = useQuery({
    queryKey: keys.notifications({}),
    queryFn: () => meApi.notifications({ page_size: 50 }),
    enabled: session.me != null,
    refetchInterval: 30_000,
  });
  const unread = (notifications.data?.rows ?? []).filter((item) => !item.read).length;

  if (session.loading || session.error?.kind === "auth") {
    return <div className="app-shell"><LoadingState label="正在确认登录会话" /></div>;
  }
  if (session.error) {
    return (
      <div className="app-shell">
        <EmptyState
          title="无法进入教师门户"
          hint={session.error.payload?.message ?? session.error.message}
          action={<button type="button" className="btn" onClick={session.reload}>重新加载</button>}
        />
      </div>
    );
  }
  if (!session.me) return <div className="app-shell"><LoadingState label="正在确认登录会话" /></div>;

  if (session.me.portal !== "TEACHING" && !session.me.eligible_portals.includes("TEACHING")) {
    return (
      <div className="app-shell">
        <EmptyState
          title="当前账号未开通教师门户"
          hint="请通过教师门户地址 teacher.localhost 登录教师账号。"
          icon="shield"
        />
      </div>
    );
  }

  const { me, logout } = session;
  const displayName = me.display_name || me.username;
  void params;
  const nav = TEACHER_NAV;
  return (
    <div className="app-shell">
      <AppShell
        brand="教学实验平台"
        domainLabel="教师教学空间"
        navigationPosition="side"
        collapsible
        collapseStorageKey="edu.teacher.sidebar-collapsed"
        nav={nav}
        activePath={location.pathname.startsWith("/courses/") ? "/courses" : location.pathname}
        onNavigate={navigate}
        avatar={{ name: displayName, role: "教师", badge: displayName.slice(0, 1) }}
        actions={<button type="button" className="btn sm" aria-label={`通知中心，${unread} 条未读`}
          onClick={() => navigate("/notifications")}>通知中心{unread ? `（${unread}）` : ""}</button>}
        avatarItems={[
          { label: "退出登录", icon: "log-out", onClick: () => { void logout().then(() => navigate("/login", { replace: true })); } },
        ]}
      >
        <CourseLayout><Outlet /></CourseLayout>
      </AppShell>
    </div>
  );
}

