import { useEffect, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { Icon, IconName } from "./icons";

export interface NavEntry { label: string; path: string; icon?: IconName; }

export interface NavGroupEntry { label: string; items: NavEntry[]; }

export type NavItem = NavEntry | NavGroupEntry;

function isGroup(item: NavItem): item is NavGroupEntry {
  return "items" in item;
}

export interface AvatarMenuItem { label: string; onClick?: () => void; icon?: IconName; }

export interface AppShellProps {
  brand?: string;
  domainLabel: string;
  nav: NavItem[];
  activePath: string;
  onNavigate: (path: string) => void;
  avatar: { name: string; role: string; badge?: string };
  avatarItems?: AvatarMenuItem[];
  actions?: ReactNode;
  children: ReactNode;
  maxWidth?: CSSProperties["maxWidth"];
  navigationPosition?: "top" | "side";
  collapsible?: boolean;
  collapseStorageKey?: string;
}

export function AppShell({
  brand = "Edu Agent Platform", domainLabel, nav, activePath, onNavigate,
  avatar, avatarItems = [], actions, children, maxWidth,
  navigationPosition = "top", collapsible = false, collapseStorageKey,
}: AppShellProps) {
  const [collapsed, setCollapsed] = useState(() => {
    try { return Boolean(collapseStorageKey && localStorage.getItem(collapseStorageKey) === "true"); }
    catch { return false; }
  });
  const canCollapse = collapsible && navigationPosition === "side";
  const toggleSidebar = () => {
    const next = !collapsed;
    setCollapsed(next);
    try { if (collapseStorageKey) localStorage.setItem(collapseStorageKey, String(next)); }
    catch { /* Navigation still works when storage is unavailable. */ }
  };
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [avatarOpen, setAvatarOpen] = useState(false);

  useEffect(() => {
    const closeAvatar = () => setAvatarOpen(false);
    document.addEventListener("click", closeAvatar);
    return () => document.removeEventListener("click", closeAvatar);
  }, []);

  const groupActive = (group: NavGroupEntry) => group.items.some((item) => item.path === activePath);

  return (
    <div className={`shell-layout${navigationPosition === "side" ? " side-nav-shell" : ""}${canCollapse ? " collapsible-shell" : ""}${canCollapse && collapsed ? " nav-collapsed" : ""}`}>
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true"><Icon name="layers" size={16} /></span>
          <span className="brand-name">{brand}</span>
          <span className="context-dot" aria-hidden="true" />
          <span className="context-label">{domainLabel}</span>
        </div>
        {canCollapse ? <button type="button" className="sidebar-toggle"
          aria-label={collapsed ? "展开导航" : "收起导航"} title={collapsed ? "展开导航" : "收起导航"}
          aria-expanded={!collapsed} aria-controls="collapsible-primary-nav" onClick={toggleSidebar}>
          <Icon name={collapsed ? "chevron-right" : "chevron-left"} size={18} />
          <span className="nav-label">收起导航</span>
        </button> : null}
        <nav id={canCollapse ? "collapsible-primary-nav" : undefined} className="primary-nav" aria-label="一级导航">
          {nav.map((item) => {
            if (!isGroup(item)) {
              return (
                <button key={item.path} type="button" className={`nav-item${activePath === item.path ? " active" : ""}`}
                  aria-label={item.label} title={canCollapse ? item.label : undefined}
                  aria-current={activePath === item.path ? "page" : undefined}
                  onClick={() => onNavigate(item.path)}>
                  {item.icon ? <Icon name={item.icon} size={18} /> : null}
                  <span className="nav-label">{item.label}</span>
                </button>
              );
            }
            const isOpen = openGroup === item.label;
            return (
              <div key={item.label} className="nav-group">
                <button type="button" className={`nav-item${groupActive(item) ? " active" : ""}`}
                  aria-expanded={isOpen} aria-haspopup="menu"
                  onClick={() => setOpenGroup(isOpen ? null : item.label)}>
                  {item.label} <Icon name="chevron-down" size={12} />
                </button>
                {isOpen ? (
                  <div className="nav-group-menu" role="menu">
                    {item.items.map((child) => (
                      <button key={child.path} type="button" role="menuitem"
                        className={activePath.startsWith(child.path) ? "active" : undefined}
                        onClick={() => { setOpenGroup(null); onNavigate(child.path); }}>
                        {child.label}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </nav>
        <div className="topbar-actions">
          {actions}
          <div className="profile-menu-wrap">
            <button type="button" className="profile-trigger" aria-haspopup="menu"
              aria-expanded={avatarOpen}
              aria-label="打开个人菜单"
              onClick={(event) => { event.stopPropagation(); setAvatarOpen((open) => !open); }}>
              <span className="avatar">{avatar.badge ?? avatar.name.slice(0, 1)}</span>
              <span className="profile-trigger-text">
                <strong>{avatar.name}</strong>
                <small>{avatar.role}</small>
              </span>
              <Icon name="chevron-down" size={13} />
            </button>
            {avatarOpen ? (
              <div className="profile-popover" role="menu">
                <div className="profile-popover-heading">
                  <strong>{avatar.name}</strong>
                  <small>{avatar.role}</small>
                </div>
                {avatarItems.map((item) => (
                  <button key={item.label} type="button" role="menuitem"
                    onClick={(event) => { event.stopPropagation(); setAvatarOpen(false); item.onClick?.(); }}>
                    {item.icon ? <Icon name={item.icon} size={14} /> : null}
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      </header>
      <main className="main-content" style={maxWidth ? { maxWidth } : undefined}>
        {children}
      </main>
    </div>
  );
}

export function AppShellRoot({ children }: { children: ReactNode }) {
  return <div className="app-shell">{children}</div>;
}
