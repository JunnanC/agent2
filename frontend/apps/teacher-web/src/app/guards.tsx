import { CourseLayout } from "./course-layout";
import { useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { meApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Link, Outlet, useLocation, useNavigate, useParams } from "react-router-dom";
import { AppShell, EmptyState, Icon, LoadingState } from "@edu/ui";
import { useSession } from "./session";
import { usePortalEvents } from "./providers";

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
  return (
    <div className="app-shell">
      <AppShell
        brand="实验教学平台"
        domainLabel="教师门户"
        nav={[]}
        activePath={location.pathname.startsWith("/courses/") ? "/courses" : location.pathname}
        onNavigate={(path) => navigate(path === "/courses" ? "/courses" : path)}
        avatar={{ name: displayName, role: "教师", badge: displayName.slice(0, 1) }}
        actions={<button type="button" className="btn sm" aria-label={`通知中心，${unread} 条未读`}
          onClick={() => navigate("/notifications")}><Icon name="bell" size={18} /><span className="notification-label">通知中心{unread ? `（${unread}）` : ""}</span></button>}
        avatarItems={[
          { label: "退出登录", icon: "log-out", onClick: () => { void logout().then(() => navigate("/login", { replace: true })); } },
        ]}
      >
        {location.pathname !== "/" && <Link className="btn sm" to="/">返回课表</Link>}
        <CourseLayout><Outlet /></CourseLayout>
      </AppShell>
    </div>
  );
}

