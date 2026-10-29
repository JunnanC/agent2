import { useRef } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { AppShell, EmptyState, LoadingState } from "@edu/ui";
import type { NavEntry, NavGroupEntry } from "@edu/ui";
import { useSession } from "./session";
import { usePortalEvents } from "./providers";

const ADMIN_NAV: Array<NavEntry | NavGroupEntry> = [
  { label: "平台概览", path: "/" },
  { label: "用户与授权", path: "/users" },
  { label: "治理工作", path: "/governance" },
  { label: "资源治理", path: "/resources" },
  { label: "镜像目录", path: "/images" },
  { label: "Agent 治理", path: "/agents" },
  { label: "异常中心", path: "/incidents" },
  { label: "异常与审计", path: "/audit" },
];

export function PortalSSEBridge() {
  const session = useSession();
  const streamRef = useRef<import("@edu/event-client").PortalEventStream | null>(null);
  usePortalEvents({ enabled: session.me != null, streamRef });
  return null;
}

export function AuthGuard({ shell = true }: { shell?: boolean }) {
  const session = useSession();
  const navigate = useNavigate();
  const location = useLocation();

  if (session.loading || session.error?.kind === "auth") {
    return <div className="app-shell"><LoadingState label="正在确认平台会话" /></div>;
  }
  if (session.error) {
    return (
      <div className="app-shell">
        <EmptyState
          title="无法进入平台管理门户"
          hint={session.error.payload?.message ?? session.error.message}
          action={<button type="button" className="btn" onClick={session.reload}>重新加载</button>}
        />
      </div>
    );
  }
  if (!session.me) return <div className="app-shell"><LoadingState label="正在确认平台会话" /></div>;

  if (session.me.portal !== "PLATFORM" && !session.me.eligible_portals.includes("PLATFORM")) {
    return (
      <div className="app-shell">
        <EmptyState
          title="当前账号没有平台管理权限"
          hint="需要平台管理员授权；请通过平台管理员身份访问 admin.localhost。"
          icon="shield"
        />
      </div>
    );
  }

  if (!shell) return <Outlet />;

  const { me, logout } = session;
  const displayName = me.display_name || me.username;

  return (
    <div className="app-shell">
      <AppShell
        domainLabel="admin.localhost"
        nav={ADMIN_NAV}
        activePath={location.pathname}
        onNavigate={navigate}
        avatar={{ name: displayName, role: "平台管理员", badge: displayName.slice(0, 1) }}
        avatarItems={[
          { label: "退出登录", icon: "log-out", onClick: () => { void logout().then(() => navigate("/login", { replace: true })); } },
        ]}
      >
        <Outlet />
      </AppShell>
    </div>
  );
}
