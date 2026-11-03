import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, RotateCcw, Trash2 } from 'lucide-react';
import { ApiError, RequestIntent, apiRequestWithMetadata, } from './legacy/api-client';
import { PortalEventClient } from '@edu/event-client';
import { archiveKeys } from './legacy/query-keys';
import { PageHeader, RequestStateView, StatusBadge } from './legacy/ui';
function stateFor(error) {
    if (error instanceof ApiError && error.status === 403)
        return 'forbidden';
    if (error instanceof ApiError && error.status === 409)
        return 'conflict';
    if (error instanceof ApiError && error.status === 412)
        return 'precondition';
    return 'error';
}
function usePlatformArchiveEvents() {
    const queryClient = useQueryClient();
    const [fallbackPolling, setFallbackPolling] = useState(false);
    useEffect(() => {
        let active = true;
        const client = new PortalEventClient({
            onEvent: (event) => {
                if (event.type.startsWith('archive.') || event.type.startsWith('runtime.')) {
                    void queryClient.invalidateQueries({ queryKey: archiveKeys.all });
                }
            },
            onStateChange: (state) => {
                if (active)
                    setFallbackPolling(state === 'backoff' || state === 'polling');
            },
        });
        client.start();
        return () => { active = false; client.stop(); };
    }, [queryClient]);
    return fallbackPolling;
}
export function PlatformInstancesPage() {
    const queryClient = useQueryClient();
    const fallbackPolling = usePlatformArchiveEvents();
    const [error, setError] = useState('');
    const [busyId, setBusyId] = useState('');
    const query = useQuery({
        queryKey: archiveKeys.instances(),
        queryFn: () => apiRequestWithMetadata('/api/v2/platform/instances'),
        refetchInterval: fallbackPolling ? 3000 : false,
    });
    const destroy = async (item) => {
        const reason = window.prompt('请输入异常销毁原因')?.trim();
        if (!reason)
            return;
        setBusyId(item.public_id);
        setError('');
        try {
            await apiRequestWithMetadata(`/api/v2/platform/instances/${encodeURIComponent(item.public_id)}/destroy`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason }), ifMatch: `"${item.row_version}"`, intent: new RequestIntent() });
            await queryClient.invalidateQueries({ queryKey: archiveKeys.instances() });
        }
        catch (cause) {
            setError(cause instanceof ApiError ? cause.payload.error.message : '销毁请求未完成。');
        }
        finally {
            setBusyId('');
        }
    };
    if (query.isPending)
        return _jsx(RequestStateView, { state: "loading" });
    if (query.isError)
        return _jsx(RequestStateView, { state: stateFor(query.error), traceId: query.error instanceof ApiError ? query.error.traceId : undefined, onRetry: () => void query.refetch() });
    const values = query.data.payload.data;
    return _jsxs("section", { className: "workspace-page", children: [_jsx(PageHeader, { eyebrow: "PLATFORM / RUNTIME RECOVERY", title: "\u5B9E\u4F8B\u4E0E\u5B64\u513F\u68C0\u6D4B", actions: _jsxs("button", { className: "text-button", title: "\u5237\u65B0\u5B9E\u4F8B", onClick: () => void query.refetch(), children: [_jsx(RefreshCw, { size: 16, "aria-hidden": "true" }), " \u5237\u65B0"] }) }), error ? _jsx("p", { className: "form-error", role: "alert", children: error }) : null, values.length ? _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u5B9E\u4F8B" }), _jsx("th", { children: "\u4EFB\u52A1 / \u8BFE\u7A0B" }), _jsx("th", { children: "\u6570\u636E\u5E93\u72B6\u6001" }), _jsx("th", { children: "\u5916\u90E8\u72B6\u6001" }), _jsx("th", { children: "\u5F02\u5E38" }), _jsx("th", { children: "\u64CD\u4F5C" })] }) }), _jsx("tbody", { children: values.map((item) => _jsxs("tr", { children: [_jsxs("td", { "data-wrap": true, children: [_jsx("strong", { children: item.public_id }), _jsx("br", {}), _jsx("small", { children: item.external_id || '-' })] }), _jsxs("td", { "data-wrap": true, children: [item.task_id || '外部孤儿', _jsx("br", {}), _jsx("small", { children: item.course_id || '-' })] }), _jsx("td", { children: _jsx(StatusBadge, { status: item.status }) }), _jsx("td", { children: _jsx(StatusBadge, { status: item.external_status }) }), _jsx("td", { children: item.orphan ? '外部孤儿' : item.resource_leak ? '终态资源泄漏' : '-' }), _jsx("td", { children: _jsxs("button", { className: "text-button text-button--danger", disabled: item.orphan || item.status === 'DESTROYED' || busyId === item.public_id, onClick: () => void destroy(item), children: [_jsx(Trash2, { size: 16, "aria-hidden": "true" }), " ", busyId === item.public_id ? '处理中' : '异常销毁'] }) })] }, item.public_id)) })] }) }) : _jsx(RequestStateView, { state: "empty" })] });
}
export function PlatformCompensationsPage() {
    const queryClient = useQueryClient();
    const fallbackPolling = usePlatformArchiveEvents();
    const [status, setStatus] = useState('');
    const [error, setError] = useState('');
    const [busyId, setBusyId] = useState('');
    const query = useQuery({
        queryKey: archiveKeys.compensations(status),
        queryFn: () => apiRequestWithMetadata(`/api/v2/platform/compensations${status ? `?status=${status}` : ''}`),
        refetchInterval: fallbackPolling ? 3000 : false,
    });
    const retry = async (item) => {
        const reason = window.prompt('请输入人工重试原因')?.trim();
        if (!reason)
            return;
        setBusyId(item.public_id);
        setError('');
        try {
            await apiRequestWithMetadata('/api/v2/platform/compensations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ compensation_id: item.public_id, reason }), ifMatch: `"${item.row_version}"`, intent: new RequestIntent() });
            await queryClient.invalidateQueries({ queryKey: archiveKeys.all });
        }
        catch (cause) {
            setError(cause instanceof ApiError ? cause.payload.error.message : '补偿重试请求未完成。');
        }
        finally {
            setBusyId('');
        }
    };
    if (query.isPending)
        return _jsx(RequestStateView, { state: "loading" });
    if (query.isError)
        return _jsx(RequestStateView, { state: stateFor(query.error), traceId: query.error instanceof ApiError ? query.error.traceId : undefined, onRetry: () => void query.refetch() });
    const values = query.data.payload.data;
    return _jsxs("section", { className: "workspace-page", children: [_jsx(PageHeader, { eyebrow: "PLATFORM / COMPENSATIONS", title: "\u5F52\u6863\u4E0E\u56DE\u6536\u8865\u507F", actions: _jsxs("button", { className: "text-button", title: "\u5237\u65B0\u8865\u507F", onClick: () => void query.refetch(), children: [_jsx(RefreshCw, { size: 16, "aria-hidden": "true" }), " \u5237\u65B0"] }) }), _jsxs("label", { className: "field", children: [_jsx("span", { children: "\u8865\u507F\u72B6\u6001" }), _jsxs("select", { value: status, onChange: (event) => setStatus(event.target.value), children: [_jsx("option", { value: "", children: "\u5168\u90E8" }), _jsx("option", { value: "RETRY", children: "\u7B49\u5F85\u91CD\u8BD5" }), _jsx("option", { value: "DEAD", children: "\u5DF2\u8017\u5C3D" })] })] }), error ? _jsx("p", { className: "form-error", role: "alert", children: error }) : null, values.length ? _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u8865\u507F" }), _jsx("th", { children: "\u5BF9\u8C61" }), _jsx("th", { children: "\u72B6\u6001" }), _jsx("th", { children: "\u5C1D\u8BD5" }), _jsx("th", { children: "\u5931\u8D25" }), _jsx("th", { children: "Trace" }), _jsx("th", { children: "\u64CD\u4F5C" })] }) }), _jsx("tbody", { children: values.map((item) => _jsxs("tr", { children: [_jsxs("td", { "data-wrap": true, children: [item.task_type, _jsx("br", {}), _jsx("small", { children: item.public_id })] }), _jsxs("td", { "data-wrap": true, children: [item.subject_type, _jsx("br", {}), _jsx("small", { children: item.subject_ref })] }), _jsx("td", { children: _jsx(StatusBadge, { status: item.status }) }), _jsxs("td", { children: [item.attempt_count, " / ", item.max_attempts] }), _jsx("td", { children: item.error_code || '-' }), _jsx("td", { className: "digest", children: item.trace_id }), _jsx("td", { children: _jsxs("button", { className: "text-button", disabled: !['RETRY', 'DEAD'].includes(item.status) || busyId === item.public_id, onClick: () => void retry(item), children: [_jsx(RotateCcw, { size: 16, "aria-hidden": "true" }), " ", busyId === item.public_id ? '处理中' : '人工重试'] }) })] }, item.public_id)) })] }) }) : _jsx(RequestStateView, { state: "empty" })] });
}
