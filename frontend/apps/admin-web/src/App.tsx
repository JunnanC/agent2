import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError } from '@edu/api-client';
import { useSession } from '@edu/auth-client';
import { LoginForm, RequestStateView } from '@edu/ui';
import { DetailDrawer, type Detail } from './components';
import { pages, type Page } from './data';
import { Audit, Governance, Incidents, ModulePage, Overview, Resources } from './pages';
import {
  AdminsPage,
  CoursesPage,
  ImagesPage,
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
  const navItem = (key: Page, glyph: string) => <button key={key} className={page === key ? 'active' : ''} aria-current={page === key ? 'page' : undefined} onClick={() => navigate(key)}><span className="nav-icon" aria-hidden="true">{glyph}</span>{pages[key].title}</button>;
  const navGroups: Array<[string, Array<[Page, string]>]> = [
    ['总览', [['overview', '▦']]],
    ['账号与教学', [['users', '◎'], ['teachers', '♢'], ['admins', '♢'], ['verifications', '✓'], ['courses', '▤']]],
    ['实验运行', [['experimentAnomalies', '△'], ['workspaceSessions', '⌗'], ['instances', '◫'], ['compensations', '↻']]],
    ['资源治理', [['runtimes', '◈'], ['images', '▧'], ['resourceProfiles', '▥'], ['quotas', '▤'], ['security', '⌑']]],
    ['质量与智能', [['templatePrechecks', '◇'], ['reportScanAnomalies', '△'], ['reviewMonitor', '≡'], ['agentPolicies', '✦']]],
    ['运维与集成', [['operations', '◌'], ['governance', '⌑'], ['resources', '▤'], ['incidents', '△'], ['audit', '≡']]],
  ];
  const content = page === 'overview' ? <Overview navigate={navigate} /> : page === 'governance' ? <Governance onDetail={setDetail} /> : page === 'resources' ? <Resources onDetail={setDetail} /> : page === 'incidents' ? <Incidents onDetail={setDetail} /> : page === 'audit' ? <Audit onDetail={setDetail} /> : apiPages.has(page) ? <ApiPage page={page} session={session} /> : <ModulePage page={page} onDetail={setDetail} />;
  return <div className="app">
    <a href="#main-content" className="skip-link" onClick={event => { event.preventDefault(); document.getElementById('main-content')?.focus(); }}>跳到主要内容</a>
    {menuOpen && <button className="nav-backdrop" aria-label="关闭管理导航" onClick={() => setMenuOpen(false)} />}
    <aside id="management-navigation" className={`sidebar ${menuOpen ? 'is-open' : ''}`} aria-label="平台管理导航">
      <div className="brand"><span className="brand-mark">E</span><span className="brand-copy"><strong>Edu Agent Platform</strong><small>平台管理控制台</small></span></div>
      {navGroups.map(([label, items]) => <div key={label}><div className="nav-label">{label}</div><nav className="nav" aria-label={label}>{items.map(([key, glyph]) => navItem(key, glyph))}</nav></div>)}
      <div className="sidebar-bottom"><div className="environment"><span className="dot" />服务健康为演示状态</div><div className="operator"><span className="avatar">管</span><span><span className="operator-name">平台管理员</span><span className="operator-role">平台运维与治理</span></span></div></div>
    </aside>
    <main className="main" id="main-content" tabIndex={-1}>
      <header className="topbar"><div className="top-left"><button className="icon-button mobile-nav" aria-label={menuOpen ? '关闭管理导航' : '打开管理导航'} aria-expanded={menuOpen} aria-controls="management-navigation" onClick={() => setMenuOpen(!menuOpen)}>☰</button><span className="top-parent">平台管理</span><span className="crumb-sep">/</span><strong>{pages[page].title}</strong></div><div className="top-actions"><span className="demo-tag">{apiPages.has(page) ? session.status === 'authenticated' ? '实时接口' : session.status === 'denied' ? '权限不足' : session.status === 'error' ? '认证服务异常' : session.status === 'loading' ? '检查会话' : '需管理员登录' : '演示数据'}</span>{session.status === 'authenticated' ? <button className="btn" onClick={() => void session.signOut().finally(() => queryClient.clear())}>退出</button> : null}<button className="icon-button" aria-label="帮助" onClick={() => setToast(apiPages.has(page) ? '此模块读取管理端服务接口' : '此模块使用本地演示数据')}>?</button><span className="top-avatar">{session.me?.display_name?.slice(0, 1) ?? '管'}</span></div></header>
      <div className="content"><div className="page-head"><div><div className="eyebrow">{pages[page].eyebrow}<span className="crumb-sep">/</span>平台管理</div><h1>{pages[page].title}</h1><p>{pages[page].description}</p></div><div className="head-actions">{!apiPages.has(page) && <span className="demo-tag">界面演示</span>}{page === 'overview' && <button className="btn" onClick={() => navigate('audit')}>查看审计记录 →</button>}</div></div>
        <div key={page}>{content}</div>
      </div>
    </main>
    {detail && <DetailDrawer detail={detail} onClose={() => setDetail(null)} />}
    <div className={`toast ${toast ? 'show' : ''}`} role="status">{toast}</div>
  </div>;
}

function ApiPage({ page, session }: { page: Page; session: ReturnType<typeof useSession> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (session.status === 'loading') return <RequestStateView state="loading" />;
  if (session.status === 'anonymous') {
    const signIn = async (identifier: string, password: string) => {
      setBusy(true); setError('');
      try { await session.signIn({ identifier, password }); }
      catch (cause) { setError(cause instanceof ApiError ? cause.payload.error.message : '登录请求未完成。'); }
      finally { setBusy(false); }
    };
    return <LoginForm title="平台管理端" busy={busy} error={error} onSubmit={signIn} />;
  }
  if (session.status === 'denied') return <RequestStateView state="forbidden" title="需要平台管理员资格" />;
  if (session.status === 'error') return <RequestStateView state="error" onRetry={() => void session.refresh()} />;
  switch (page) {
    case 'users': return <UsersPage />;
    case 'teachers': return <TeachersPage />;
    case 'admins': return <AdminsPage />;
    case 'verifications': return <VerificationsPage />;
    case 'courses': return <CoursesPage />;
    case 'runtimes': return <RuntimesPage />;
    case 'images': return <ImagesPage />;
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
