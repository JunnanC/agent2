import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQuery } from '@tanstack/react-query';
import { ApiError, apiRequestWithMetadata } from './legacy/api-client';
import { reviewKeys } from './legacy/query-keys';
import { PageHeader, RequestStateView, StatusBadge } from './legacy/ui';
export function ReviewMonitorPage() {
    const query = useQuery({
        queryKey: reviewKeys.monitor(),
        queryFn: () => apiRequestWithMetadata('/api/v2/platform/reviews/summary'),
        refetchInterval: 10000,
    });
    if (query.isPending)
        return _jsx(RequestStateView, { state: "loading" });
    if (query.isError)
        return _jsx(RequestStateView, { state: query.error instanceof ApiError && query.error.status === 403 ? 'forbidden' : 'error', traceId: query.error instanceof ApiError ? query.error.traceId : undefined, onRetry: () => void query.refetch() });
    const summary = query.data.payload.data;
    return _jsxs("section", { className: "workspace-page", children: [_jsx(PageHeader, { eyebrow: "PLATFORM / REVIEW GOVERNANCE", title: "\u5BA1\u6838\u76D1\u7BA1" }), _jsxs("div", { className: "summary-grid", children: [_jsxs("div", { className: "summary-item", children: [_jsx("span", { children: "\u5F85\u5904\u7406" }), _jsx("strong", { children: (summary.review_counts.PENDING ?? 0) + (summary.review_counts.IN_REVIEW ?? 0) })] }), _jsxs("div", { className: "summary-item", children: [_jsx("span", { children: "\u5DF2\u51B3\u5B9A" }), _jsx("strong", { children: summary.review_counts.DECIDED ?? 0 })] }), _jsxs("div", { className: "summary-item", children: [_jsx("span", { children: "\u81EA\u52A8\u68C0\u67E5\u5931\u8D25" }), _jsx("strong", { children: summary.auto_check_failures })] })] }), _jsxs("section", { className: "section-block", children: [_jsx("h2", { children: "\u76F8\u4F3C\u5EA6\u8FD0\u884C" }), Object.keys(summary.similarity_counts).length ? _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u72B6\u6001" }), _jsx("th", { children: "\u8FD0\u884C\u6570" })] }) }), _jsx("tbody", { children: Object.entries(summary.similarity_counts).map(([status, count]) => _jsxs("tr", { children: [_jsx("td", { children: _jsx(StatusBadge, { status: status }) }), _jsx("td", { children: count })] }, status)) })] }) }) : _jsx(RequestStateView, { state: "empty" })] }), _jsxs("section", { className: "section-block", children: [_jsx("h2", { children: "\u6700\u8FD1 Trace" }), _jsx("p", { className: "digest", children: summary.latest_trace_id || '-' })] })] });
}
