import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQuery } from '@tanstack/react-query';
import { ApiError, apiRequestWithMetadata } from './legacy/api-client';
import { reportKeys } from './legacy/query-keys';
import { PageHeader, RequestStateView, StatusBadge } from './legacy/ui';
export function ReportScanAnomaliesPage() {
    const query = useQuery({
        queryKey: reportKeys.scanAnomalies(),
        queryFn: () => apiRequestWithMetadata('/api/v2/platform/reports/scan-anomalies'),
    });
    if (query.isPending)
        return _jsx(RequestStateView, { state: "loading" });
    if (query.isError)
        return _jsx(RequestStateView, { state: query.error instanceof ApiError && query.error.status === 403 ? 'forbidden' : 'error', message: "\u626B\u63CF\u6458\u8981\u6682\u65F6\u4E0D\u53EF\u7528\u3002", onRetry: () => void query.refetch() });
    const data = query.data?.payload.data;
    const counts = data?.counts ?? {};
    return _jsxs("section", { className: "workspace-page", children: [_jsx(PageHeader, { eyebrow: "PLATFORM / REPORT ASSETS", title: "\u9644\u4EF6\u626B\u63CF\u5F02\u5E38" }), _jsx("div", { className: "summary-grid", children: Object.entries(counts).map(([status, count]) => _jsxs("div", { className: "summary-item", children: [_jsx("span", { children: _jsx(StatusBadge, { status: status }) }), _jsx("strong", { children: count })] }, status)) }), data?.items.length ? _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u8D44\u4EA7" }), _jsx("th", { children: "\u4EFB\u52A1" }), _jsx("th", { children: "\u626B\u63CF" }), _jsx("th", { children: "\u9519\u8BEF\u4EE3\u7801" }), _jsx("th", { children: "\u65F6\u95F4" })] }) }), _jsx("tbody", { children: data.items.map((item) => _jsxs("tr", { children: [_jsx("td", { children: item.asset_id }), _jsx("td", { children: item.task_id }), _jsx("td", { children: _jsx(StatusBadge, { status: item.scan_status }) }), _jsx("td", { children: item.failure_code || '-' }), _jsx("td", { children: new Date(item.created_at).toLocaleString() })] }, item.asset_id)) })] }) }) : _jsx(RequestStateView, { state: "empty" })] });
}
