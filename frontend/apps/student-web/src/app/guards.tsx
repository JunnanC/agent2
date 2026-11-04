import { useRef } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { AppShell, EmptyState, LoadingState } from "@edu/ui";
import type { NavEntry } from "@edu/ui";
import { useSession } from "./session";
import { usePortalEvents } from "./providers";

const STUDENT_NAV: Array<NavEntry> = [
  { label: "概览", path: "/", icon: "layers" },
  { label: "我的课程", path: "/courses", icon: "book" },
  { label: "通知", path: "/notifications", icon: "bell" },
];

/** 全站 SSE 桥：会话就绪后连接，事件只做提示并触发 REST 失效 */
export function PortalSSEBridge() {
  const session = useSession();
  const streamRef = useRef<import("@edu/event-client").PortalEventStream | null>(null);
  usePortalEvents({ enabled: session.me != null, platform: "student", streamRef });
  return null;
}

export function AuthGuard({ fullscreen }: { fullscreen?: boolean }) {
  const session = useSession();
  const navigate = useNavigate();
  const location = useLocation();

  if (session.loading || session.error?.kind === "auth") {
    return <div className="app-shell"><LoadingState label="正在确认登录会话" /></div>;
  }

  if (session.error) {
    return (
      <div className="app-shell">
        <EmptyState
          title="无法进入学生门户"
          hint={session.error.message}
          action={<button type="button" className="btn" onClick={session.reload}>重新加载</button>}
        />
      </div>
    );
  }
  if (!session.me) return <div className="app-shell"><LoadingState label="正在确认登录会话" /></div>;

  if (session.me.portal !== "USER" && !session.me.eligible_portals.includes("USER")) {
    return (
      <div className="app-shell">
        <EmptyState
          title="当前账号未开通学生门户"
          hint="请通过学生门户地址 student.localhost 登录学生账号。"
          icon="shield"
        />
      </div>
    );
  }

  const { me, logout } = session;
  const displayName = me.display_name || me.username;

  if (fullscreen) return <Outlet />;

  return (
    <div className="app-shell">
      <AppShell
        domainLabel="student.localhost"
        nav={STUDENT_NAV}
        activePath={location.pathname}
        onNavigate={navigate}
        avatar={{ name: displayName, role: "学生", badge: displayName.slice(0, 1) }}
        avatarItems={[
          { label: "个人设置", icon: "settings", onClick: () => navigate("/profile") },
          { label: "退出登录", icon: "log-out", onClick: () => { void logout().then(() => navigate("/login", { replace: true })); } },
        ]}
        navigationPosition="side"
        collapsible
        collapseStorageKey="edu.student.sidebar-collapsed"
      >
        <Outlet />
      </AppShell>
    </div>
  );
}
