import { useEffect, useState } from 'react';
import { Icon } from '@edu/ui';
import { useQueryClient } from '@tanstack/react-query';
import { useSession } from './app/session';
import { DetailDrawer, type Detail } from './components';
import { pages, type Page } from './data';
import { ModulePage } from './pages';
import { Home as LiveOverview } from './pages/home';
import { Governance as LiveGovernance } from './pages/governance';
import { Resources as LiveResources } from './pages/resources';
import { Images as LiveImages } from './pages/images';
import { Incidents as LiveIncidents } from './pages/incidents';
import { Audit as LiveAudit } from './pages/audit';
import {
  AdminsPage,
  CoursesPage,
  QuotasPage,
  ResourceProfilesPage,
  RuntimesPage,
  SecurityPage,
  TeachersPage,
  UsersPage,
  VerificationsPage,
} from './apiPages';
import { PrecheckSummaryPage } from './templatePrechecks';
import { ExperimentAnomaliesPage } from './experimentAnomalies';
import { WorkspaceSessionsPage } from './workspaceSessions';
import { ReportScanAnomaliesPage } from './reportScanAnomalies';
import { ReviewMonitorPage } from './reviewMonitor';
import { PlatformCompensationsPage, PlatformInstancesPage } from './instancesAndCompensations';
import { AgentPoliciesPage } from './agentPolicies';
import { OperationsIntegrationsPage } from './operationsIntegrations';

const apiPages = new Set<Page>([
  'users', 'teachers', 'admins', 'verifications', 'courses', 'runtimes', 'images',
  'resourceProfiles', 'quotas', 'security', 'experimentAnomalies', 'workspaceSessions',
  'instances', 'compensations', 'templatePrechecks', 'reportScanAnomalies',
  'reviewMonitor', 'agentPolicies', 'operations',
]);

function pageFromHash(): Page {
  const key = window.location.hash.slice(1);
  return Object.hasOwn(pages, key) ? key as Page : 'overview';
}

