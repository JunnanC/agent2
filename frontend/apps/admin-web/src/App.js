import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useSession } from './app/session';
import { DetailDrawer } from './components';
import { pages } from './data';
import { ModulePage } from './pages';
import { Home as LiveOverview } from './pages/home';
import { Governance as LiveGovernance } from './pages/governance';
import { Resources as LiveResources } from './pages/resources';
import { Images as LiveImages } from './pages/images';
import { Incidents as LiveIncidents } from './pages/incidents';
import { Audit as LiveAudit } from './pages/audit';
import { AdminsPage, CoursesPage, QuotasPage, ResourceProfilesPage, RuntimesPage, SecurityPage, TeachersPage, UsersPage, VerificationsPage, } from './apiPages';
import { PrecheckSummaryPage } from './templatePrechecks';
import { ExperimentAnomaliesPage } from './experimentAnomalies';
import { WorkspaceSessionsPage } from './workspaceSessions';
import { ReportScanAnomaliesPage } from './reportScanAnomalies';
import { ReviewMonitorPage } from './reviewMonitor';
import { PlatformCompensationsPage, PlatformInstancesPage } from './instancesAndCompensations';
import { AgentPoliciesPage } from './agentPolicies';
import { OperationsIntegrationsPage } from './operationsIntegrations';
const apiPages = new Set([
    'users', 'teachers', 'admins', 'verifications', 'courses', 'runtimes', 'images',
    'resourceProfiles', 'quotas', 'security', 'experimentAnomalies', 'workspaceSessions',
    'instances', 'compensations', 'templatePrechecks', 'reportScanAnomalies',
    'reviewMonitor', 'agentPolicies', 'operations',
]);
function pageFromHash() {
    const key = window.location.hash.slice(1);
    return Object.hasOwn(pages, key) ? key : 'overview';
}
export default function App() {
    const session = useSession();
    const queryClient = useQueryClient();
    const [page, setPage] = useState(pageFromHash);
    const [menuOpen, setMenuOpen] = useState(false);
    const [detail, setDetail] = useState(null);
    const [toast, setToast] = useState('');
    useEffect(() => {
        const onHashChange = () => { setPage(pageFromHash()); setMenuOpen(false); setDetail(null); };
        window.addEventListener('hashchange', onHashChange);
        return () => window.removeEventListener('hashchange', onHashChange);
    }, []);
    useEffect(() => {
        if (!toast)
            return;
        const timer = setTimeout(() => setToast(''), 2300);
        return () => clearTimeout(timer);
    }, [toast]);
    useEffect(() => { document.title = `${pages[page].title} · Edu Agent Platform`; }, [page]);
    function navigate(next) {
        window.location.hash = next;
        setPage(next);
        setMenuOpen(false);
        setDetail(null);
    }
    const navItem = (key, glyph) => _jsxs("button", { className: page === key ? 'active' : '', "aria-current": page === key ? 'page' : undefined, onClick: () => navigate(key), children: [_jsx("span", { className: "nav-icon", "aria-hidden": "true", children: glyph }), pages[key].title] }, key);
    const navGroups = [
        ['总览', [['overview', '▦']]],
        ['账号与教学', [['users', '◎'], ['teachers', '♢'], ['admins', '♢'], ['verifications', '✓'], ['courses', '▤']]],
        ['实验运行', [['experimentAnomalies', '△'], ['workspaceSessions', '⌗'], ['instances', '◫'], ['compensations', '↻']]],
        ['资源治理', [['runtimes', '◈'], ['images', '▧'], ['resourceProfiles', '▥'], ['quotas', '▤'], ['security', '⌑']]],
        ['质量与智能', [['templatePrechecks', '◇'], ['reportScanAnomalies', '△'], ['reviewMonitor', '≡'], ['agentPolicies', '✦']]],
        ['运维与集成', [['operations', '◌'], ['governance', '⌑'], ['resources', '▤'], ['incidents', '△'], ['audit', '≡']]],
    ];
    const content = page === 'overview' ? _jsx(LiveOverview, {}) : page === 'governance' ? _jsx(LiveGovernance, {}) : page === 'resources' ? _jsx(LiveResources, {}) : page === 'incidents' ? _jsx(LiveIncidents, {}) : page === 'audit' ? _jsx(LiveAudit, {}) : apiPages.has(page) ? _jsx(ApiPage, { page: page }) : _jsx(ModulePage, { page: page, onDetail: setDetail });
    return _jsxs("div", { className: "app", children: [_jsx("a", { href: "#main-content", className: "skip-link", onClick: event => { event.preventDefault(); document.getElementById('main-content')?.focus(); }, children: "\u8DF3\u5230\u4E3B\u8981\u5185\u5BB9" }), menuOpen && _jsx("button", { className: "nav-backdrop", "aria-label": "\u5173\u95ED\u7BA1\u7406\u5BFC\u822A", onClick: () => setMenuOpen(false) }), _jsxs("aside", { id: "management-navigation", className: `sidebar ${menuOpen ? 'is-open' : ''}`, "aria-label": "\u5E73\u53F0\u7BA1\u7406\u5BFC\u822A", children: [_jsxs("div", { className: "brand", children: [_jsx("span", { className: "brand-mark", children: "E" }), _jsxs("span", { className: "brand-copy", children: [_jsx("strong", { children: "Edu Agent Platform" }), _jsx("small", { children: "\u5E73\u53F0\u7BA1\u7406\u63A7\u5236\u53F0" })] })] }), navGroups.map(([label, items]) => _jsxs("div", { children: [_jsx("div", { className: "nav-label", children: label }), _jsx("nav", { className: "nav", "aria-label": label, children: items.map(([key, glyph]) => navItem(key, glyph)) })] }, label)), _jsxs("div", { className: "sidebar-bottom", children: [_jsxs("div", { className: "environment", children: [_jsx("span", { className: "dot" }), "\u670D\u52A1\u5065\u5EB7\u4E3A\u6F14\u793A\u72B6\u6001"] }), _jsxs("div", { className: "operator", children: [_jsx("span", { className: "avatar", children: "\u7BA1" }), _jsxs("span", { children: [_jsx("span", { className: "operator-name", children: "\u5E73\u53F0\u7BA1\u7406\u5458" }), _jsx("span", { className: "operator-role", children: "\u5E73\u53F0\u8FD0\u7EF4\u4E0E\u6CBB\u7406" })] })] })] })] }), _jsxs("main", { className: "main", id: "main-content", tabIndex: -1, children: [_jsxs("header", { className: "topbar", children: [_jsxs("div", { className: "top-left", children: [_jsx("button", { className: "icon-button mobile-nav", "aria-label": menuOpen ? '关闭管理导航' : '打开管理导航', "aria-expanded": menuOpen, "aria-controls": "management-navigation", onClick: () => setMenuOpen(!menuOpen), children: "\u2630" }), _jsx("span", { className: "top-parent", children: "\u5E73\u53F0\u7BA1\u7406" }), _jsx("span", { className: "crumb-sep", children: "/" }), _jsx("strong", { children: pages[page].title })] }), _jsxs("div", { className: "top-actions", children: [_jsx("span", { className: "demo-tag", children: apiPages.has(page) || ['overview', 'governance', 'resources', 'incidents', 'audit'].includes(page) ? '实时接口' : '演示数据' }), session.me ? _jsx("button", { className: "btn", onClick: () => void session.logout().finally(() => queryClient.clear()), children: "\u9000\u51FA" }) : null, _jsx("button", { className: "icon-button", "aria-label": "\u5E2E\u52A9", onClick: () => setToast(apiPages.has(page) || ['overview', 'governance', 'resources', 'incidents', 'audit'].includes(page) ? '此模块读取管理端服务接口' : '此模块使用本地演示数据'), children: "?" }), _jsx("span", { className: "top-avatar", children: session.me?.display_name?.slice(0, 1) ?? '管' })] })] }), _jsxs("div", { className: "content", children: [_jsxs("div", { className: "page-head", children: [_jsxs("div", { children: [_jsxs("div", { className: "eyebrow", children: [pages[page].eyebrow, _jsx("span", { className: "crumb-sep", children: "/" }), "\u5E73\u53F0\u7BA1\u7406"] }), _jsx("h1", { children: pages[page].title }), _jsx("p", { children: pages[page].description })] }), _jsxs("div", { className: "head-actions", children: [!apiPages.has(page) && _jsx("span", { className: "demo-tag", children: "\u754C\u9762\u6F14\u793A" }), page === 'overview' && _jsx("button", { className: "btn", onClick: () => navigate('audit'), children: "\u67E5\u770B\u5BA1\u8BA1\u8BB0\u5F55 \u2192" })] })] }), _jsx("div", { children: content }, page)] })] }), detail && _jsx(DetailDrawer, { detail: detail, onClose: () => setDetail(null) }), _jsx("div", { className: `toast ${toast ? 'show' : ''}`, role: "status", children: toast })] });
}
function ApiPage({ page }) {
    switch (page) {
        case 'users': return _jsx(UsersPage, {});
        case 'teachers': return _jsx(TeachersPage, {});
        case 'admins': return _jsx(AdminsPage, {});
        case 'verifications': return _jsx(VerificationsPage, {});
        case 'courses': return _jsx(CoursesPage, {});
        case 'runtimes': return _jsx(RuntimesPage, {});
        case 'images': return _jsx(LiveImages, {});
        case 'resourceProfiles': return _jsx(ResourceProfilesPage, {});
        case 'quotas': return _jsx(QuotasPage, {});
        case 'security': return _jsx(SecurityPage, {});
        case 'experimentAnomalies': return _jsx(ExperimentAnomaliesPage, {});
        case 'workspaceSessions': return _jsx(WorkspaceSessionsPage, {});
        case 'instances': return _jsx(PlatformInstancesPage, {});
        case 'compensations': return _jsx(PlatformCompensationsPage, {});
        case 'templatePrechecks': return _jsx(PrecheckSummaryPage, {});
        case 'reportScanAnomalies': return _jsx(ReportScanAnomaliesPage, {});
        case 'reviewMonitor': return _jsx(ReviewMonitorPage, {});
        case 'agentPolicies': return _jsx(AgentPoliciesPage, {});
        case 'operations': return _jsx(OperationsIntegrationsPage, {});
        default: return null;
    }
}
