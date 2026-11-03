import { newIdempotencyKey, request } from "@edu/auth-client";
export * from "./types";
function normalizeTask(raw) {
    const base = { ...raw };
    base.public_id = raw.public_id != null ? String(raw.public_id) : "";
    base.title = raw.title ?? "";
    base.status = raw.status ?? "ASSIGNED";
    // 契约对齐：row_version 实测是数字；动作枚举实测是大写（ENTER / REQUEST_EXTENSION）。
    // 统一转字符串与小写，供 allowed_actions.includes("enter") 等小写判断使用。
    base.row_version = raw.row_version != null ? String(raw.row_version) : "";
    base.allowed_actions = Array.isArray(raw.allowed_actions)
        ? raw.allowed_actions.map((action) => String(action).toLowerCase())
        : [];
    base.blockers = Array.isArray(raw.blockers) ? raw.blockers : [];
    base.progress = typeof raw.progress === "number" ? raw.progress : 0;
    base.current_failure = raw.current_failure != null && typeof raw.current_failure === "object"
        ? raw.current_failure
        : null;
    if (raw.provisioning === undefined)
        base.provisioning = null;
    return base;
}
function taskListEnvelope(envelope) {
    const list = toList(envelope);
    return { ...list, rows: list.rows.map(normalizeTask) };
}
function taskEnvelope(envelope) {
    return { ...envelope, data: normalizeTask(envelope.data ?? {}) };
}
/**
 * 工作台聚合归一（真实契约：task / content / template / tests / workspace / submission）：
 * - task 沿用 normalizeTask（动作转小写等）
 * - 章节列表缺省时，由 content.steps 或 content.description 派生一个可用章节，避免左侧空白
 * - tests 实测为对象（public_count/count/summary/recent_execution），summary 才是用例列表；
 *   聚合归一为页面使用的数组
 */
