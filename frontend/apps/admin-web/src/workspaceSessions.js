import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQuery } from '@tanstack/react-query';
import { ApiError, apiRequestWithMetadata } from './legacy/api-client';
import { workspaceKeys } from './legacy/query-keys';
import { PageHeader, RequestStateView, StatusBadge } from './legacy/ui';
export function WorkspaceSessionsPage() {
    const query = useQuery({ queryKey: workspaceKeys.adminSessions(), queryFn: () => apiRequestWithMetadata('/api/v2/platform/workspaces/sessions') });
    if (query.isPending)
        return _jsx(RequestStateView, { state: "loading" });
    if (query.isError)
        return _jsx(RequestStateView, { state: query.error instanceof ApiError && query.error.status === 403 ? 'forbidden' : 'error', message: "\u5DE5\u4F5C\u533A\u4F1A\u8BDD\u6458\u8981\u6682\u65F6\u4E0D\u53EF\u7528\u3002", onRetry: () => void query.refetch() });
    const items = query.data?.payload.data ?? [];
    return _jsxs("section", { className: "workspace-page", children: [_jsx(PageHeader, { eyebrow: "PLATFORM / WORKSPACES", title: "\u5DE5\u4F5C\u533A\u4F1A\u8BDD\u6458\u8981", description: "\u4EC5\u663E\u793A\u72B6\u6001\u3001\u8FC7\u671F\u3001\u64A4\u9500\u548C\u7248\u672C\u6458\u8981\uFF1B\u4E0D\u63D0\u4F9B\u8FDB\u5165\u5B66\u751F\u5DE5\u4F5C\u533A\u6216\u7B7E\u53D1\u7968\u636E\u7684\u5165\u53E3\u3002" }), _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u4F1A\u8BDD" }), _jsx("th", { children: "\u4EFB\u52A1 / \u5B66\u751F" }), _jsx("th", { children: "\u72B6\u6001" }), _jsx("th", { children: "\u8FC7\u671F" }), _jsx("th", { children: "\u7248\u672C" })] }) }), _jsx("tbody", { children: items.map((item) => _jsxs("tr", { children: [_jsx("td", { children: item.public_id }), _jsxs("td", { children: [item.task_id, _jsx("br", {}), _jsx("small", { children: item.student_id })] }), _jsx("td", { children: _jsx(StatusBadge, { status: item.status }) }), _jsx("td", { children: new Date(item.expires_at).toLocaleString() }), _jsx("td", { children: item.current_version })] }, item.public_id)) })] }) }), items.length === 0 ? _jsx(RequestStateView, { state: "empty" }) : null] });
}
