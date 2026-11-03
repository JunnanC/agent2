import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ApiError, RequestIntent, apiRequestWithMetadata } from './legacy/api-client';
import { agentKeys } from './legacy/query-keys';
import { PageHeader, RequestStateView, StatusBadge, TextField } from './legacy/ui';
function message(error) { return error instanceof ApiError ? `${error.payload.error.message}（trace: ${error.traceId || 'n/a'}）` : '平台 Agent 请求未完成。'; }
function useList(path, key) { return useQuery({ queryKey: key, queryFn: () => apiRequestWithMetadata(path) }); }
export function AgentPoliciesPage() {
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');
    const [policyForm, setPolicyForm] = useState(false);
    const [routeForm, setRouteForm] = useState(false);
    const policies = useList('/api/v2/platform/agent/tool-policies', agentKeys.platformPolicies());
    const routes = useList('/api/v2/platform/agent/model-routes', [...agentKeys.all, 'platform', 'routes']);
    const suites = useList('/api/v2/platform/agent/eval-suites', [...agentKeys.all, 'platform', 'eval-suites']);
    const usage = useQuery({ queryKey: [...agentKeys.all, 'platform', 'usage'], queryFn: () => apiRequestWithMetadata('/api/v2/platform/agent/usage-costs') });
    const createPolicy = async (event) => {
        event.preventDefault();
        setError('');
        const form = new FormData(event.currentTarget);
        try {
            await apiRequestWithMetadata('/api/v2/platform/agent/tool-policies', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: form.get('key'), tool_name: form.get('tool_name'), risk: form.get('risk'), timeout_seconds: Number(form.get('timeout_seconds')), output_limit: Number(form.get('output_limit')), allowlist: [String(form.get('tool_name'))] }), intent: new RequestIntent() });
            setNotice('平台工具策略已创建新版本。');
            setPolicyForm(false);
            await policies.refetch();
        }
        catch (cause) {
            setError(message(cause));
        }
    };
    const createRoute = async (event) => {
        event.preventDefault();
        setError('');
        const form = new FormData(event.currentTarget);
        try {
            await apiRequestWithMetadata('/api/v2/platform/agent/model-routes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: form.get('key'), provider: form.get('provider'), model_name: form.get('model_name'), regions: ['LOCAL'], max_tokens: Number(form.get('max_tokens')), timeout_seconds: Number(form.get('timeout_seconds')) }), intent: new RequestIntent() });
            setNotice('批准模型路由已登记。');
            setRouteForm(false);
            await routes.refetch();
        }
        catch (cause) {
            setError(message(cause));
        }
    };
    const createSuite = async (event) => {
        event.preventDefault();
        setError('');
        const form = new FormData(event.currentTarget);
        try {
            await apiRequestWithMetadata('/api/v2/platform/agent/eval-suites', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: form.get('name'), threshold: { minimum_score: Number(form.get('minimum_score') || 1) } }), intent: new RequestIntent() });
            setNotice('平台强制评测套件已创建。');
            await suites.refetch();
            event.currentTarget.reset();
        }
        catch (cause) {
            setError(message(cause));
        }
    };
    if (policies.isPending || routes.isPending || suites.isPending)
        return _jsx(RequestStateView, { state: "loading" });
    if (policies.isError)
        return _jsx(RequestStateView, { state: "error", message: message(policies.error), onRetry: () => void policies.refetch() });
    const policyValues = policies.data?.payload.data ?? [];
    const routeValues = routes.data?.payload.data ?? [];
    const suiteValues = suites.data?.payload.data ?? [];
    return _jsxs("section", { className: "workspace-page", children: [_jsx(PageHeader, { eyebrow: "PLATFORM / AGENTS", title: "Agent \u7B56\u7565\u3001\u8DEF\u7531\u4E0E\u8BC4\u6D4B", description: "\u7BA1\u7406\u7AEF\u5C55\u793A\u6CBB\u7406\u4E8B\u5B9E\u548C\u805A\u5408\u6307\u6807\uFF0C\u654F\u611F\u4E0A\u4E0B\u6587\u6309\u6700\u5C0F\u6743\u9650\u9690\u85CF\u3002", actions: _jsxs("div", { className: "toolbar", children: [_jsx("button", { className: "text-button", onClick: () => setRouteForm((value) => !value), children: "\u65B0\u589E\u8DEF\u7531" }), _jsx("button", { className: "text-button", onClick: () => setPolicyForm((value) => !value), children: "\u65B0\u589E\u5DE5\u5177\u7B56\u7565" })] }) }), notice ? _jsx("p", { className: "notice", role: "status", children: notice }) : null, error ? _jsx("p", { className: "form-error", role: "alert", children: error }) : null, routeForm ? _jsxs("section", { className: "section-block", children: [_jsx("h2", { children: "\u6279\u51C6\u6A21\u578B\u8DEF\u7531" }), _jsxs("form", { className: "form-grid", onSubmit: (event) => void createRoute(event), children: [_jsx(TextField, { label: "\u8DEF\u7531 key", name: "key", required: true }), _jsx(TextField, { label: "Provider", name: "provider", defaultValue: "LOCAL", required: true }), _jsx(TextField, { label: "\u6A21\u578B\u540D", name: "model_name", defaultValue: "rule-based", required: true }), _jsx(TextField, { label: "\u6700\u5927 token", name: "max_tokens", type: "number", defaultValue: "4096" }), _jsx(TextField, { label: "\u8D85\u65F6\u79D2\u6570", name: "timeout_seconds", type: "number", defaultValue: "5" }), _jsx("button", { className: "primary-button", type: "submit", children: "\u4FDD\u5B58\u8DEF\u7531" })] })] }) : null, policyForm ? _jsxs("section", { className: "section-block", children: [_jsx("h2", { children: "\u5DE5\u5177\u7B56\u7565\u7248\u672C" }), _jsxs("form", { className: "form-grid", onSubmit: (event) => void createPolicy(event), children: [_jsx(TextField, { label: "\u7B56\u7565 key", name: "key", required: true }), _jsx(TextField, { label: "\u5DE5\u5177\u540D\u79F0", name: "tool_name", required: true }), _jsxs("label", { className: "field", children: [_jsx("span", { children: "\u98CE\u9669\u7B49\u7EA7" }), _jsxs("select", { name: "risk", defaultValue: "LOW", children: [_jsx("option", { children: "LOW" }), _jsx("option", { children: "MEDIUM" }), _jsx("option", { children: "HIGH" }), _jsx("option", { children: "FORBIDDEN" })] })] }), _jsx(TextField, { label: "\u8D85\u65F6\u79D2\u6570", name: "timeout_seconds", type: "number", defaultValue: "30" }), _jsx(TextField, { label: "\u8F93\u51FA\u4E0A\u9650", name: "output_limit", type: "number", defaultValue: "8192" }), _jsx("button", { className: "primary-button", type: "submit", children: "\u4FDD\u5B58\u7B56\u7565" })] })] }) : null, _jsxs("section", { className: "section-block", children: [_jsx("h2", { children: "\u6A21\u578B\u8DEF\u7531\u4E0E fallback" }), _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u8DEF\u7531" }), _jsx("th", { children: "Provider/\u6A21\u578B" }), _jsx("th", { children: "\u533A\u57DF" }), _jsx("th", { children: "\u72B6\u6001" }), _jsx("th", { children: "token \u4E0A\u9650" })] }) }), _jsx("tbody", { children: routeValues.map((item) => _jsxs("tr", { children: [_jsxs("td", { children: [item.key, " \u00B7 v", item.version_no] }), _jsxs("td", { children: [item.provider, " / ", item.model_name] }), _jsx("td", { children: (item.regions ?? []).join(', ') }), _jsx("td", { children: _jsx(StatusBadge, { status: item.status }) }), _jsx("td", { children: item.max_tokens })] }, item.public_id)) })] }) }), routeValues.length === 0 ? _jsx(RequestStateView, { state: "empty" }) : null] }), _jsxs("section", { className: "section-block", children: [_jsx("h2", { children: "\u5DE5\u5177\u7B56\u7565" }), _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u5DE5\u5177" }), _jsx("th", { children: "\u98CE\u9669" }), _jsx("th", { children: "\u72B6\u6001" }), _jsx("th", { children: "\u8D85\u65F6/\u8F93\u51FA" })] }) }), _jsx("tbody", { children: policyValues.map((item) => _jsxs("tr", { children: [_jsxs("td", { children: [item.tool_name, " \u00B7 v", item.version_no] }), _jsx("td", { children: _jsx(StatusBadge, { status: item.risk }) }), _jsx("td", { children: _jsx(StatusBadge, { status: item.status }) }), _jsxs("td", { children: [item.timeout_seconds, "s / ", item.output_limit] })] }, item.public_id)) })] }) }), policyValues.length === 0 ? _jsx(RequestStateView, { state: "empty" }) : null] }), _jsxs("section", { className: "section-block", children: [_jsx("h2", { children: "\u5E73\u53F0\u5F3A\u5236\u8BC4\u6D4B" }), _jsxs("form", { className: "form-grid", onSubmit: (event) => void createSuite(event), children: [_jsx(TextField, { label: "\u5957\u4EF6\u540D\u79F0", name: "name", required: true }), _jsx(TextField, { label: "\u6700\u4F4E\u5206", name: "minimum_score", type: "number", step: "0.01", defaultValue: "1" }), _jsx("button", { className: "text-button", type: "submit", children: "\u521B\u5EFA\u5957\u4EF6" })] }), suiteValues.length ? _jsx("ul", { children: suiteValues.map((item) => _jsxs("li", { children: [item.name, " \u00B7 ", item.case_count ?? 0, " \u9898 \u00B7 ", item.platform_managed ? '强制' : '课程'] }, item.public_id)) }) : _jsx(RequestStateView, { state: "empty" })] }), _jsxs("section", { className: "section-block", children: [_jsx("h2", { children: "\u8C03\u7528\u4E0E\u6210\u672C\u805A\u5408" }), usage.isPending ? _jsx(RequestStateView, { state: "loading" }) : usage.isError ? _jsx(RequestStateView, { state: "error", onRetry: () => void usage.refetch() }) : _jsx("pre", { className: "summary-item", children: JSON.stringify(usage.data?.payload.data ?? {}, null, 2) })] })] });
}
