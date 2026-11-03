import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, RequestIntent, apiRequestWithMetadata, } from './legacy/api-client';
import { accountKeys, courseKeys, governanceKeys } from './legacy/query-keys';
import { PageHeader, RequestStateView, StatusBadge, TextField } from './legacy/ui';
function messageFor(error) {
    if (!(error instanceof ApiError))
        return '请求未完成，请稍后重试。';
    return error.payload.error.message;
}
function AsyncState({ query, children }) {
    if (query.isPending)
        return _jsx(RequestStateView, { state: "loading" });
    if (query.isError)
        return _jsx(RequestStateView, { state: "error", onRetry: () => void query.refetch() });
    return children;
}
export function UsersPage() {
    const queryClient = useQueryClient();
    const [error, setError] = useState('');
    const [showCreate, setShowCreate] = useState(false);
    const query = useQuery({ queryKey: accountKeys.users(), queryFn: () => apiRequestWithMetadata('/api/v2/platform/users') });
    const create = async (event) => {
        event.preventDefault();
        setError('');
        const form = new FormData(event.currentTarget);
        try {
            await apiRequestWithMetadata('/api/v2/platform/users', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(form)), intent: new RequestIntent() });
            event.currentTarget.reset();
            setShowCreate(false);
            await queryClient.invalidateQueries({ queryKey: accountKeys.users() });
        }
        catch (reason) {
            setError(messageFor(reason));
        }
    };
    const changeStatus = async (user) => {
        const next = user.account_status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE';
        if (!window.confirm(`确认将 ${user.display_name} 设置为 ${next}？`))
            return;
        try {
            await apiRequestWithMetadata(`/api/v2/platform/users/${user.public_id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ account_status: next, reason: '管理员账号治理操作' }), ifMatch: `"${user.row_version}"` });
            await queryClient.invalidateQueries({ queryKey: accountKeys.users() });
        }
        catch (reason) {
            setError(messageFor(reason));
        }
    };
    const grant = async (user, kind) => {
        const suffix = kind === 'teacher' ? 'teacher-qualification' : 'admin-assignment';
        try {
            await apiRequestWithMetadata(`/api/v2/platform/users/${user.public_id}/${suffix}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: '管理员授予资格' }), ifMatch: `"${user.row_version}"`, intent: new RequestIntent() });
            await queryClient.invalidateQueries({ queryKey: kind === 'teacher' ? accountKeys.teachers() : accountKeys.admins() });
        }
        catch (reason) {
            setError(messageFor(reason));
        }
    };
    const values = query.data?.payload.data ?? [];
    return _jsxs("section", { className: "workspace-page", children: [_jsx(PageHeader, { eyebrow: "PLATFORM ACCOUNTS", title: "\u7528\u6237\u8D26\u53F7", description: "\u521B\u5EFA\u3001\u505C\u7528\u3001\u6062\u590D\u8D26\u53F7\u5E76\u6388\u4E88\u95E8\u6237\u8D44\u683C\u3002", actions: _jsx("button", { className: "text-button", onClick: () => setShowCreate((value) => !value), children: "\u65B0\u5EFA\u8D26\u53F7" }) }), null, error ? _jsx("p", { className: "form-error", role: "alert", children: error }) : null, showCreate ? _jsxs("section", { className: "section-block", children: [_jsx("h2", { children: "\u65B0\u5EFA\u8D26\u53F7" }), _jsxs("form", { className: "form-grid", onSubmit: create, children: [_jsx(TextField, { label: "\u90AE\u7BB1", name: "email", type: "email", required: true }), _jsx(TextField, { label: "\u7528\u6237\u540D", name: "username", required: true }), _jsx(TextField, { label: "\u5C55\u793A\u540D\u79F0", name: "display_name", required: true }), _jsx(TextField, { label: "\u521D\u59CB\u5BC6\u7801", name: "password", type: "password", minLength: 12, required: true }), _jsx("div", { className: "form-actions", children: _jsx("button", { className: "primary-button", type: "submit", children: "\u521B\u5EFA" }) })] })] }) : null, _jsx(AsyncState, { query: query, children: values.length === 0 ? _jsx(RequestStateView, { state: "empty" }) : _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u7528\u6237" }), _jsx("th", { children: "\u7528\u6237\u540D" }), _jsx("th", { children: "\u72B6\u6001" }), _jsx("th", { children: "\u7248\u672C" }), _jsx("th", { children: "\u64CD\u4F5C" })] }) }), _jsx("tbody", { children: values.map((user) => _jsxs("tr", { children: [_jsxs("td", { "data-wrap": true, children: [_jsx("strong", { children: user.display_name }), _jsx("br", {}), user.email] }), _jsx("td", { children: user.username }), _jsx("td", { children: _jsx(StatusBadge, { status: user.account_status }) }), _jsx("td", { children: user.row_version }), _jsx("td", { children: _jsxs("div", { className: "toolbar", children: [_jsx("button", { className: user.account_status === 'ACTIVE' ? 'text-button text-button--danger' : 'text-button', onClick: () => void changeStatus(user), children: user.account_status === 'ACTIVE' ? '停用' : '恢复' }), _jsx("button", { className: "text-button", onClick: () => void grant(user, 'teacher'), children: "\u6388\u4E88\u6559\u5E08" }), _jsx("button", { className: "text-button", onClick: () => void grant(user, 'admin'), children: "\u6388\u4E88\u7BA1\u7406\u5458" })] }) })] }, user.public_id)) })] }) }) })] });
}
export function TeachersPage() {
    const queryClient = useQueryClient();
    const [error, setError] = useState('');
    const query = useQuery({ queryKey: accountKeys.teachers(), queryFn: () => apiRequestWithMetadata('/api/v2/platform/teacher-qualifications') });
    const change = async (value, status) => {
        if (!window.confirm(`确认将 ${value.display_name} 的教师资格设置为 ${status}？`))
            return;
        try {
            await apiRequestWithMetadata(`/api/v2/platform/teacher-qualifications/${value.public_id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status, reason: '管理员资格治理操作' }), ifMatch: `"${value.row_version}"` });
            await queryClient.invalidateQueries({ queryKey: accountKeys.teachers() });
        }
        catch (reason) {
            setError(messageFor(reason));
        }
    };
    const values = query.data?.payload.data ?? [];
    return _jsxs("section", { className: "workspace-page", children: [_jsx(PageHeader, { eyebrow: "QUALIFICATIONS", title: "\u6559\u5E08\u8D44\u683C", description: "\u6682\u505C\u4F1A\u7ACB\u5373\u7981\u6B62\u6559\u5E08\u7AEF\u8BBF\u95EE\uFF1B\u64A4\u9500\u5728 P03 \u63A5\u5165\u8BFE\u7A0B\u8D1F\u8D23\u4EBA\u963B\u65AD\u3002" }), null, error ? _jsx("p", { className: "form-error", children: error }) : null, _jsx(AsyncState, { query: query, children: values.length === 0 ? _jsx(RequestStateView, { state: "empty" }) : _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u6559\u5E08" }), _jsx("th", { children: "\u72B6\u6001" }), _jsx("th", { children: "\u539F\u56E0" }), _jsx("th", { children: "\u64CD\u4F5C" })] }) }), _jsx("tbody", { children: values.map((value) => _jsxs("tr", { children: [_jsx("td", { children: value.display_name }), _jsx("td", { children: _jsx(StatusBadge, { status: value.status }) }), _jsx("td", { "data-wrap": true, children: value.reason }), _jsx("td", { children: _jsxs("div", { className: "toolbar", children: [value.status === 'ACTIVE' ? _jsx("button", { className: "text-button", onClick: () => void change(value, 'SUSPENDED'), children: "\u6682\u505C" }) : null, value.status !== 'REVOKED' ? _jsx("button", { className: "text-button text-button--danger", onClick: () => void change(value, 'REVOKED'), children: "\u64A4\u9500" }) : null] }) })] }, value.public_id)) })] }) }) })] });
}
export function AdminsPage() {
    const queryClient = useQueryClient();
    const [error, setError] = useState('');
    const query = useQuery({ queryKey: accountKeys.admins(), queryFn: () => apiRequestWithMetadata('/api/v2/platform/admin-assignments') });
    const revoke = async (value) => {
        if (!window.confirm(`确认撤销 ${value.display_name} 的管理员资格？最后一名管理员不可撤销。`))
            return;
        try {
            await apiRequestWithMetadata(`/api/v2/platform/admin-assignments/${value.public_id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'REVOKED', reason: '管理员资格治理操作' }), ifMatch: `"${value.row_version}"` });
            await queryClient.invalidateQueries({ queryKey: accountKeys.admins() });
        }
        catch (reason) {
            setError(messageFor(reason));
        }
    };
    const values = query.data?.payload.data ?? [];
    return _jsxs("section", { className: "workspace-page", children: [_jsx(PageHeader, { eyebrow: "PLATFORM ACCESS", title: "\u7BA1\u7406\u5458\u8D44\u683C", description: "\u7BA1\u7406\u5458\u8D44\u683C\u4E0E\u6559\u5E08\u8D44\u683C\u72EC\u7ACB\u7EF4\u62A4\u3002" }), null, error ? _jsx("p", { className: "form-error", children: error }) : null, _jsx(AsyncState, { query: query, children: values.length === 0 ? _jsx(RequestStateView, { state: "empty" }) : _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u7BA1\u7406\u5458" }), _jsx("th", { children: "\u72B6\u6001" }), _jsx("th", { children: "\u6388\u4E88\u65F6\u95F4" }), _jsx("th", { children: "\u64CD\u4F5C" })] }) }), _jsx("tbody", { children: values.map((value) => _jsxs("tr", { children: [_jsx("td", { children: value.display_name }), _jsx("td", { children: _jsx(StatusBadge, { status: value.status }) }), _jsx("td", { children: new Date(value.granted_at).toLocaleString() }), _jsx("td", { children: value.status === 'ACTIVE' ? _jsx("button", { className: "text-button text-button--danger", onClick: () => void revoke(value), children: "\u64A4\u9500" }) : null })] }, value.public_id)) })] }) }) })] });
}
export function VerificationsPage() {
    const queryClient = useQueryClient();
    const [error, setError] = useState('');
    const query = useQuery({ queryKey: accountKeys.verifications(), queryFn: () => apiRequestWithMetadata('/api/v2/platform/verifications') });
    const review = async (value, decision) => {
        const reason = decision === 'REJECT' ? window.prompt('请输入拒绝原因') : '';
        if (decision === 'REJECT' && !reason)
            return;
        try {
            await apiRequestWithMetadata(`/api/v2/platform/verifications/${value.public_id}/review`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, reason }), ifMatch: `"${value.row_version}"`, intent: new RequestIntent() });
            await queryClient.invalidateQueries({ queryKey: accountKeys.verifications() });
        }
        catch (cause) {
            setError(messageFor(cause));
        }
    };
    const values = query.data?.payload.data ?? [];
    return _jsxs("section", { className: "workspace-page", children: [_jsx(PageHeader, { eyebrow: "IDENTITY REVIEW", title: "\u8EAB\u4EFD\u5BA1\u6838", description: "\u8BC1\u4EF6\u539F\u503C\u4E0D\u4F1A\u51FA\u73B0\u5728\u54CD\u5E94\u3001\u65E5\u5FD7\u6216\u5BA1\u8BA1\u4E2D\u3002" }), null, error ? _jsx("p", { className: "form-error", children: error }) : null, _jsx(AsyncState, { query: query, children: values.length === 0 ? _jsx(RequestStateView, { state: "empty" }) : _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u7528\u6237" }), _jsx("th", { children: "\u7C7B\u578B" }), _jsx("th", { children: "\u673A\u6784" }), _jsx("th", { children: "\u8BC1\u4EF6\u63A9\u7801" }), _jsx("th", { children: "\u72B6\u6001" }), _jsx("th", { children: "\u64CD\u4F5C" })] }) }), _jsx("tbody", { children: values.map((value) => _jsxs("tr", { children: [_jsx("td", { children: value.user_id }), _jsx("td", { children: value.identity_type }), _jsx("td", { "data-wrap": true, children: value.organization_name }), _jsx("td", { children: value.identity_number_masked || '-' }), _jsx("td", { children: _jsx(StatusBadge, { status: value.status }) }), _jsx("td", { children: value.status === 'SUBMITTED' ? _jsxs("div", { className: "toolbar", children: [_jsx("button", { className: "text-button", onClick: () => void review(value, 'APPROVE'), children: "\u901A\u8FC7" }), _jsx("button", { className: "text-button text-button--danger", onClick: () => void review(value, 'REJECT'), children: "\u62D2\u7EDD" })] }) : null })] }, value.public_id)) })] }) }) })] });
}
export function CoursesPage() {
    const query = useQuery({ queryKey: courseKeys.catalog({ portal: 'PLATFORM' }), queryFn: () => apiRequestWithMetadata('/api/v2/platform/courses') });
    const values = query.data?.payload.data ?? [];
    if (query.isPending)
        return _jsx(RequestStateView, { state: "loading" });
    if (query.isError)
        return _jsx(RequestStateView, { state: "error", onRetry: () => void query.refetch() });
    return _jsxs("section", { className: "workspace-page", children: [_jsx(PageHeader, { eyebrow: "COURSE GOVERNANCE", title: "\u8BFE\u7A0B\u76D1\u7BA1", description: "\u7BA1\u7406\u7AEF\u53EA\u8BFB\u53D6\u8BFE\u7A0B\u76D1\u7BA1\u4E8B\u5B9E\uFF1B\u6559\u5B66\u5BA1\u6279\u4ECD\u7531\u6559\u5E08\u7AEF\u5B8C\u6210\u3002" }), values.length ? _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u8BFE\u7A0B" }), _jsx("th", { children: "\u8D1F\u8D23\u4EBA" }), _jsx("th", { children: "\u72B6\u6001" }), _jsx("th", { children: "\u6CBB\u7406\u5165\u53E3" })] }) }), _jsx("tbody", { children: values.map((course) => _jsxs("tr", { children: [_jsxs("td", { "data-wrap": true, children: [_jsx("strong", { children: course.title }), _jsx("br", {}), course.code] }), _jsx("td", { children: course.owner_name }), _jsx("td", { children: _jsx(StatusBadge, { status: course.status }) }), _jsx("td", { children: _jsx("button", { className: "text-button", disabled: true, title: "\u6CBB\u7406\u51BB\u7ED3\u80FD\u529B\u5C1A\u672A\u5F00\u653E", children: "\u51BB\u7ED3\u5165\u53E3\uFF08\u4E0D\u53EF\u7528\uFF09" }) })] }, course.public_id)) })] }) }) : _jsx(RequestStateView, { state: "empty" })] });
}
function GovernanceError({ error, retry }) {
    if (error instanceof ApiError && error.status === 403)
        return _jsx(RequestStateView, { state: "forbidden", message: messageFor(error) });
    if (error instanceof ApiError && error.status === 409)
        return _jsx(RequestStateView, { state: "conflict", message: messageFor(error), onRetry: retry });
    if (error instanceof ApiError && error.status === 412)
        return _jsx(RequestStateView, { state: "precondition", message: messageFor(error), onRetry: retry });
    return _jsx(RequestStateView, { state: "error", message: messageFor(error), onRetry: retry });
}
export function RuntimesPage() {
    const queryClient = useQueryClient();
    const [error, setError] = useState('');
    const [showCreate, setShowCreate] = useState(false);
    const query = useQuery({ queryKey: governanceKeys.runtimes(), queryFn: () => apiRequestWithMetadata('/api/v2/platform/runtime-adapters') });
    const create = async (event) => {
        event.preventDefault();
        setError('');
        const form = new FormData(event.currentTarget);
        try {
            await apiRequestWithMetadata('/api/v2/platform/runtime-adapters', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(form)), intent: new RequestIntent() });
            event.currentTarget.reset();
            setShowCreate(false);
            await queryClient.invalidateQueries({ queryKey: governanceKeys.runtimes() });
        }
        catch (reason) {
            setError(messageFor(reason));
        }
    };
    if (query.isPending)
        return _jsx(RequestStateView, { state: "loading" });
    if (query.isError)
        return _jsx(GovernanceError, { error: query.error, retry: () => void query.refetch() });
    const values = query.data?.payload.data ?? [];
    return _jsxs("section", { className: "workspace-page", children: [_jsx(PageHeader, { eyebrow: "GOVERNANCE / RUNTIMES", title: "\u8FD0\u884C\u65F6\u76EE\u5F55", description: "\u7EF4\u62A4\u8FD0\u884C\u65F6\u80FD\u529B\u548C\u5065\u5EB7\u5FEB\u7167\uFF1BP04 \u4E0D\u521B\u5EFA\u5BB9\u5668\u3002", actions: _jsx("button", { className: "text-button", onClick: () => setShowCreate((value) => !value), children: "\u65B0\u5EFA\u8FD0\u884C\u65F6" }) }), null, error ? _jsx("p", { className: "form-error", role: "alert", children: error }) : null, showCreate ? _jsxs("section", { className: "section-block", children: [_jsx("h2", { children: "\u767B\u8BB0\u8FD0\u884C\u65F6" }), _jsxs("form", { className: "form-grid", onSubmit: create, children: [_jsx(TextField, { label: "\u7F16\u7801", name: "code", required: true }), _jsx(TextField, { label: "\u540D\u79F0", name: "name", required: true }), _jsxs("label", { className: "field", children: [_jsx("span", { children: "\u7C7B\u578B" }), _jsxs("select", { name: "runtime_type", defaultValue: "CONTAINER", children: [_jsx("option", { value: "CONTAINER", children: "\u5BB9\u5668" }), _jsx("option", { value: "VM", children: "\u865A\u62DF\u673A" })] })] }), _jsxs("label", { className: "field", children: [_jsx("span", { children: "\u9A71\u52A8" }), _jsxs("select", { name: "driver", defaultValue: "FAKE", children: [_jsx("option", { value: "FAKE", children: "Fake" }), _jsx("option", { value: "DOCKER_SWARM", children: "Docker Swarm" }), _jsx("option", { value: "LIBVIRT", children: "Libvirt" })] })] }), _jsx(TextField, { label: "\u914D\u7F6E\u5F15\u7528", name: "config_ref" }), _jsx(TextField, { label: "\u53D8\u66F4\u539F\u56E0", name: "reason", required: true }), _jsx("div", { className: "form-actions", children: _jsx("button", { className: "primary-button", type: "submit", children: "\u767B\u8BB0" }) })] })] }) : null, _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u8FD0\u884C\u65F6" }), _jsx("th", { children: "\u7C7B\u578B/\u9A71\u52A8" }), _jsx("th", { children: "\u72B6\u6001" }), _jsx("th", { children: "\u5065\u5EB7" }), _jsx("th", { children: "\u5BB9\u91CF" })] }) }), _jsx("tbody", { children: values.map((item) => _jsxs("tr", { children: [_jsxs("td", { "data-wrap": true, children: [_jsx("strong", { children: item.name }), _jsx("br", {}), item.code] }), _jsxs("td", { children: [item.runtime_type, " / ", item.driver] }), _jsx("td", { children: _jsx(StatusBadge, { status: item.status }) }), _jsx("td", { children: _jsx(StatusBadge, { status: item.health_status }) }), _jsxs("td", { children: [item.available_cpu_millicores, " / ", item.capacity_cpu_millicores, " mCPU"] })] }, item.public_id)) })] }) }), values.length === 0 ? _jsx(RequestStateView, { state: "empty" }) : null] });
}
export function ImagesPage() {
    const queryClient = useQueryClient();
    const [error, setError] = useState('');
    const [showCreate, setShowCreate] = useState(false);
    const query = useQuery({ queryKey: governanceKeys.images(), queryFn: () => apiRequestWithMetadata('/api/v2/platform/images') });
    const create = async (event) => { event.preventDefault(); setError(''); const form = new FormData(event.currentTarget); try {
        await apiRequestWithMetadata('/api/v2/platform/images', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(form)), intent: new RequestIntent() });
        event.currentTarget.reset();
        setShowCreate(false);
        await queryClient.invalidateQueries({ queryKey: governanceKeys.images() });
    }
    catch (reason) {
        setError(messageFor(reason));
    } };
    const decide = async (item, decision) => { const reason = window.prompt('请输入变更原因'); if (!reason)
        return; setError(''); try {
        await apiRequestWithMetadata(`/api/v2/platform/images/${item.public_id}/decide`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, reason }), ifMatch: `"${item.row_version}"`, intent: new RequestIntent() });
        await queryClient.invalidateQueries({ queryKey: governanceKeys.images() });
    }
    catch (cause) {
        setError(messageFor(cause));
    } };
    if (query.isPending)
        return _jsx(RequestStateView, { state: "loading" });
    if (query.isError)
        return _jsx(GovernanceError, { error: query.error, retry: () => void query.refetch() });
    const values = query.data?.payload.data ?? [];
    return _jsxs("section", { className: "workspace-page", children: [_jsx(PageHeader, { eyebrow: "GOVERNANCE / IMAGES", title: "\u955C\u50CF\u76EE\u5F55", description: "digest \u662F\u4E0D\u53EF\u6F02\u79FB\u7684\u8FD0\u884C\u4E8B\u5B9E\uFF0Ctag \u4EC5\u7528\u4E8E\u5C55\u793A\u3002", actions: _jsx("button", { className: "text-button", onClick: () => setShowCreate((value) => !value), children: "\u767B\u8BB0\u955C\u50CF" }) }), null, error ? _jsx("p", { className: "form-error", role: "alert", children: error }) : null, showCreate ? _jsxs("section", { className: "section-block", children: [_jsx("h2", { children: "\u767B\u8BB0\u955C\u50CF digest" }), _jsxs("form", { className: "form-grid", onSubmit: create, children: [_jsx(TextField, { label: "\u955C\u50CF\u4ED3\u5E93", name: "registry", required: true }), _jsx(TextField, { label: "\u4ED3\u5E93\u8DEF\u5F84", name: "repository", required: true }), _jsx(TextField, { label: "\u5C55\u793A tag", name: "display_tag" }), _jsx(TextField, { label: "digest", name: "digest", pattern: "sha256:[a-fA-F0-9]{64}", required: true }), _jsxs("label", { className: "field", children: [_jsx("span", { children: "\u98CE\u9669\u7B49\u7EA7" }), _jsxs("select", { name: "risk_level", defaultValue: "LOW", children: [_jsx("option", { value: "LOW", children: "\u4F4E" }), _jsx("option", { value: "MEDIUM", children: "\u4E2D" }), _jsx("option", { value: "HIGH", children: "\u9AD8" })] })] }), _jsx(TextField, { label: "\u53D8\u66F4\u539F\u56E0", name: "reason", required: true }), _jsx("div", { className: "form-actions", children: _jsx("button", { className: "primary-button", type: "submit", children: "\u767B\u8BB0" }) })] })] }) : null, _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u955C\u50CF" }), _jsx("th", { children: "digest" }), _jsx("th", { children: "\u626B\u63CF" }), _jsx("th", { children: "\u6279\u51C6" }), _jsx("th", { children: "\u64CD\u4F5C" })] }) }), _jsx("tbody", { children: values.map((item) => _jsxs("tr", { children: [_jsxs("td", { "data-wrap": true, children: [_jsx("strong", { children: item.repository }), _jsx("br", {}), item.display_tag || '-'] }), _jsxs("td", { children: [item.digest.slice(0, 18), "..."] }), _jsx("td", { children: _jsx(StatusBadge, { status: item.scan_status }) }), _jsx("td", { children: _jsx(StatusBadge, { status: item.approval_status }) }), _jsx("td", { children: item.approval_status === 'PENDING' ? _jsx("button", { className: "text-button", onClick: () => void decide(item, 'APPROVED'), children: "\u6279\u51C6" }) : null })] }, item.public_id)) })] }) }), values.length === 0 ? _jsx(RequestStateView, { state: "empty" }) : null] });
}
export function ResourceProfilesPage() {
    const queryClient = useQueryClient();
    const [error, setError] = useState('');
    const [showCreate, setShowCreate] = useState(false);
    const query = useQuery({ queryKey: governanceKeys.profiles(), queryFn: () => apiRequestWithMetadata('/api/v2/platform/resource-profiles') });
    const create = async (event) => { event.preventDefault(); setError(''); const form = new FormData(event.currentTarget); try {
        await apiRequestWithMetadata('/api/v2/platform/resource-profiles', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(form)), intent: new RequestIntent() });
        event.currentTarget.reset();
        setShowCreate(false);
        await queryClient.invalidateQueries({ queryKey: governanceKeys.profiles() });
    }
    catch (reason) {
        setError(messageFor(reason));
    } };
    const activate = async (item) => { const reason = window.prompt('请输入激活原因'); if (!reason)
        return; try {
        await apiRequestWithMetadata(`/api/v2/platform/resource-profiles/${item.public_id}/activate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason }), ifMatch: `"${item.row_version}"`, intent: new RequestIntent() });
        await queryClient.invalidateQueries({ queryKey: governanceKeys.profiles() });
    }
    catch (cause) {
        setError(messageFor(cause));
    } };
    if (query.isPending)
        return _jsx(RequestStateView, { state: "loading" });
    if (query.isError)
        return _jsx(GovernanceError, { error: query.error, retry: () => void query.refetch() });
    const values = query.data?.payload.data ?? [];
    return _jsxs("section", { className: "workspace-page", children: [_jsx(PageHeader, { eyebrow: "GOVERNANCE / PROFILES", title: "\u8D44\u6E90\u89C4\u683C", description: "ACTIVE \u89C4\u683C\u51BB\u7ED3\uFF1B\u540E\u7EED\u53D8\u66F4\u521B\u5EFA\u65B0\u89C4\u683C\u3002", actions: _jsx("button", { className: "text-button", onClick: () => setShowCreate((value) => !value), children: "\u65B0\u5EFA\u89C4\u683C" }) }), null, error ? _jsx("p", { className: "form-error", role: "alert", children: error }) : null, showCreate ? _jsxs("section", { className: "section-block", children: [_jsx("h2", { children: "\u65B0\u5EFA\u8D44\u6E90\u89C4\u683C" }), _jsxs("form", { className: "form-grid", onSubmit: create, children: [_jsx(TextField, { label: "\u7F16\u7801", name: "code", required: true }), _jsx(TextField, { label: "\u540D\u79F0", name: "name", required: true }), _jsx(TextField, { label: "CPU mCPU", name: "cpu_millicores", type: "number", min: "1", required: true }), _jsx(TextField, { label: "\u5185\u5B58 MB", name: "memory_mb", type: "number", min: "1", required: true }), _jsx(TextField, { label: "\u78C1\u76D8 GB", name: "disk_gb", type: "number", min: "1", required: true }), _jsxs("label", { className: "field", children: [_jsx("span", { children: "\u7F51\u7EDC\u6A21\u5F0F" }), _jsxs("select", { name: "network_mode", defaultValue: "DENY_ALL", children: [_jsx("option", { value: "DENY_ALL", children: "\u7981\u6B62\u51FA\u7F51" }), _jsx("option", { value: "ALLOWLIST", children: "\u767D\u540D\u5355" })] })] }), _jsx(TextField, { label: "\u53D8\u66F4\u539F\u56E0", name: "reason", required: true }), _jsx("div", { className: "form-actions", children: _jsx("button", { className: "primary-button", type: "submit", children: "\u4FDD\u5B58\u8349\u7A3F" }) })] })] }) : null, _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u89C4\u683C" }), _jsx("th", { children: "\u8D44\u6E90" }), _jsx("th", { children: "\u7F51\u7EDC" }), _jsx("th", { children: "\u72B6\u6001" }), _jsx("th", { children: "\u64CD\u4F5C" })] }) }), _jsx("tbody", { children: values.map((item) => _jsxs("tr", { children: [_jsxs("td", { "data-wrap": true, children: [_jsx("strong", { children: item.name }), _jsx("br", {}), item.code] }), _jsxs("td", { children: [item.cpu_millicores, " mCPU / ", item.memory_mb, " MB / ", item.disk_gb, " GB"] }), _jsx("td", { children: item.network_mode }), _jsx("td", { children: _jsx(StatusBadge, { status: item.status }) }), _jsx("td", { children: item.status === 'DRAFT' ? _jsx("button", { className: "text-button", onClick: () => void activate(item), children: "\u6FC0\u6D3B" }) : null })] }, item.public_id)) })] }) }), values.length === 0 ? _jsx(RequestStateView, { state: "empty" }) : null] });
}
export function QuotasPage() {
    const queryClient = useQueryClient();
    const [error, setError] = useState('');
    const [showCreate, setShowCreate] = useState(false);
    const query = useQuery({ queryKey: governanceKeys.quotas(), queryFn: () => apiRequestWithMetadata('/api/v2/platform/quotas') });
    const create = async (event) => { event.preventDefault(); setError(''); const form = new FormData(event.currentTarget); const raw = Object.fromEntries(form); const body = { ...raw, max_concurrent_instances: Number(raw.max_concurrent_instances), max_cpu_millicores: Number(raw.max_cpu_millicores) }; try {
        await apiRequestWithMetadata('/api/v2/platform/quotas', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), intent: new RequestIntent() });
        event.currentTarget.reset();
        setShowCreate(false);
        await queryClient.invalidateQueries({ queryKey: governanceKeys.quotas() });
    }
    catch (reason) {
        setError(messageFor(reason));
    } };
    if (query.isPending)
        return _jsx(RequestStateView, { state: "loading" });
    if (query.isError)
        return _jsx(GovernanceError, { error: query.error, retry: () => void query.refetch() });
    const values = query.data?.payload.data ?? [];
    return _jsxs("section", { className: "workspace-page", children: [_jsx(PageHeader, { eyebrow: "GOVERNANCE / QUOTAS", title: "\u4E09\u7EA7\u914D\u989D", description: "\u5E73\u53F0\u3001\u8BFE\u7A0B\u548C\u7528\u6237\u914D\u989D\u7531 MySQL \u4E8B\u5B9E\u8BA1\u7B97\uFF0C\u7F3A\u7701\u65F6\u7EE7\u627F\u4E0A\u5C42\u3002", actions: _jsx("button", { className: "text-button", onClick: () => setShowCreate((value) => !value), children: "\u65B0\u589E\u914D\u989D" }) }), null, error ? _jsx("p", { className: "form-error", role: "alert", children: error }) : null, showCreate ? _jsxs("section", { className: "section-block", children: [_jsx("h2", { children: "\u65B0\u589E\u5E73\u53F0\u914D\u989D" }), _jsxs("form", { className: "form-grid", onSubmit: create, children: [_jsx("input", { type: "hidden", name: "scope_type", value: "PLATFORM" }), _jsx(TextField, { label: "\u5E76\u53D1\u5B9E\u4F8B", name: "max_concurrent_instances", type: "number", min: "1", required: true }), _jsx(TextField, { label: "CPU mCPU", name: "max_cpu_millicores", type: "number", min: "1", required: true }), _jsx(TextField, { label: "\u53D8\u66F4\u539F\u56E0", name: "reason", required: true }), _jsx("div", { className: "form-actions", children: _jsx("button", { className: "primary-button", type: "submit", children: "\u4FDD\u5B58\u914D\u989D" }) })] })] }) : null, _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u8303\u56F4" }), _jsx("th", { children: "\u5B9E\u4F8B" }), _jsx("th", { children: "CPU" }), _jsx("th", { children: "\u5185\u5B58" }), _jsx("th", { children: "\u7248\u672C" })] }) }), _jsx("tbody", { children: values.map((item) => _jsxs("tr", { children: [_jsxs("td", { children: [item.scope_type, _jsx("br", {}), _jsx("small", { children: item.course_id || item.user_id || 'PLATFORM' })] }), _jsx("td", { children: item.max_concurrent_instances ?? '继承' }), _jsxs("td", { children: [item.max_cpu_millicores ?? '继承', " mCPU"] }), _jsxs("td", { children: [item.max_memory_mb ?? '继承', " MB"] }), _jsx("td", { children: item.row_version })] }, item.public_id)) })] }) }), values.length === 0 ? _jsx(RequestStateView, { state: "empty" }) : null] });
}
export function SecurityPage() {
    const queryClient = useQueryClient();
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');
    const policiesQuery = useQuery({ queryKey: governanceKeys.policies(), queryFn: () => apiRequestWithMetadata('/api/v2/platform/security-policies') });
    const scalingQuery = useQuery({ queryKey: governanceKeys.policies('RESOURCE_SCALING'), queryFn: () => apiRequestWithMetadata('/api/v2/platform/resource-scaling-policies') });
    const allowlistQuery = useQuery({ queryKey: governanceKeys.allowlists(), queryFn: () => apiRequestWithMetadata('/api/v2/platform/network-allowlists') });
    const usageQuery = useQuery({ queryKey: governanceKeys.usage(), queryFn: () => apiRequestWithMetadata('/api/v2/platform/governance/usage') });
    const alertsQuery = useQuery({ queryKey: governanceKeys.alerts(), queryFn: () => apiRequestWithMetadata('/api/v2/platform/governance/alerts') });
    const savePolicy = async (event, kind) => { event.preventDefault(); setError(''); setMessage(''); const form = new FormData(event.currentTarget); const rules = kind === 'security' ? { default_egress: 'DENY_ALL', allow_privileged: false, require_workspace_gateway: true } : { prewarm_enabled: true, min_replicas: 0, max_replicas: 2, cooldown_seconds: 300, idle_reclaim_seconds: 1800, budget_minor: 10000 }; try {
        await apiRequestWithMetadata(`/api/v2/platform/${kind === 'security' ? 'security-policies' : 'resource-scaling-policies'}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scope_type: 'PLATFORM', risk_level: 'HIGH', rules, reason: form.get('reason') }), intent: new RequestIntent() });
        setMessage('策略已提交，审计与 Outbox 已记录。');
        await Promise.all([queryClient.invalidateQueries({ queryKey: governanceKeys.policies() }), queryClient.invalidateQueries({ queryKey: governanceKeys.policies('RESOURCE_SCALING') })]);
    }
    catch (cause) {
        setError(messageFor(cause));
    } };
    const busy = policiesQuery.isPending || scalingQuery.isPending || allowlistQuery.isPending || usageQuery.isPending || alertsQuery.isPending;
    if (busy)
        return _jsx(RequestStateView, { state: "loading" });
    const failedQuery = [policiesQuery, scalingQuery, allowlistQuery, usageQuery, alertsQuery].find((candidate) => candidate.isError);
    if (failedQuery?.isError)
        return _jsx(GovernanceError, { error: failedQuery.error, retry: () => void failedQuery.refetch() });
    const policies = policiesQuery.data?.payload.data ?? [];
    const scaling = scalingQuery.data?.payload.data ?? [];
    const allowlist = allowlistQuery.data?.payload.data ?? [];
    const usage = usageQuery.data?.payload.data;
    const alerts = alertsQuery.data?.payload.data ?? [];
    return _jsxs("section", { className: "workspace-page", children: [_jsx(PageHeader, { eyebrow: "GOVERNANCE / SECURITY", title: "\u5B89\u5168\u4E0E\u7B56\u7565\u62A4\u680F", description: "\u5B89\u5168\u7B56\u7565\u3001\u7F51\u7EDC\u767D\u540D\u5355\u3001\u9884\u70ED\u3001\u6269\u7F29\u5BB9\u548C\u9884\u7B97\u5171\u7528\u6CBB\u7406\u4E8B\u5B9E\u8868\u3002" }), null, message ? _jsx("p", { className: "notice", role: "status", children: message }) : null, error ? _jsx("p", { className: "form-error", role: "alert", children: error }) : null, _jsxs("div", { className: "summary-grid", children: [_jsxs("div", { className: "summary-item", children: [_jsx("span", { children: "\u5F53\u524D\u9884\u7559\u5B9E\u4F8B" }), _jsx("strong", { children: usage?.reservation.instance_count ?? 0 })] }), _jsxs("div", { className: "summary-item", children: [_jsx("span", { children: "\u5BF9\u8C61\u5B58\u50A8" }), _jsxs("strong", { children: [usage?.object_storage_bytes ?? 0, " B"] })] }), _jsxs("div", { className: "summary-item", children: [_jsx("span", { children: "\u544A\u8B66\u6458\u8981" }), _jsx("strong", { children: alerts.length })] })] }), _jsxs("section", { className: "section-block", children: [_jsx("h2", { children: "\u5B89\u5168\u7B56\u7565" }), _jsx("p", { children: policies.length ? JSON.stringify(policies[0].rules) : '尚未配置平台安全策略' }), _jsxs("form", { className: "form-grid", onSubmit: (event) => void savePolicy(event, 'security'), children: [_jsx(TextField, { label: "\u53D8\u66F4\u539F\u56E0", name: "reason", required: true }), _jsx("div", { className: "form-actions", children: _jsx("button", { className: "primary-button", type: "submit", children: "\u4FDD\u5B58\u9ED8\u8BA4\u62D2\u7EDD\u7B56\u7565" }) })] })] }), _jsxs("section", { className: "section-block", children: [_jsx("h2", { children: "\u6269\u7F29\u5BB9\u4E0E\u9884\u70ED" }), _jsx("p", { children: scaling.length ? JSON.stringify(scaling[0].rules) : '尚未配置扩缩容策略' }), _jsxs("form", { className: "form-grid", onSubmit: (event) => void savePolicy(event, 'scaling'), children: [_jsx(TextField, { label: "\u53D8\u66F4\u539F\u56E0", name: "reason", required: true }), _jsx("div", { className: "form-actions", children: _jsx("button", { className: "primary-button", type: "submit", children: "\u4FDD\u5B58\u9884\u7B97\u62A4\u680F" }) })] })] }), _jsxs("section", { className: "section-block", children: [_jsx("h2", { children: "\u7F51\u7EDC\u767D\u540D\u5355" }), allowlist.length ? _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u8303\u56F4" }), _jsx("th", { children: "\u76EE\u6807" }), _jsx("th", { children: "\u7AEF\u53E3" }), _jsx("th", { children: "\u72B6\u6001" })] }) }), _jsx("tbody", { children: allowlist.map((item) => _jsxs("tr", { children: [_jsx("td", { children: item.scope_type }), _jsx("td", { children: item.target_value }), _jsxs("td", { children: [item.protocol, " ", item.port_start, "-", item.port_end] }), _jsx("td", { children: _jsx(StatusBadge, { status: item.status }) })] }, item.public_id)) })] }) }) : _jsx(RequestStateView, { state: "empty" })] }), _jsxs("section", { className: "section-block", children: [_jsx("h2", { children: "\u544A\u8B66" }), alerts.length ? _jsx("div", { className: "data-table-wrap", children: _jsxs("table", { className: "data-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u7B49\u7EA7" }), _jsx("th", { children: "\u4EE3\u7801" }), _jsx("th", { children: "\u8D44\u6E90" }), _jsx("th", { children: "\u8BF4\u660E" })] }) }), _jsx("tbody", { children: alerts.map((item) => _jsxs("tr", { children: [_jsx("td", { children: _jsx(StatusBadge, { status: item.severity }) }), _jsx("td", { children: item.code }), _jsx("td", { children: item.resource_ref }), _jsx("td", { "data-wrap": true, children: item.message })] }, `${item.code}-${item.resource_ref}`)) })] }) }) : _jsx(RequestStateView, { state: "empty" })] })] });
}
