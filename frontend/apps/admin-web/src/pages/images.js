import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useMutation, useQuery } from "@tanstack/react-query";
import { platformApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Breadcrumbs, Button, ConfirmDialog, Metric, Modal, Panel, RequestStateView, StatusBadge, useToast, } from "@edu/ui";
import { useEffect, useState } from "react";
import { apiErrorMessage } from "@/lib/format";
import { useRecentAuthGuard } from "@/lib/recent-auth";
const RISK_LABEL = {
    LOW: "低风险",
    MEDIUM: "中风险",
    HIGH: "高风险",
};
const SCAN_LABEL = {
    PENDING: "待扫描",
    CLEAN: "扫描干净",
    INFECTED: "检出风险",
    FAILED: "扫描失败",
};
const APPROVAL_LABEL = {
    PENDING: "待审批",
    APPROVED: "已批准",
    REJECTED: "已拒绝",
    RETIRED: "已下架",
};
const DIGEST_PATTERN = /sha256:[0-9a-f]{64}$/;
const TAG_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const imagesPollIntervalMs = 3000;
const imagesPollDeadlineMs = 120_000;
/* 支持粘贴 ubuntu:22.04 / org/repo:tag / registry.example.com/org/repo:tag，可带 @sha256: 摘要 */
function parseImageReference(raw) {
    const value = raw.trim().replace(/^https?:\/\//i, "");
    if (!value)
        return null;
    let digest = "";
    let main = value;
    const at = value.indexOf("@");
    if (at > 0) {
        digest = value.slice(at + 1);
        main = value.slice(0, at);
    }
    let registry = "docker.io";
    let rest = main;
    const slash = main.indexOf("/");
    if (slash > 0) {
        const head = main.slice(0, slash);
        if (head.includes(".") || head.includes(":") || head === "localhost") {
            registry = head;
            rest = main.slice(slash + 1);
        }
        else {
            // org/repo 形式：registry 仍是 docker.io，head 属于 repository 命名空间
            rest = main;
        }
    }
    let tag = "latest";
    let repository = rest;
    const colon = rest.lastIndexOf(":");
    if (colon > -1 && colon > rest.lastIndexOf("/")) {
        const candidate = rest.slice(colon + 1);
        if (TAG_PATTERN.test(candidate)) {
            tag = candidate;
            repository = rest.slice(0, colon);
        }
    }
    if (!repository)
        return null;
    return { registry, repository, tag, digest: DIGEST_PATTERN.test(digest) ? digest : "" };
}
const EMPTY_ADD_FORM = {
    quick: "",
    registry: "",
    repository: "",
    tag: "",
    digest: "",
    riskLevel: "LOW",
    reason: "",
};
function riskTone(risk) {
    if (risk === "LOW")
        return "good";
    if (risk === "MEDIUM")
        return "warn";
    if (risk === "HIGH")
        return "bad";
    return "neutral";
}
export function Images() {
    const toast = useToast();
    const recentAuth = useRecentAuthGuard();
    const [showAdd, setShowAdd] = useState(false);
    const [addForm, setAddForm] = useState(EMPTY_ADD_FORM);
    const [scanTarget, setScanTarget] = useState(null);
    const [scanForm, setScanForm] = useState({ scanStatus: "CLEAN", reportRef: "", risk: "LOW", reason: "" });
    const [decideTarget, setDecideTarget] = useState(null);
    const [pendingResolveId, setPendingResolveId] = useState(null);
    const [pendingReresolve, setPendingReresolve] = useState(null);
    const images = useQuery({ queryKey: keys.images({}), queryFn: () => platformApi.images({ page_size: 100 }) });
    const rows = images.data?.rows ?? [];
    const refresh = () => void images.refetch();
    const addImage = useMutation({
        mutationFn: () => platformApi.createImage({
            registry: addForm.registry,
            repository: addForm.repository,
            display_tag: addForm.tag || undefined,
            digest: addForm.digest.trim() || undefined,
            risk_level: addForm.riskLevel,
            reason: addForm.reason,
        }),
        onSuccess: () => {
            toast.notify("镜像已加入目录，等待解析 digest 与扫描");
            setAddForm(EMPTY_ADD_FORM);
            setShowAdd(false);
            refresh();
        },
        onError: (error) => {
            if (!recentAuth.intercept(error, () => addImage.mutate())) {
                toast.notify(apiErrorMessage(error), "error");
            }
        },
    });
    const resolveDigest = useMutation({
        mutationFn: (target) => platformApi.resolveImage(target.public_id, target.row_version),
        onSuccess: (_data, target) => {
            toast.notify("已提交解析任务，运行时正在拉取镜像并计算 sha256，首次可能较久");
            setPendingResolveId(target.public_id);
            refresh();
        },
        onError: (error, target) => {
            if (!recentAuth.intercept(error, () => resolveDigest.mutate(target))) {
                toast.notify(apiErrorMessage(error), "error");
            }
            refresh();
        },
    });
    const pendingRow = pendingResolveId ? rows.find((image) => image.public_id === pendingResolveId) : undefined;
    const pendingResolved = pendingRow?.digest != null;
    const pendingRejected = pendingRow?.approval_status === "REJECTED";
    useEffect(() => {
        if (!pendingResolveId)
            return;
        if (pendingResolved) {
            toast.notify("已解析出镜像 sha256 摘要，可进行扫描上报");
            setPendingResolveId(null);
            return;
        }
        if (pendingRejected) {
            toast.notify("解析完成：该镜像内容与目录中已批准的镜像相同，已自动拒绝此重复项", "error");
            setPendingResolveId(null);
            return;
        }
        const startedAt = Date.now();
        const timer = window.setInterval(() => {
            void images.refetch();
            if (Date.now() - startedAt > imagesPollDeadlineMs) {
                toast.notify("解析任务仍在进行，请稍后刷新查看结果或重新解析", "error");
                setPendingResolveId(null);
            }
        }, imagesPollIntervalMs);
        return () => window.clearInterval(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [pendingResolveId, pendingResolved, pendingRejected]);
    const reResolve = useMutation({
        mutationFn: (target) => platformApi.reResolveImage(target.public_id, target.row_version),
        onSuccess: (_data, target) => {
            toast.notify("已提交重新解析任务：摘要变化时扫描与审批会失效，请稍后重新扫描并批准");
            setPendingReresolve({ id: target.public_id, digest: target.digest ?? "", startedAt: Date.now() });
            refresh();
        },
        onError: (error, target) => {
            if (!recentAuth.intercept(error, () => reResolve.mutate(target))) {
                toast.notify(apiErrorMessage(error), "error");
            }
            refresh();
        },
    });
    useEffect(() => {
        if (!pendingReresolve)
            return;
        const row = rows.find((image) => image.public_id === pendingReresolve.id);
        if (row && pendingReresolve.digest && row.digest !== pendingReresolve.digest) {
            toast.notify("运行时摘要已更新：此前扫描与批准已失效，请重新扫描并批准", "error");
            setPendingReresolve(null);
            return;
        }
        const timer = window.setInterval(() => {
            void images.refetch();
            if (Date.now() - pendingReresolve.startedAt > imagesPollDeadlineMs) {
                toast.notify("重新解析任务仍在进行或摘要未变化，请稍后刷新确认", "error");
                setPendingReresolve(null);
            }
        }, imagesPollIntervalMs);
        return () => window.clearInterval(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [pendingReresolve, rows]);
    const reportScan = useMutation({
        mutationFn: (input) => platformApi.reportImageScan(input.target.public_id, {
            scan_status: input.form.scanStatus,
            ...(input.form.reportRef.trim() ? { scan_report_ref: input.form.reportRef.trim() } : {}),
            risk_level: input.form.risk,
            reason: input.form.reason,
        }, input.target.row_version),
        onSuccess: () => {
            toast.notify("扫描结果已登记");
            setScanTarget(null);
            refresh();
        },
        onError: (error, input) => {
            if (!recentAuth.intercept(error, () => reportScan.mutate(input))) {
                toast.notify(apiErrorMessage(error), "error");
            }
            refresh();
        },
    });
    const decide = useMutation({
        mutationFn: (input) => platformApi.decideImage(input.target.public_id, { decision: input.decision }, input.target.row_version),
        onSuccess: (_data, input) => {
            toast.notify(input.decision === "approve" ? "镜像已批准，教师端可选用" : "已拒绝镜像");
            setDecideTarget(null);
            refresh();
        },
        onError: (error, input) => {
            if (!recentAuth.intercept(error, () => decide.mutate(input))) {
                toast.notify(apiErrorMessage(error), "error");
            }
            refresh();
        },
    });
    const approvedCount = rows.filter((image) => image.approval_status === "APPROVED").length;
    const pendingCount = rows.filter((image) => image.approval_status === "PENDING").length;
    const unresolvedCount = rows.filter((image) => !image.digest).length;
    const applyQuickReference = () => {
        const parsed = parseImageReference(addForm.quick);
        if (!parsed)
            return;
        setAddForm({
            ...EMPTY_ADD_FORM,
            quick: addForm.quick,
            registry: parsed.registry,
            repository: parsed.repository,
            tag: parsed.tag,
            digest: parsed.digest,
            riskLevel: addForm.riskLevel,
            reason: addForm.reason,
        });
    };
    const canAdd = addForm.registry.trim().length > 0
        && addForm.repository.trim().length > 0
        && addForm.reason.trim().length > 0
        && (!addForm.digest.trim() || DIGEST_PATTERN.test(addForm.digest.trim()));
    const imageLabel = (image) => {
        const name = image.repository || image.public_id;
        return image.display_tag ? `${name} : ${image.display_tag}` : name;
    };
    return (_jsxs(_Fragment, { children: [_jsx(Breadcrumbs, { items: [{ label: "平台管理" }, { label: "资源治理" }], current: "\u955C\u50CF\u76EE\u5F55" }), _jsxs("div", { className: "page-actions align-end", children: [_jsx(Button, { onClick: refresh, ariaLabel: "\u5237\u65B0\u955C\u50CF\u5217\u8868", children: "\u5237\u65B0" }), _jsx(Button, { variant: "primary", onClick: () => { setAddForm(EMPTY_ADD_FORM); setShowAdd(true); }, children: "\u6DFB\u52A0\u955C\u50CF" })] }), _jsx(Panel, { className: "section", children: _jsx(RequestStateView, { loading: images.isLoading, error: images.error, onRetry: refresh, empty: false, emptyState: null, children: _jsxs("div", { className: "metric-strip", children: [_jsx(Metric, { label: "\u5DF2\u6279\u51C6\u955C\u50CF", value: String(approvedCount), icon: "boxes", sub: "\u6559\u5E08\u7AEF\u53EF\u9009" }), _jsx(Metric, { label: "\u5F85\u5BA1\u6279", value: String(pendingCount), icon: "gauge", sub: "\u7B49\u5F85\u626B\u63CF\u4E0E\u6279\u51C6" }), _jsx(Metric, { label: "\u5F85\u89E3\u6790 digest", value: String(unresolvedCount), icon: "monitor", sub: "\u89E3\u6790\u540E\u518D\u626B\u63CF" })] }) }) }), _jsx(Panel, { className: "section", title: _jsxs(_Fragment, { children: [_jsx("h2", { children: "\u955C\u50CF\u76EE\u5F55" }), _jsx("span", { className: "subtle", children: "\u6279\u51C6\u5E76\u626B\u63CF\u5E72\u51C0\u7684\u955C\u50CF\uFF0C\u6559\u5E08\u53EF\u5728\u5B9E\u9A8C\u6A21\u677F\u201C\u8FD0\u884C\u73AF\u5883\u201D\u4E2D\u9009\u62E9" })] }), children: _jsx(RequestStateView, { loading: images.isLoading, error: images.error, onRetry: refresh, empty: !rows.length, emptyState: _jsxs("div", { className: "state-block", children: [_jsx("strong", { children: "\u955C\u50CF\u76EE\u5F55\u4E3A\u7A7A" }), _jsx("p", { children: "\u6DFB\u52A0 ubuntu / python / jdk \u7B49\u5E38\u7528\u955C\u50CF\uFF0C\u6279\u51C6\u540E\u4F9B\u6559\u5E08\u521B\u5EFA\u5B9E\u9A8C\u6A21\u677F\u4F7F\u7528\u3002" })] }), children: _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "\u955C\u50CF" }), _jsx("th", { children: "Digest" }), _jsx("th", { children: "\u98CE\u9669" }), _jsx("th", { children: "\u626B\u63CF" }), _jsx("th", { children: "\u5BA1\u6279" }), _jsx("th", { children: "\u64CD\u4F5C" })] }) }), _jsx("tbody", { children: rows.map((image) => {
                                        const resolving = pendingResolveId === image.public_id || (resolveDigest.isPending && resolveDigest.variables?.public_id === image.public_id);
                                        const unresolved = !image.digest && image.approval_status !== "APPROVED";
                                        return (_jsxs("tr", { children: [_jsxs("td", { children: [_jsx("strong", { children: imageLabel(image) }), _jsx("small", { style: { display: "block" }, children: image.registry })] }), _jsx("td", { children: _jsx("small", { children: image.digest ? `${image.digest.slice(0, 18)}…` : _jsx("span", { className: "subtle", children: "\u672A\u89E3\u6790" }) }) }), _jsx("td", { children: _jsx(StatusBadge, { tone: riskTone(image.risk_level), children: RISK_LABEL[image.risk_level ?? ""] ?? "—" }) }), _jsx("td", { children: _jsx(StatusBadge, { tone: image.scan_status === "CLEAN" ? "good" : image.scan_status === "INFECTED" ? "bad" : "neutral", children: SCAN_LABEL[image.scan_status] ?? image.scan_status }) }), _jsx("td", { children: image.approval_status === "APPROVED"
                                                        ? _jsx(StatusBadge, { tone: "good", children: APPROVAL_LABEL[image.approval_status] })
                                                        : _jsx(StatusBadge, { tone: image.approval_status === "REJECTED" ? "bad" : "neutral", children: APPROVAL_LABEL[image.approval_status] ?? image.approval_status }) }), _jsx("td", { children: _jsxs("div", { className: "row-actions", children: [unresolved ? (_jsx(Button, { size: "sm", disabled: resolveDigest.isPending || pendingResolveId === image.public_id, onClick: () => resolveDigest.mutate(image), title: resolving ? "解析任务已在队列中，完成列表自动刷新" : "由平台经运行时拉取镜像并解析 sha256，首次可能较久", ariaLabel: `解析 ${imageLabel(image)} 的 digest`, children: resolving ? "解析中…" : "解析 digest" })) : null, image.digest && image.approval_status !== "RETIRED" ? (_jsx(Button, { size: "sm", disabled: reResolve.isPending || pendingReresolve?.id === image.public_id, onClick: () => reResolve.mutate(image), title: "\u8FD0\u884C\u65F6\u955C\u50CF\u91CD\u5EFA\u540E\u6458\u8981\u53EF\u80FD\u6F02\u79FB\uFF1A\u91CD\u65B0\u89E3\u6790\u4F1A\u5237\u65B0\u6458\u8981\u5E76\u4F7F\u626B\u63CF/\u5BA1\u6279\u5931\u6548", ariaLabel: `重新解析 ${imageLabel(image)} 的 digest`, children: pendingReresolve?.id === image.public_id ? "重新解析中…" : "重新解析" })) : null, image.approval_status !== "APPROVED" && image.approval_status !== "RETIRED" ? (_jsxs(_Fragment, { children: [_jsx(Button, { size: "sm", onClick: () => {
                                                                            setScanForm({ scanStatus: "CLEAN", reportRef: "", risk: image.risk_level ?? "LOW", reason: "" });
                                                                            setScanTarget(image);
                                                                        }, children: "\u626B\u63CF\u4E0A\u62A5" }), _jsx(Button, { size: "sm", variant: "primary", disabled: !image.digest, onClick: () => setDecideTarget({ image, decision: "approve" }), title: image.digest ? undefined : "需先解析 digest", children: "\u6279\u51C6" }), _jsx(Button, { size: "sm", variant: "danger", onClick: () => setDecideTarget({ image, decision: "reject" }), children: "\u62D2\u7EDD" })] })) : null, image.approval_status === "APPROVED" ? _jsx("span", { className: "subtle", children: "\u5DF2\u4E0A\u67B6" }) : null] }) })] }, image.public_id));
                                    }) })] }) }) }) }), _jsxs(Modal, { open: showAdd, onClose: () => setShowAdd(false), eyebrow: "\u955C\u50CF\u76EE\u5F55", title: "\u6DFB\u52A0\u5E38\u7528\u955C\u50CF", actions: (_jsxs(_Fragment, { children: [_jsx(Button, { onClick: () => setShowAdd(false), disabled: addImage.isPending, children: "\u53D6\u6D88" }), _jsx(Button, { variant: "primary", disabled: addImage.isPending || !canAdd, onClick: () => addImage.mutate(), children: addImage.isPending ? "提交中…" : "加入目录" })] })), children: [_jsx("p", { className: "subtle", children: "\u52A0\u5165\u76EE\u5F55\u540E\u5148\u201C\u89E3\u6790 digest\u201D\uFF0C\u518D\u201C\u626B\u63CF\u4E0A\u62A5\u201D\uFF0C\u6279\u51C6\u540E\u624D\u5BF9\u6559\u5E08\u53EF\u89C1\u3002" }), _jsxs("label", { className: "form-label", htmlFor: "image-quick", children: ["\u5FEB\u901F\u586B\u5199 ", _jsx("span", { children: "\u7C98\u8D34\u5B8C\u6574\u955C\u50CF\u540D\u81EA\u52A8\u62C6\u89E3" })] }), _jsx("div", { style: { display: "flex", gap: 8 }, children: _jsx("input", { id: "image-quick", className: "field", style: { flex: 1 }, placeholder: "\u5982 ubuntu:22.04 \u6216 registry.example.com/lab/jdk:17", value: addForm.quick, onChange: (event) => setAddForm((base) => ({ ...base, quick: event.target.value })), onBlur: applyQuickReference }) }), _jsx("label", { className: "form-label", htmlFor: "image-registry", children: "Registry" }), _jsx("input", { id: "image-registry", className: "field", placeholder: "docker.io", value: addForm.registry, onChange: (event) => setAddForm((base) => ({ ...base, registry: event.target.value })) }), _jsx("label", { className: "form-label", htmlFor: "image-repository", children: "Repository" }), _jsx("input", { id: "image-repository", className: "field", placeholder: "library/ubuntu", value: addForm.repository, onChange: (event) => setAddForm((base) => ({ ...base, repository: event.target.value })) }), _jsx("label", { className: "form-label", htmlFor: "image-tag", children: "\u6807\u7B7E\uFF08Tag\uFF09" }), _jsx("input", { id: "image-tag", className: "field", placeholder: "22.04\uFF0C\u7559\u7A7A\u6309 latest \u89E3\u6790", value: addForm.tag, onChange: (event) => setAddForm((base) => ({ ...base, tag: event.target.value })) }), _jsxs("label", { className: "form-label", htmlFor: "image-digest", children: ["Digest ", _jsx("span", { children: "\u9009\u586B\uFF0C\u53EF\u7559\u7A7A\u7531\u5E73\u53F0\u89E3\u6790" })] }), _jsx("input", { id: "image-digest", className: "field", placeholder: "sha256:\u2026\uFF08\u9009\u586B\uFF09", value: addForm.digest, onChange: (event) => setAddForm((base) => ({ ...base, digest: event.target.value })) }), !addForm.digest.trim() || DIGEST_PATTERN.test(addForm.digest.trim()) ? null : (_jsx("p", { className: "subtle", style: { color: "var(--danger, #c0392b)" }, children: "Digest \u9700\u5F62\u5982 sha256:64 \u4F4D\u5341\u516D\u8FDB\u5236\uFF0C\u6216\u7559\u7A7A\u7531\u5E73\u53F0\u89E3\u6790\u3002" })), _jsx("label", { className: "form-label", htmlFor: "image-risk", children: "\u98CE\u9669\u7B49\u7EA7" }), _jsxs("select", { id: "image-risk", className: "field", value: addForm.riskLevel, onChange: (event) => setAddForm((base) => ({ ...base, riskLevel: event.target.value })), children: [_jsx("option", { value: "LOW", children: "\u4F4E\u98CE\u9669" }), _jsx("option", { value: "MEDIUM", children: "\u4E2D\u98CE\u9669" }), _jsx("option", { value: "HIGH", children: "\u9AD8\u98CE\u9669" })] }), _jsx("label", { className: "form-label", htmlFor: "image-reason", children: "\u53D8\u66F4\u539F\u56E0" }), _jsx("textarea", { id: "image-reason", className: "field", rows: 2, placeholder: "\u4F8B\u5982\uFF1A\u57FA\u7840\u8BFE\u7A0B\u9700\u8981 ubuntu \u73AF\u5883", value: addForm.reason, onChange: (event) => setAddForm((base) => ({ ...base, reason: event.target.value })) })] }), _jsxs(Modal, { open: scanTarget != null, onClose: () => setScanTarget(null), eyebrow: "\u955C\u50CF\u6CBB\u7406", title: "\u4E0A\u62A5\u626B\u63CF\u7ED3\u679C", actions: (_jsxs(_Fragment, { children: [_jsx(Button, { onClick: () => setScanTarget(null), disabled: reportScan.isPending, children: "\u53D6\u6D88" }), _jsx(Button, { variant: "primary", disabled: reportScan.isPending || scanForm.reason.trim().length === 0, onClick: () => { if (scanTarget)
                                reportScan.mutate({ target: scanTarget, form: scanForm }); }, children: reportScan.isPending ? "提交中…" : "登记结果" })] })), children: [_jsx("p", { className: "subtle", children: "\u6279\u51C6\u955C\u50CF\u8981\u6C42\u626B\u63CF\u7ED3\u679C\u4E3A CLEAN\uFF1BINFECTED / FAILED \u7684\u955C\u50CF\u4E0D\u80FD\u6279\u51C6\u3002" }), _jsx("label", { className: "form-label", htmlFor: "scan-status", children: "\u626B\u63CF\u7ED3\u8BBA" }), _jsxs("select", { id: "scan-status", className: "field", value: scanForm.scanStatus, onChange: (event) => setScanForm((base) => ({ ...base, scanStatus: event.target.value })), children: [_jsx("option", { value: "CLEAN", children: "\u626B\u63CF\u5E72\u51C0\uFF08CLEAN\uFF09" }), _jsx("option", { value: "INFECTED", children: "\u68C0\u51FA\u98CE\u9669\uFF08INFECTED\uFF09" }), _jsx("option", { value: "FAILED", children: "\u626B\u63CF\u5931\u8D25\uFF08FAILED\uFF09" })] }), _jsxs("label", { className: "form-label", htmlFor: "scan-ref", children: ["\u626B\u63CF\u62A5\u544A\u5F15\u7528 ", _jsx("span", { children: "\u9009\u586B" })] }), _jsx("input", { id: "scan-ref", className: "field", placeholder: "\u5982 scanner/run-2026-10", value: scanForm.reportRef, onChange: (event) => setScanForm((base) => ({ ...base, reportRef: event.target.value })) }), _jsx("label", { className: "form-label", htmlFor: "scan-risk", children: "\u98CE\u9669\u7B49\u7EA7" }), _jsxs("select", { id: "scan-risk", className: "field", value: scanForm.risk, onChange: (event) => setScanForm((base) => ({ ...base, risk: event.target.value })), children: [_jsx("option", { value: "LOW", children: "\u4F4E\u98CE\u9669" }), _jsx("option", { value: "MEDIUM", children: "\u4E2D\u98CE\u9669" }), _jsx("option", { value: "HIGH", children: "\u9AD8\u98CE\u9669" })] }), _jsx("label", { className: "form-label", htmlFor: "scan-reason", children: "\u53D8\u66F4\u539F\u56E0" }), _jsx("textarea", { id: "scan-reason", className: "field", rows: 2, placeholder: "\u4F8B\u5982\uFF1A\u5DF2\u6309\u626B\u63CF\u6D41\u7A0B\u51FA\u5177\u62A5\u544A", value: scanForm.reason, onChange: (event) => setScanForm((base) => ({ ...base, reason: event.target.value })) })] }), _jsx(ConfirmDialog, { open: decideTarget != null, onClose: () => setDecideTarget(null), onConfirm: () => { if (decideTarget)
                    decide.mutate({ target: decideTarget.image, decision: decideTarget.decision }); }, tone: decideTarget?.decision === "approve" ? "primary" : "danger", busy: decide.isPending, title: decideTarget?.decision === "approve" ? "批准镜像？" : "拒绝镜像？", eyebrow: "\u955C\u50CF\u6CBB\u7406", confirmLabel: decideTarget?.decision === "approve" ? "批准" : "拒绝", description: decideTarget?.decision === "approve"
                    ? _jsx("p", { children: "\u6279\u51C6\u5E76\u4FDD\u6301\u626B\u63CF CLEAN \u540E\uFF0C\u6559\u5E08\u53EF\u5728\u5B9E\u9A8C\u6A21\u677F\u4E2D\u9009\u62E9\u8BE5\u955C\u50CF\u3002" })
                    : _jsx("p", { children: "\u62D2\u7EDD\u540E\u8BE5\u955C\u50CF\u4E0D\u53EF\u88AB\u6559\u5E08\u4F7F\u7528\uFF0C\u4E4B\u540E\u4ECD\u53EF\u91CD\u65B0\u8D70\u626B\u63CF\u4E0E\u6279\u51C6\u6D41\u7A0B\u3002" }) }), recentAuth.dialog] }));
}