export default function App() {
  const session = useSession();
  const queryClient = useQueryClient();
  const [page, setPage] = useState<Page>(pageFromHash);
  const [menuOpen, setMenuOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem('edu.admin.sidebar-collapsed') === 'true'; }
    catch { return false; }
  });
  function toggleSidebar() {
    setCollapsed(value => {
      const next = !value;
      try { localStorage.setItem('edu.admin.sidebar-collapsed', String(next)); } catch { /* Storage is optional. */ }
      return next;
    });
  }
  const [detail, setDetail] = useState<Detail | null>(null);
  const [toast, setToast] = useState('');
  useEffect(() => {
    const onHashChange = () => { setPage(pageFromHash()); setMenuOpen(false); setDetail(null); };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(''), 2300);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => { document.title = `${pages[page].title} · Edu Agent Platform`; }, [page]);
  function navigate(next: Page) {
    window.location.hash = next;
    setPage(next);
    setMenuOpen(false);
    setDetail(null);
  }
  const navItem = (key: Page, glyph: string) => <button key={key} className={page === key ? 'active' : ''} aria-current={page === key ? 'page' : undefined} aria-label={pages[key].title} title={pages[key].title} onClick={() => navigate(key)}><span className="nav-icon" aria-hidden="true">{glyph}</span><span className="nav-item-label">{pages[key].title}</span></button>;
  const navGroups: Array<[string, Array<[Page, string]>]> = [
    ['总览', [['overview', '▦']]],
    ['账号与教学', [['users', '◎'], ['teachers', '♢'], ['admins', '♢'], ['verifications', '✓'], ['courses', '▤']]],
    ['实验运行', [['experimentAnomalies', '△'], ['workspaceSessions', '⌗'], ['instances', '◫'], ['compensations', '↻']]],
    ['资源治理', [['runtimes', '◈'], ['images', '▧'], ['resourceProfiles', '▥'], ['quotas', '▤'], ['security', '⌑']]],
    ['质量与智能', [['templatePrechecks', '◇'], ['reportScanAnomalies', '△'], ['reviewMonitor', '≡'], ['agentPolicies', '✦']]],
    ['运维与集成', [['operations', '◌'], ['governance', '⌑'], ['resources', '▤'], ['incidents', '△'], ['audit', '≡']]],
  ];
  const content = page === 'overview' ? <LiveOverview /> : page === 'governance' ? <LiveGovernance /> : page === 'resources' ? <LiveResources /> : page === 'incidents' ? <LiveIncidents /> : page === 'audit' ? <LiveAudit /> : apiPages.has(page) ? <ApiPage page={page} /> : <ModulePage page={page} onDetail={setDetail} />;
  return <div className={`app ${collapsed ? 'sidebar-collapsed' : ''}`}>
    <a href="#main-content" className="skip-link" onClick={event => { event.preventDefault(); document.getElementById('main-content')?.focus(); }}>跳到主要内容</a>
    {menuOpen && <button className="nav-backdrop" aria-label="关闭管理导航" onClick={() => setMenuOpen(false)} />}
    <aside id="management-navigation" className={`sidebar ${menuOpen ? 'is-open' : ''}`} aria-label="平台管理导航">
      <div className="brand">{collapsed ? <button type="button" className="brand-mark brand-expand" aria-label="展开导航" title="展开导航" aria-expanded={false} aria-controls="management-navigation" onClick={toggleSidebar}><Icon name="layers" size={18} /></button> : <span className="brand-mark" aria-hidden="true"><Icon name="layers" size={18} /></span>}<span className="brand-copy"><strong>教学云实验平台</strong><small>平台管理控制台</small></span></div>
      {!collapsed && <button type="button" className="sidebar-toggle" aria-label="收起导航" aria-expanded={true} aria-controls="management-navigation" onClick={toggleSidebar}><Icon name="chevron-left" size={18} />收起导航</button>}
      <div className="sidebar-navigation">
      {navGroups.map(([label, items]) => <div key={label}><div className="nav-label">{label}</div><nav className="nav" aria-label={label}>{items.map(([key, glyph]) => navItem(key, glyph))}</nav></div>)}
      </div>
      <div className="sidebar-bottom"><div className="environment"><span className="dot" />服务健康为演示状态</div><div className="operator"><span className="avatar">{(session.me?.display_name || session.me?.username || "管").slice(0, 1)}</span><span className="operator-copy"><span className="operator-name">{session.me?.display_name || session.me?.username || "平台管理员"}</span><span className="operator-role">平台运维与治理</span></span></div></div>
    </aside>
    <main className="main" id="main-content" tabIndex={-1}>
      <header className="topbar"><div className="top-left"><button className="icon-button mobile-nav" aria-label={menuOpen ? '关闭管理导航' : '打开管理导航'} aria-expanded={menuOpen} aria-controls="management-navigation" onClick={() => setMenuOpen(!menuOpen)}>☰</button><span className="top-parent">平台管理</span><span className="crumb-sep">/</span><strong>{pages[page].title}</strong></div><div className="top-actions"><span className="demo-tag">{apiPages.has(page) || ['overview', 'governance', 'resources', 'incidents', 'audit'].includes(page) ? '实时接口' : '演示数据'}</span>{session.me ? <button className="btn" onClick={() => void session.logout().finally(() => queryClient.clear())}>退出</button> : null}<button className="icon-button" aria-label="帮助" onClick={() => setToast(apiPages.has(page) || ['overview', 'governance', 'resources', 'incidents', 'audit'].includes(page) ? '此模块读取管理端服务接口' : '此模块使用本地演示数据')}>?</button></div></header>
      <div className="content"><div className="page-head"><div><div className="eyebrow">{pages[page].eyebrow}<span className="crumb-sep">/</span>平台管理</div><h1>{pages[page].title}</h1><p>{pages[page].description}</p></div><div className="head-actions">{!apiPages.has(page) && <span className="demo-tag">界面演示</span>}{page === 'overview' && <button className="btn" onClick={() => navigate('audit')}>查看审计记录 →</button>}</div></div>
        <div key={page}>{content}</div>
      </div>
    </main>
    {detail && <DetailDrawer detail={detail} onClose={() => setDetail(null)} />}
    <div className={`toast ${toast ? 'show' : ''}`} role="status">{toast}</div>
  </div>;
}

function ApiPage({ page }: { page: Page }) {
  switch (page) {
    case 'users': return <UsersPage />;
    case 'teachers': return <TeachersPage />;
    case 'admins': return <AdminsPage />;
    case 'verifications': return <VerificationsPage />;
    case 'courses': return <CoursesPage />;
    case 'runtimes': return <RuntimesPage />;
    case 'images': return <LiveImages />;
    case 'resourceProfiles': return <ResourceProfilesPage />;
    case 'quotas': return <QuotasPage />;
    case 'security': return <SecurityPage />;
    case 'experimentAnomalies': return <ExperimentAnomaliesPage />;
    case 'workspaceSessions': return <WorkspaceSessionsPage />;
    case 'instances': return <PlatformInstancesPage />;
    case 'compensations': return <PlatformCompensationsPage />;
    case 'templatePrechecks': return <PrecheckSummaryPage />;
    case 'reportScanAnomalies': return <ReportScanAnomaliesPage />;
    case 'reviewMonitor': return <ReviewMonitorPage />;
    case 'agentPolicies': return <AgentPoliciesPage />;
    case 'operations': return <OperationsIntegrationsPage />;
    default: return null;
  }
}
