import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useMutation, useQuery } from "@tanstack/react-query";
import { platformApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Button, Modal, Panel, RequestStateView, StatusBadge, useToast, } from "@edu/ui";
import { useState } from "react";
export function Users() {
    const toast = useToast();
    const [reviewTarget, setReviewTarget] = useState(null);
    const [note, setNote] = useState("");
    const users = useQuery({ queryKey: keys.platformUsers({}), queryFn: () => platformApi.users({ page_size: 100 }) });
    const verifications = useQuery({ queryKey: keys.verifications({ status: "PENDING" }), queryFn: () => platformApi.verifications({ status: "PENDING" }) });
    const review = useMutation({
        mutationFn: (input) => platformApi.reviewVerification(input.target.public_id, { decision: input.decision, note }, input.target.payload_summary?.row_version ?? ""),
        onSuccess: (_data, input) => {
            toast.notify(input.decision === "approve" ? "已通过" : "已拒绝");
            setReviewTarget(null);
            void verifications.refetch();
            void users.refetch();
        },
        onError: () => toast.notify("审核失败，请检查权限后重试", "error"),
    });
    const rows = users.data?.rows ?? [];
    const pendingVerifications = verifications.data?.rows ?? [];
    return (_jsxs(_Fragment, { children: [_jsx(Panel, { title: _jsxs(_Fragment, { children: [_jsx("h2", { children: "\u5F85\u5904\u7406\u8D44\u683C\u7533\u8BF7" }), _jsx("span", { className: "subtle", children: "\u6309\u63D0\u4EA4\u65F6\u95F4\u6392\u5E8F" })] }), children: _jsx(RequestStateView, { loading: verifications.isLoading, error: verifications.error, onRetry: () => void verifications.refetch(), empty: !pendingVerifications.length, emptyState: _jsx("div", { className: "state-block", children: _jsx("strong", { children: "\u6682\u65E0\u5F85\u5904\u7406\u8D44\u683C\u7533\u8BF7" }) }), children: _jsx("div", { children: pendingVerifications.map((item) => (_jsxs("div", { className: "item", children: [_jsxs("div", { children: [_jsx("strong", { children: item.target_user_name ?? item.public_id }), _jsxs("small", { children: [item.kind, " \u00B7 ", item.submitted_at] })] }), _jsx(Button, { size: "sm", variant: "primary", onClick: () => setReviewTarget(item), children: "\u5904\u7406" })] }, item.public_id))) }) }) }), _jsx(Panel, { className: "section", title: _jsx("h2", { children: "\u7528\u6237\u5217\u8868" }), children: _jsx(RequestStateView, { loading: users.isLoading, error: users.error, onRetry: () => void users.refetch(), empty: !rows.length, emptyState: _jsx("div", { className: "state-block", children: _jsx("strong", { children: "\u6682\u65E0\u7528\u6237" }) }), children: _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u7528\u6237" }), _jsx("th", { children: "\u90AE\u7BB1" }), _jsx("th", { children: "\u8D26\u53F7\u72B6\u6001" }), _jsx("th", { children: "\u8D44\u683C" }), _jsx("th", { children: "\u7BA1\u7406\u5458" })] }) }), _jsx("tbody", { children: rows.map((user) => (_jsxs("tr", { children: [_jsxs("td", { children: [_jsx("strong", { children: user.display_name }), _jsx("small", { style: { display: "block" }, children: user.username })] }), _jsx("td", { children: user.email }), _jsx("td", { children: _jsx(StatusBadge, { tone: user.account_status === "ACTIVE" ? "good" : "neutral", children: user.account_status }) }), _jsx("td", { children: user.teacher_qualification?.status
                                                    ? _jsx(StatusBadge, { tone: user.teacher_qualification.status === "APPROVED" ? "good" : "warn", children: user.teacher_qualification.status })
                                                    : _jsx("span", { className: "subtle", children: "\u672A\u7533\u8BF7" }) }), _jsx("td", { children: user.admin_assignment?.role ?? "—" })] }, user.public_id))) })] }) }) }) }), _jsxs(Modal, { open: reviewTarget != null, onClose: () => setReviewTarget(null), eyebrow: "\u8D44\u683C\u5BA1\u6838", title: reviewTarget ? `审核 ${reviewTarget.target_user_name ?? ""}` : "资格审核", actions: (_jsxs(_Fragment, { children: [_jsx(Button, { onClick: () => setReviewTarget(null), children: "\u53D6\u6D88" }), _jsx(Button, { variant: "danger", disabled: review.isPending, onClick: () => { if (reviewTarget)
                                review.mutate({ target: reviewTarget, decision: "reject" }); }, children: "\u62D2\u7EDD" }), _jsx(Button, { variant: "primary", disabled: review.isPending, onClick: () => { if (reviewTarget)
                                review.mutate({ target: reviewTarget, decision: "approve" }); }, children: review.isPending ? "处理中…" : "通过" })] })), children: [_jsx("p", { className: "subtle", children: "\u5BA1\u6838\u4F1A\u8BB0\u5F55\u64CD\u4F5C\u65E5\u5FD7\u5E76\u5F71\u54CD\u5BF9\u5E94\u95E8\u6237\u7684\u8BBF\u95EE\u8D44\u683C\u3002" }), _jsxs("label", { className: "form-label", htmlFor: "verify-note", children: ["\u5BA1\u6838\u5907\u6CE8 ", _jsx("span", { children: "\u9009\u586B" })] }), _jsx("textarea", { id: "verify-note", className: "field", rows: 2, value: note, onChange: (event) => setNote(event.target.value) })] })] }));
}