function normalizeWorkbenchAggregate(data) {
    if (data == null || typeof data !== "object") {
        return { task: normalizeTask({}), chapters: [] };
    }
    const content = data.content;
    let chapters = Array.isArray(data.chapters) ? data.chapters : [];
    if (!chapters.length && Array.isArray(content?.steps) && content?.steps?.length) {
        chapters = content.steps.map((step, index) => ({
            public_id: String(step["public_id"] ?? `step-${index}`),
            title: String(step["title"] ?? step["name"] ?? `步骤 ${index + 1}`),
            description: step["description"] != null ? String(step["description"]) : null,
            sort_order: index,
            instructions: Array.isArray(step["instructions"])
                ? step["instructions"].map((item) => String(item))
                : undefined,
        }));
    }
    if (!chapters.length) {
        chapters = [{
                public_id: "chapter-current",
                title: data.task?.title ?? "实验内容",
                description: content?.description ?? null,
                sort_order: 0,
            }];
    }
    const rawTests = data.tests;
    let testsList;
    if (Array.isArray(rawTests)) {
        testsList = rawTests;
    }
    else if (rawTests != null && typeof rawTests === "object") {
        const summary = rawTests.summary;
        if (Array.isArray(summary)) {
            testsList = summary.map((item, index) => {
                const entry = item;
                return {
                    key: entry["key"] != null ? String(entry["key"]) : String(index),
                    name: String(entry["name"] ?? entry["title"] ?? `测试用例 ${index + 1}`),
                    description: entry["description"] != null ? String(entry["description"]) : undefined,
                };
            });
        }
    }
    else {
        testsList = undefined;
    }
    const rawTemplate = data.template;
    let templateCaps = null;
    if (rawTemplate != null && typeof rawTemplate === "object") {
        const rawCaps = rawTemplate.workspace_capabilities;
        if (rawCaps != null && typeof rawCaps === "object") {
            templateCaps = Object.fromEntries(Object.entries(rawCaps)
                .filter((entry) => typeof entry[1] === "boolean")
                .map((entry) => [entry[0], entry[1]]));
        }
    }
    return {
        ...data,
        task: data.task ? normalizeTask(data.task) : data.task,
        chapters,
        tests: testsList,
        template_caps: templateCaps,
    };
}
function toList(envelope) {
    // 契约对齐：部分列表接口（如 GET /tasks/{id}/checkpoints）的 data 是
    // `{ items: [...], current_version, ... }` 包装而非纯数组；统一取 items。
    const raw = envelope.data;
    let rows;
    if (Array.isArray(raw)) {
        rows = raw;
    }
    else if (raw != null && typeof raw === "object" && Array.isArray(raw.items)) {
        rows = raw.items;
    }
    else {
        rows = [];
    }
    return {
        rows: rows,
        page: typeof envelope.meta?.page === "number" ? envelope.meta.page : 1,
        pageSize: typeof envelope.meta?.page_size === "number" ? envelope.meta.page_size : 20,
        total: typeof envelope.meta?.total === "number" ? envelope.meta.total : rows.length,
        traceId: envelope.meta?.trace_id,
    };
}
/* ══════════ 认证与个人 ══════════ */
export const meApi = {
    retrieve: () => request("/me").then((r) => r.data),
    context: () => request("/context").then((r) => r.data),
    updateProfile: (payload, ifMatch) => request("/me", { method: "PATCH", body: payload, ifMatch }).then((r) => r.data),
    notifications: (query) => request("/notifications", { query }).then(toList),
    markNotificationRead: (id) => request(`/notifications/${id}/read`, { method: "POST", body: {} }).then((r) => r.data),
    /* 平台端敏感写操作要求"近期认证"：提交密码刷新会话认证时间 */
    stepUpSession: (password, reuseKey) => request("/auth/session/step-up", {
        method: "POST",
        body: { password },
        idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),
};
/* ══════════ 学生端 ══════════ */
export const studentApi = {
    dashboard: () => request("/me/dashboard").then((r) => r.data),
    courses: (query) => request("/courses", { query }).then(toList),
    myEnrollments: (query) => request("/me/enrollments", { query }).then(toList),
    coursesResource: (courseId, resource, query) => request(`/courses/${courseId}/${resource}`, { query }).then(toList),
    courseDetail: (courseId) => request(`/courses/${courseId}`).then((r) => r.data),
    courseChapters: (courseId) => request(`/courses/${courseId}/chapters`).then(toList),
    courseMaterials: (courseId) => request(`/courses/${courseId}/materials`).then(toList),
    courseAnnouncements: (courseId) => request(`/courses/${courseId}/announcements`).then(toList),
    courseCalendarEvents: (courseId, query) => request(`/courses/${courseId}/calendar-events`, { query }).then(toList),
    /** 加入课程（需要幂等键；APPROVAL 课程提交申请，OPEN 课程直接加入） */
    joinCourse: (courseId, payload, reuseKey) => request(`/courses/${courseId}/enrollments`, { method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey() }).then((r) => r.data),
    dropEnrollment: (enrollmentId, ifMatch, reuseKey) => request(`/me/enrollments/${enrollmentId}/withdraw`, {
        method: "POST", body: {}, idempotencyKey: reuseKey, ifMatch,
    }).then((r) => r.data),
};
/* ══════════ 学生任务 ══════════ */
export const taskApi = {
    list: (query) => request("/tasks", { query }).then(taskListEnvelope),
    detail: (taskId) => request(`/tasks/${taskId}`).then((r) => taskEnvelope(r).data),
    transitions: (taskId) => request(`/tasks/${taskId}/transitions`).then((r) => r.data),
    start: (taskId, ifMatch, reuseKey) => request(`/tasks/${taskId}/start`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then(taskEnvelope).then((r) => r.data),
    enter: (taskId, ifMatch, reuseKey) => request(`/tasks/${taskId}/enter`, {
        method: "POST",
        body: {},
        idempotencyKey: reuseKey ?? newIdempotencyKey(),
        ifMatch,
    }).then((r) => r.data)
        .then((data) => ({ ...data, task: data?.task ? normalizeTask(data.task) : data?.task })),
    provisioningJob: (taskId) => request(`/tasks/${taskId}/provisioning-job`).then((r) => r.data),
    cancelProvisioning: (taskId, ifMatch, reuseKey) => request(`/tasks/${taskId}/provisioning-job/cancel`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    extensions: (taskId) => request(`/tasks/${taskId}/extensions`).then(toList),
    requestExtension: (taskId, payload, ifMatch, reuseKey) => request(`/tasks/${taskId}/extension-requests`, {
        method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    retry: (taskId, ifMatch, reuseKey) => request(`/tasks/${taskId}/retry`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then(taskEnvelope).then((r) => r.data),
    complete: (taskId, ifMatch, reuseKey) => request(`/tasks/${taskId}/complete`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then(taskEnvelope).then((r) => r.data),
};
export const workspaceApi = {
    workbench: (taskId) => request(`/tasks/${taskId}/workbench`)
        .then((r) => r.data)
        .then((data) => normalizeWorkbenchAggregate(data)),
    createSession: (taskId, reuseKey) => request(`/tasks/${taskId}/workspace-sessions`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),
    renewSession: (sessionId, workspaceToken, reuseKey) => request(`/workspace-sessions/${sessionId}/renew`, {
        method: "POST",
        body: {},
        idempotencyKey: reuseKey ?? newIdempotencyKey(),
        headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined,
    }).then((r) => r.data),
    revokeSession: (sessionId, workspaceToken, reuseKey) => request(`/workspace-sessions/${sessionId}/revoke`, {
        method: "POST",
        body: {},
        idempotencyKey: reuseKey ?? newIdempotencyKey(),
        headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined,
    }).then((r) => r.data),
    saveSnapshot: (taskId, payload, workspaceToken, reuseKey) => request(`/tasks/${taskId}/workspace-snapshot`, {
        method: "PUT",
        body: payload,
        idempotencyKey: reuseKey ?? newIdempotencyKey(),
        headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined,
    }).then((r) => r.data),
    checkpoints: (taskId, workspaceToken) => request(`/tasks/${taskId}/checkpoints`, { headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined }).then((envelope) => {
        const raw = envelope.data;
        return {
            rows: Array.isArray(raw?.items) ? raw.items : [],
            currentVersion: typeof raw?.current_version === "number" ? raw.current_version : 0,
            sessionRowVersion: typeof raw?.row_version === "number" ? raw.row_version : 0,
        };
    }),
    createCheckpoint: (taskId, payload, workspaceToken, reuseKey) => request(`/tasks/${taskId}/checkpoints`, {
        method: "POST",
        body: payload,
        idempotencyKey: reuseKey ?? newIdempotencyKey(),
        headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined,
    }).then((r) => r.data),
    restoreCheckpoint: (taskId, checkpointId, ifMatch, workspaceToken, reuseKey) => request(`/tasks/${taskId}/checkpoints/${checkpointId}/restore`, {
        method: "POST",
        body: {},
        idempotencyKey: reuseKey ?? newIdempotencyKey(),
        ifMatch,
        headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined,
    }).then((r) => r.data),
    executionRuns: (taskId, query, workspaceToken) => request(`/tasks/${taskId}/execution-runs`, {
        query,
        headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined,
    }).then(toList),
    executionRun: (taskId, runId, workspaceToken) => request(`/tasks/${taskId}/execution-runs/${runId}`, {
        headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined,
    }).then((r) => r.data),
    createExecutionRun: (taskId, payload, workspaceToken, reuseKey) => request(`/tasks/${taskId}/execution-runs`, {
        method: "POST",
        body: payload,
        idempotencyKey: reuseKey ?? newIdempotencyKey(),
        headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined,
    }).then((r) => r.data),
    stopRuntime: (runtimeId, reuseKey) => request(`/student/task-runtimes/${runtimeId}/stop`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),
};
/* ══════════ 报告 ══════════ */
export const reportApi = {
    draft: (taskId) => request(`/tasks/${taskId}/report-draft`).then((r) => r.data),
    saveDraft: (taskId, payload, ifMatch) => request(`/tasks/${taskId}/report-draft`, {
        method: "PUT", body: payload, idempotencyKey: newIdempotencyKey(), ifMatch,
    }),
    reportVersions: (taskId) => request(`/tasks/${taskId}/report-versions`).then(toList),
    attachments: (taskId) => request(`/tasks/${taskId}/attachments`).then((r) => r.data),
    uploadAttachment: (taskId, reuseKey) => request(`/tasks/${taskId}/attachments`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),
    createDownloadGrant: (assetId, reuseKey) => request(`/files/${assetId}/download-grants`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),
    submitReport: (taskId, reuseKey, ifMatch) => request(`/tasks/${taskId}/submit-report`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    reviewResult: (taskId) => request(`/tasks/${taskId}/review-result`).then((r) => r.data),
};
/* ══════════ 教师端 ══════════ */
/* ══════════ 评审详情归一 ══════════ */
function escapeReportHtml(value) {
    return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
/* 后端 review_detail_data 契约：
 - 评分标准在 scores.criteria（rubric/{version}/criteria），后端没有 rubric 字段；criteria 里同条目回带已存 score
 - submission 是 { kind, version | artifact }，报告正文在 version.body_markdown（markdown 而非 html）
 - annotations 用 public_id/status；status != ACTIVE 视为已撤销 */
function normalizeReviewDetail(raw) {
    const base = (raw ?? {});
    const scores = base["scores"];
    const submission = base["submission"];
    const reportVersion = submission?.["version"];
    const reportMarkdown = typeof reportVersion?.["body_markdown"] === "string" ? reportVersion["body_markdown"] : "";
    const criteria = (scores?.["criteria"] ?? []);
    const annotations = (base["annotations"] ?? []);
    return {
        ...base,
        rubric: {
            criteria: criteria.map((row) => ({
                public_id: String(row["public_id"] ?? ""),
                title: String(row["title"] ?? ""),
                description: row["description"] != null ? String(row["description"]) : undefined,
                max_score: Number(row["max_score"] ?? 0),
                score: row["score"] != null ? Number(row["score"]) : null,
            })),
        },
        scores: criteria
            .filter((row) => row["score"] != null)
            .map((row) => ({ criterion_id: String(row["public_id"] ?? ""), score: Number(row["score"]) })),
        submission: {
            report_id: reportVersion?.["public_id"] != null ? String(reportVersion["public_id"]) : undefined,
            report_html: reportMarkdown ? `<pre>${escapeReportHtml(reportMarkdown)}</pre>` : undefined,
            report_markdown: reportMarkdown || undefined,
        },
        annotations: annotations.map((row) => ({
            id: String(row["public_id"] ?? ""),
            body: String(row["body"] ?? ""),
            revoked: row["status"] !== "ACTIVE",
        })),
        row_version: String(base["row_version"] ?? ""),
    };
}
export const teachingApi = {
    courses: (query) => request("/teaching/courses", { query }).then(toList),
    course: (courseId) => request(`/teaching/courses/${courseId}`).then((r) => r.data),
    createCourse: (payload, reuseKey) => request("/teaching/courses", {
        method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),
    publishCourse: (courseId, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/publish`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    courseResource: (courseId, resource, query) => request(`/teaching/courses/${courseId}/${resource}`, { query }).then(toList),
    enrollments: (courseId, query) => request(`/teaching/courses/${courseId}/enrollments`, { query }).then(toList),
    reviewEnrollment: (courseId, enrollmentId, payload, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/enrollments/${enrollmentId}/review`, {
        method: "POST",
        // 后端 EnrollmentReviewSerializer 仅收大写 APPROVE/REJECT，备注字段为 note
        body: {
            decision: payload.decision.toUpperCase(),
            ...(payload.decision_note != null ? { note: payload.decision_note } : {}),
        },
        idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    imports: {
        precheck: (courseId, payload, reuseKey) => request(`/teaching/courses/${courseId}/enrollment-imports/precheck`, {
            method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(),
        }).then((r) => r.data),
        get: (courseId, jobId) => request(`/teaching/courses/${courseId}/enrollment-imports/${jobId}`).then((r) => r.data),
    },
    // 模板
    templates: (courseId, query) => request(`/teaching/courses/${courseId}/templates`, { query }).then(toList),
    createTemplate: (courseId, payload, reuseKey) => request(`/teaching/courses/${courseId}/templates`, {
        method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),
    deleteTemplate: (courseId, templateId, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/templates/${templateId}`, {
        method: "DELETE", idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    templateVersions: (courseId, templateId) => request(`/teaching/courses/${courseId}/templates/${templateId}/versions`).then(toList),
    createTemplateVersion: (courseId, templateId, payload, reuseKey) => request(`/teaching/courses/${courseId}/templates/${templateId}/versions`, {
        method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),
    templateVersion: (courseId, versionId) => request(`/teaching/courses/${courseId}/template-versions/${versionId}`).then((r) => r.data),
    updateTemplateVersion: (courseId, versionId, payload, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/template-versions/${versionId}`, {
        method: "PATCH", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    templateChapters: (courseId, versionId) => request(`/teaching/courses/${courseId}/template-versions/${versionId}/chapters`).then(toList),
    createTemplateChapter: (courseId, versionId, payload, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/template-versions/${versionId}/chapters`, {
        method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    createTemplateTask: (courseId, chapterId, payload, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/template-chapters/${chapterId}/tasks`, {
        method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    reorderChapters: (courseId, versionId, payload, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/template-versions/${versionId}/chapters/reorder`, {
        method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    templateChapterTasks: (courseId, chapterId) => request(`/teaching/courses/${courseId}/template-chapters/${chapterId}/tasks`).then(toList),
    templateOptions: (courseId) => request(`/teaching/courses/${courseId}/template-options`).then((r) => r.data),
    // 镜像
    experimentImages: (courseId) => request(`/teaching/courses/${courseId}/experiment-images`).then(toList),
    prepareImage: (courseId, imageId, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/experiment-images/${imageId}/prepare`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    imageEvents: (courseId, imageId) => request(`/teaching/courses/${courseId}/experiment-images/${imageId}/events`).then(toList),
    // 预检与发布
    precheck: (courseId, versionId, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/template-versions/${versionId}/precheck`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    precheckRuns: (courseId, versionId) => request(`/teaching/courses/${courseId}/template-versions/${versionId}/precheck-runs`).then(toList),
    publishTemplateVersion: (courseId, versionId, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/template-versions/${versionId}/publish`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    saveExecutionSpec: (courseId, versionId, payload, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/template-versions/${versionId}/execution-spec`, {
        method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    publications: (courseId, query) => request(`/teaching/courses/${courseId}/experiments`, { query }).then(toList),
    createPublication: (courseId, payload, reuseKey) => request(`/teaching/courses/${courseId}/experiments`, {
        method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),
    publication: (courseId, publicationId) => request(`/teaching/courses/${courseId}/experiments/${publicationId}`).then((r) => r.data),
    updatePublication: (courseId, publicationId, payload, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/experiments/${publicationId}`, {
        method: "PATCH", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    publishPublication: (courseId, publicationId, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/experiments/${publicationId}/publish`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    withdrawPublication: (courseId, publicationId, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/experiments/${publicationId}/withdraw`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    closePublication: (courseId, publicationId, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/experiments/${publicationId}/close`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    publicationTasks: (courseId, publicationId, query) => request(`/teaching/courses/${courseId}/experiments/${publicationId}/tasks`, { query }).then(taskListEnvelope),
    // 选课与邀请
    invitations: (courseId) => request(`/teaching/courses/${courseId}/invitations`).then(toList),
    createInvitation: (courseId, payload = {}, reuseKey) => {
        // The API contract (InvitationWrite) requires max_uses + expires_at; map
        // the UI-facing knobs onto it so calls never send unsupported fields.
        const body = {
            max_uses: payload.max_uses ?? payload.usage_limit ?? 20,
            expires_at: payload.expires_at ??
                new Date(Date.now() + (payload.valid_days ?? 30) * 86_400_000).toISOString(),
        };
        return request(`/teaching/courses/${courseId}/invitations`, {
            method: "POST",
            body,
            idempotencyKey: reuseKey ?? newIdempotencyKey(),
        }).then((r) => r.data);
    },
    // 学生过程
    progress: (courseId, query) => request(`/teaching/courses/${courseId}/progress`, { query }).then(taskListEnvelope),
    studentTaskWorkspace: (courseId, taskId) => request(`/teaching/courses/${courseId}/tasks/${taskId}/workspace`).then((r) => r.data),
    operationReplay: (courseId, taskId) => request(`/teaching/courses/${courseId}/tasks/${taskId}/operation-replay`).then(toList),
    // 评审
    reviews: (courseId, query) => request(`/teaching/courses/${courseId}/reviews`, { query }).then(toList),
    rubrics: (courseId) => request(`/teaching/courses/${courseId}/rubrics`).then(toList),
    review: (courseId, reviewId) => request(`/teaching/courses/${courseId}/reviews/${reviewId}`)
        .then((r) => r.data)
        .then(normalizeReviewDetail),
    saveCriterionScores: (courseId, reviewId, payload, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/reviews/${reviewId}/criterion-scores`, {
        method: "PUT", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    addAnnotation: (courseId, reviewId, payload, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/reviews/${reviewId}/annotations`, {
        method: "POST",
        // 契约 AnnotationWriteSerializer：target_type/target_ref/anchor 必填
        body: { target_type: "REPORT_TEXT", target_ref: payload.target_ref, anchor: payload.anchor, body: payload.body },
        idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    revokeAnnotation: (courseId, annotationId, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/annotations/${annotationId}/revoke`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    decideReview: (courseId, reviewId, payload, ifMatch, reuseKey) => request(`/teaching/courses/${courseId}/reviews/${reviewId}/decide`, {
        method: "POST",
        // 后端 ReviewDecisionEnum 仅收大写 APPROVE/REJECT；页面语义 return(退回修改)对应 REJECT
        body: {
            decision: payload.decision === "approve" ? "APPROVE" : "REJECT",
            ...(payload.note ? { feedback: payload.note } : {}),
        },
        idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    startSimilarityRun: (courseId, taskId, reuseKey) => request(`/teaching/courses/${courseId}/similarity-runs`, {
        method: "POST", body: { task_id: taskId }, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),
    submissionPreview: (courseId, taskId) => request(`/teaching/courses/${courseId}/tasks/${taskId}/submission-preview`).then((r) => r.data),
    // 分析
    analytics: (courseId, section) => request(`/teaching/courses/${courseId}/analytics/${section}`).then((r) => r.data),
    analyticsSeries: (courseId, days) => request(`/teaching/courses/${courseId}/analytics/series`, { query: days ? { days } : undefined }).then((r) => r.data),
    riskSignals: (courseId) => request(`/teaching/courses/${courseId}/analytics/risk-signals`).then(toList),
};
/* ══════════ 平台端 ══════════ */
export const platformApi = {
    users: (query) => request("/platform/users", { query }).then(toList),
    verifications: (query) => request("/platform/verifications", { query }).then(toList),
    reviewVerification: (id, payload, ifMatch, reuseKey) => request(`/platform/verifications/${id}/review`, {
        method: "POST",
        // 后端 IdentityReviewSerializer 仅收大写 APPROVE/REJECT，备注字段为 reason
        body: {
            decision: payload.decision.toUpperCase(),
            ...(payload.note != null ? { reason: payload.note } : {}),
        },
        idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    governanceAlerts: (query) => request("/platform/governance/alerts", { query }).then(toList),
    governanceUsage: () => request("/platform/governance/usage").then((r) => r.data),
    courses: (query) => request("/platform/courses", { query }).then(toList),
    freezeCourse: (courseId, payload, ifMatch, reuseKey) => request(`/platform/courses/${courseId}/freeze`, {
        method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    precheckSummary: () => request("/platform/template-prechecks/summary").then((r) => r.data),
    images: (query) => request("/platform/images", { query }).then(toList),
    decideImage: (imageId, payload, ifMatch, reuseKey) => request(`/platform/images/${imageId}/decide`, {
        method: "POST",
        // 后端 decide_image 仅收大写 APPROVED/REJECTED，备注字段为 reason
        body: {
            decision: payload.decision === "approve" ? "APPROVED" : "REJECTED",
            ...(payload.note != null ? { reason: payload.note } : {}),
        },
        idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    createImage: (payload, reuseKey) => request("/platform/images", {
        method: "POST",
        body: {
            registry: payload.registry,
            repository: payload.repository,
            ...(payload.display_tag ? { display_tag: payload.display_tag } : {}),
            ...(payload.digest ? { digest: payload.digest } : {}),
            risk_level: payload.risk_level,
            reason: payload.reason,
        },
        idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),
    resolveImage: (imageId, ifMatch, reuseKey) => request(`/platform/images/${imageId}/resolve`, {
        method: "POST",
        body: {},
        idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    /* 镜像在运行时重建后摘要漂移:重新向运行时解析当前摘要(后台任务) */
    reResolveImage: (imageId, ifMatch, reuseKey) => request(`/platform/images/${imageId}/re-resolve`, {
        method: "POST",
        body: {},
        idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    reportImageScan: (imageId, payload, ifMatch, reuseKey) => request(`/platform/images/${imageId}`, {
        method: "PATCH",
        // 后端仅收大写 CLEAN/INFECTED/FAILED
        body: {
            scan_status: payload.scan_status.toUpperCase(),
            ...(payload.scan_report_ref ? { scan_report_ref: payload.scan_report_ref } : {}),
            risk_level: payload.risk_level,
            reason: payload.reason,
        },
        idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    resourceProfiles: (query) => request("/platform/resource-profiles", { query }).then(toList),
    runtimeAdapters: () => request("/platform/runtime-adapters").then(toList),
    quotas: (query) => request("/platform/quotas", { query }).then(toList),
    compensations: (query) => request("/platform/compensations", { query }).then(toList),
    retryCompensation: (compensationId, payload, ifMatch, reuseKey) => request("/platform/compensations", {
        method: "POST",
        body: { compensation_id: compensationId, ...payload },
        idempotencyKey: reuseKey ?? newIdempotencyKey(),
        ifMatch,
    }).then((r) => r.data),
    instances: (query) => request("/platform/instances", { query }).then(toList),
    destroyInstance: (instanceId, ifMatch, reuseKey) => request(`/platform/instances/${instanceId}/destroy`, {
        method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
    workspaceSessions: (query) => request("/platform/workspaces/sessions", { query }).then(toList),
    anomalies: (query) => request("/platform/tasks/anomalies", { query }).then(toList),
    scanAnomalies: (query) => request("/platform/reports/scan-anomalies", { query }).then(toList),
    operationsOverview: () => request("/platform/operations/overview").then((r) => r.data),
    operationLogs: (query) => request("/platform/operations/logs", { query }).then(toList),
    agentModelRoutes: () => request("/platform/agent/model-routes").then(toList),
    agentToolPolicies: () => request("/platform/agent/tool-policies").then(toList),
    agentUsageCosts: (query) => request("/platform/agent/usage-costs", { query }).then(toList),
};
