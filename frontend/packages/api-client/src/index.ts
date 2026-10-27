import { newIdempotencyKey, request } from "@edu/auth-client";
import type { EnvelopeSuccess } from "@edu/auth-client";
import type {
  Anomaly, Announcement, CalendarEvent, Checkpoint, CheckpointList, Chapter, Compensation, Course,
  Enrollment, ExecutionRun, ImportJob, Instance as InstanceData, Invitation, Material, Me,
  ModelRoute, NotificationItem, OperationLog, OperationsOverview, PlatformImage, PlatformUser,
  PortalContext, PrecheckRun, Publication, Quota, ReportDraft, ResourceProfile, ReviewDetail,
  ReviewSummary, Rubric, RuntimeAdapter, StudentDashboard, Task, TeachingCourseList, Template,
  TemplateChapter, TemplateTask, ToolPolicy, TemplateVersion, UsageCost, Verification,
  WorkspaceSession,
} from "./types";

export * from "./types";

function normalizeTask(raw: Partial<Task>): Task {
  const base = ({ ...raw } as unknown) as Task;
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
    ? (raw.current_failure as Task["current_failure"])
    : null;
  if (raw.provisioning === undefined) base.provisioning = null;
  return base;
}

function taskListEnvelope(envelope: EnvelopeSuccess<Partial<Task>[]>): ListEnvelope<Task> {
  const list = toList<Partial<Task>>(envelope);
  return { ...list, rows: list.rows.map(normalizeTask) };
}

function taskEnvelope(envelope: EnvelopeSuccess<Partial<Task>>): EnvelopeSuccess<Task> {
  return { ...envelope, data: normalizeTask(envelope.data ?? {}) } as EnvelopeSuccess<Task>;
}

/**
 * 工作台聚合归一（真实契约：task / content / template / tests / workspace / submission）：
 * - task 沿用 normalizeTask（动作转小写等）
 * - 章节列表缺省时，由 content.steps 或 content.description 派生一个可用章节，避免左侧空白
 * - tests 实测为对象（public_count/count/summary/recent_execution），summary 才是用例列表；
 *   聚合归一为页面使用的数组
 */
function normalizeWorkbenchAggregate(data: WorkbenchAggregate | undefined | null): WorkbenchAggregate {
  if (data == null || typeof data !== "object") {
    return { task: normalizeTask({}), chapters: [] };
  }
  const content = data.content as { description?: string | null; steps?: Array<Record<string, unknown>> } | null;
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
  const rawTests = data.tests as unknown;
  let testsList: Array<{ key?: string; name: string; description?: string }> | undefined;
  if (Array.isArray(rawTests)) {
    testsList = rawTests as Array<{ key?: string; name: string; description?: string }>;
  } else if (rawTests != null && typeof rawTests === "object") {
    const summary = (rawTests as { summary?: unknown }).summary;
    if (Array.isArray(summary)) {
      testsList = summary.map((item, index) => {
        const entry = item as Record<string, unknown>;
        return {
          key: entry["key"] != null ? String(entry["key"]) : String(index),
          name: String(entry["name"] ?? entry["title"] ?? `测试用例 ${index + 1}`),
          description: entry["description"] != null ? String(entry["description"]) : undefined,
        };
      });
    }
  } else {
    testsList = undefined;
  }
  return {
    ...data,
    task: data.task ? normalizeTask(data.task) : (data.task as never),
    chapters,
    tests: testsList,
  };
}

export interface ListEnvelope<T> {
  rows: T[];
  page: number;
  pageSize: number;
  total: number;
  traceId?: string;
}

function toList<T>(envelope: EnvelopeSuccess<T[]>): ListEnvelope<T> {
  // 契约对齐：部分列表接口（如 GET /tasks/{id}/checkpoints）的 data 是
  // `{ items: [...], current_version, ... }` 包装而非纯数组；统一取 items。
  const raw = envelope.data as unknown;
  let rows: unknown[];
  if (Array.isArray(raw)) {
    rows = raw;
  } else if (raw != null && typeof raw === "object" && Array.isArray((raw as { items?: unknown[] }).items)) {
    rows = (raw as { items: unknown[] }).items;
  } else {
    rows = [];
  }
  return {
    rows: rows as T[],
    page: typeof envelope.meta?.page === "number" ? envelope.meta.page : 1,
    pageSize: typeof envelope.meta?.page_size === "number" ? envelope.meta.page_size : 20,
    total: typeof envelope.meta?.total === "number" ? envelope.meta.total : rows.length,
    traceId: envelope.meta?.trace_id,
  };
}

/* ══════════ 认证与个人 ══════════ */

export const meApi = {
  retrieve: () => request<Me>("/me").then((r) => r.data),
  context: () => request<PortalContext>("/context").then((r) => r.data),
  updateProfile: (payload: { display_name?: string }, ifMatch?: string) =>
    request<Me>("/me", { method: "PATCH", body: payload, ifMatch }).then((r) => r.data),
  notifications: (query?: { page?: number; page_size?: number; unread?: boolean }) =>
    request<NotificationItem[]>("/notifications", { query }).then(toList),
  markNotificationRead: (id: string) =>
    request(`/notifications/${id}/read`, { method: "POST", body: {} }).then((r) => r.data),
};

/* ══════════ 学生端 ══════════ */

export const studentApi = {
  dashboard: () => request<StudentDashboard>("/me/dashboard").then((r) => r.data),

  courses: (query?: { page?: number; page_size?: number; search?: string }) =>
    request<Course[]>("/courses", { query }).then(toList),

  myEnrollments: (query?: { page?: number; page_size?: number; status?: string }) =>
    request<Enrollment[]>("/me/enrollments", { query }).then(toList),

  coursesResource: <T>(courseId: string, resource: "chapters" | "materials" | "announcements" | "calendar-events" | "questions", query?: { page?: number; page_size?: number }) =>
    request<T[]>(`/courses/${courseId}/${resource}`, { query }).then(toList),

  courseDetail: (courseId: string) => request<Course>(`/courses/${courseId}`).then((r) => r.data),

  courseChapters: (courseId: string) =>
    request<Chapter[]>(`/courses/${courseId}/chapters`).then(toList),

  courseMaterials: (courseId: string) =>
    request<Material[]>(`/courses/${courseId}/materials`).then(toList),

  courseAnnouncements: (courseId: string) =>
    request<Announcement[]>(`/courses/${courseId}/announcements`).then(toList),

  courseCalendarEvents: (courseId: string, query?: { start?: string; end?: string }) =>
    request<CalendarEvent[]>(`/courses/${courseId}/calendar-events`, { query }).then(toList),

  /** 加入课程（需要幂等键；APPROVAL 课程提交申请，OPEN 课程直接加入） */
  joinCourse: (courseId: string, payload: { invitation_code?: string; application_message?: string }, reuseKey?: string) =>
    request<Enrollment>(
      `/courses/${courseId}/enrollments`,
      { method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey() },
    ).then((r) => r.data),

  dropEnrollment: (enrollmentId: string, ifMatch: string, reuseKey: string) =>
    request<unknown>(`/me/enrollments/${enrollmentId}/withdraw`, {
      method: "POST", body: {}, idempotencyKey: reuseKey, ifMatch,
    }).then((r) => r.data),
};

/* ══════════ 学生任务 ══════════ */

export const taskApi = {
  list: (query?: { page?: number; page_size?: number; status?: string; course_id?: string }) =>
    request<Partial<Task>[]>("/tasks", { query }).then(taskListEnvelope),

  detail: (taskId: string) => request<Partial<Task>>(`/tasks/${taskId}`).then((r) => taskEnvelope(r).data),

  transitions: (taskId: string) =>
    request<{ allowed_actions: string[]; blockers: Task["blockers"] }>(`/tasks/${taskId}/transitions`).then((r) => r.data),

  start: (taskId: string, ifMatch?: string | number | null, reuseKey?: string) =>
    request<Partial<Task>>(`/tasks/${taskId}/start`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then(taskEnvelope).then((r) => r.data),

  enter: (taskId: string, ifMatch?: string | number | null, reuseKey?: string) =>
    request<{ task: Partial<Task>; session: WorkspaceSession }>(`/tasks/${taskId}/enter`, {
      method: "POST",
      body: {},
      idempotencyKey: reuseKey ?? newIdempotencyKey(),
      ifMatch,
    }).then((r) => r.data)
      .then((data) => ({ ...data, task: data?.task ? normalizeTask(data.task) : (data?.task as never) })) as
    Promise<{ task: Task; session: WorkspaceSession }>,

  provisioningJob: (taskId: string) =>
    request<Record<string, unknown> | null>(`/tasks/${taskId}/provisioning-job`).then((r) => r.data),

  cancelProvisioning: (taskId: string, ifMatch?: string | number | null, reuseKey?: string) =>
    request(`/tasks/${taskId}/provisioning-job/cancel`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  extensions: (taskId: string) =>
    request<Array<Record<string, unknown>>>(`/tasks/${taskId}/extensions`).then(toList),

  requestExtension: (taskId: string, payload: { reason: string }, ifMatch: string, reuseKey?: string) =>
    request(`/tasks/${taskId}/extension-requests`, {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  retry: (taskId: string, ifMatch?: string | number | null, reuseKey?: string) =>
    request<Partial<Task>>(`/tasks/${taskId}/retry`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then(taskEnvelope).then((r) => r.data),

  complete: (taskId: string, ifMatch?: string | number | null, reuseKey?: string) =>
    request<Partial<Task>>(`/tasks/${taskId}/complete`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then(taskEnvelope).then((r) => r.data),
};

/* ══════════ 工作区 ══════════ */

export interface WorkbenchAggregate {
  task: Task;
  session?: WorkspaceSession | null;
  chapters: Array<{ public_id: string; title: string; description?: string | null; sort_order: number; status?: string; tasks?: unknown; instructions?: string[] }>;
  content?: { description?: string | null; steps?: Array<Record<string, unknown>> } | null;
  current_chapter?: { public_id: string; title: string; instructions?: string[] } | null;
  tests?: Array<{ key?: string; name: string; description?: string }>;
  capabilities?: string[];
}

export const workspaceApi = {
  workbench: (taskId: string) => request<WorkbenchAggregate>(`/tasks/${taskId}/workbench`)
    .then((r) => r.data)
    .then((data) => normalizeWorkbenchAggregate(data)),

  createSession: (taskId: string, reuseKey?: string) =>
    request<WorkspaceSession>(`/tasks/${taskId}/workspace-sessions`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),

  renewSession: (sessionId: string, workspaceToken?: string, reuseKey?: string) =>
    request<WorkspaceSession>(`/workspace-sessions/${sessionId}/renew`, {
      method: "POST",
      body: {},
      idempotencyKey: reuseKey ?? newIdempotencyKey(),
      headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined,
    }).then((r) => r.data),

  revokeSession: (sessionId: string, workspaceToken?: string, reuseKey?: string) =>
    request(`/workspace-sessions/${sessionId}/revoke`, {
      method: "POST",
      body: {},
      idempotencyKey: reuseKey ?? newIdempotencyKey(),
      headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined,
    }).then((r) => r.data),

  saveSnapshot: (taskId: string, payload: { base_version: number; client_seq: number; digest: string; content?: unknown }, workspaceToken?: string, reuseKey?: string) =>
    request<Record<string, unknown>>(`/tasks/${taskId}/workspace-snapshot`, {
      method: "PUT",
      body: payload,
      idempotencyKey: reuseKey ?? newIdempotencyKey(),
      headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined,
    }).then((r) => r.data),

  checkpoints: (taskId: string, workspaceToken?: string) =>
    request<{ items?: unknown[]; current_version?: number; row_version?: number }>(
      `/tasks/${taskId}/checkpoints`,
      { headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined },
    ).then((envelope) => {
      const raw = envelope.data as { items?: unknown[]; current_version?: number; row_version?: number } | null;
      return {
        rows: Array.isArray(raw?.items) ? (raw.items as Checkpoint[]) : [],
        currentVersion: typeof raw?.current_version === "number" ? raw.current_version : 0,
        sessionRowVersion: typeof raw?.row_version === "number" ? raw.row_version : 0,
      } satisfies CheckpointList;
    }),

  createCheckpoint: (taskId: string, payload: { label: string }, workspaceToken?: string, reuseKey?: string) =>
    request<Checkpoint>(`/tasks/${taskId}/checkpoints`, {
      method: "POST",
      body: payload,
      idempotencyKey: reuseKey ?? newIdempotencyKey(),
      headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined,
    }).then((r) => r.data),

  restoreCheckpoint: (taskId: string, checkpointId: string, ifMatch?: string | number | null, workspaceToken?: string, reuseKey?: string) =>
    request(`/tasks/${taskId}/checkpoints/${checkpointId}/restore`, {
      method: "POST",
      body: {},
      idempotencyKey: reuseKey ?? newIdempotencyKey(),
      ifMatch,
      headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined,
    }).then((r) => r.data),

  executionRuns: (taskId: string, query?: { page?: number; page_size?: number }, workspaceToken?: string) =>
    request<ExecutionRun[]>(`/tasks/${taskId}/execution-runs`, {
      query,
      headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined,
    }).then(toList),

  executionRun: (taskId: string, runId: string, workspaceToken?: string) =>
    request<ExecutionRun>(`/tasks/${taskId}/execution-runs/${runId}`, {
      headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined,
    }).then((r) => r.data),

  createExecutionRun: (
    taskId: string,
    payload: { snapshot_id?: string; test_keys?: string[] },
    workspaceToken?: string,
    reuseKey?: string,
  ) =>
    request<ExecutionRun>(`/tasks/${taskId}/execution-runs`, {
      method: "POST",
      body: payload,
      idempotencyKey: reuseKey ?? newIdempotencyKey(),
      headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined,
    }).then((r) => r.data),

  stopRuntime: (runtimeId: string, reuseKey?: string) =>
    request(`/student/task-runtimes/${runtimeId}/stop`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),
};

/* ══════════ 报告 ══════════ */

export const reportApi = {
  draft: (taskId: string) => request<ReportDraft>(`/tasks/${taskId}/report-draft`).then((r) => r.data),

  saveDraft: (taskId: string, payload: { body_html?: string; body_markdown?: string; snapshot_digest?: string | null }, ifMatch?: string | null) =>
    request<ReportDraft>(`/tasks/${taskId}/report-draft`, {
      method: "PUT", body: payload, idempotencyKey: newIdempotencyKey(), ifMatch,
    }),

  reportVersions: (taskId: string) =>
    request<Array<Record<string, unknown>>>(`/tasks/${taskId}/report-versions`).then(toList),

  attachments: (taskId: string) =>
    request<ReportDraft["attachments"]>(`/tasks/${taskId}/attachments`).then((r) => r.data),

  uploadAttachment: (taskId: string, reuseKey?: string) =>
    request(`/tasks/${taskId}/attachments`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),

  createDownloadGrant: (assetId: string, reuseKey?: string) =>
    request<{ token: string; expires_at?: string }>(`/files/${assetId}/download-grants`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),

  submitReport: (taskId: string, reuseKey?: string) =>
    request<Record<string, unknown>>(`/tasks/${taskId}/submit-report`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),

  reviewResult: (taskId: string) =>
    request<Record<string, unknown>>(`/tasks/${taskId}/review-result`).then((r) => r.data),
};

/* ══════════ 教师端 ══════════ */

export const teachingApi = {
  courses: (query?: { page?: number; page_size?: number }) =>
    request<TeachingCourseList["courses"]>("/teaching/courses", { query }).then(toList),

  course: (courseId: string) =>
    request<TeachingCourseList["courses"][number]>(`/teaching/courses/${courseId}`).then((r) => r.data),

  createCourse: (payload: Partial<Course>, reuseKey?: string) =>
    request<Course>("/teaching/courses", {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),

  publishCourse: (courseId: string, ifMatch: string, reuseKey?: string) =>
    request<Course>(`/teaching/courses/${courseId}/publish`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  courseResource: <T>(courseId: string, resource: "chapters" | "materials" | "announcements" | "calendar-events" | "questions", query?: { page?: number }) =>
    request<T[]>(`/teaching/courses/${courseId}/${resource}`, { query }).then(toList),

  enrollments: (courseId: string, query?: { status?: string; page?: number }) =>
    request<Enrollment[]>(`/teaching/courses/${courseId}/enrollments`, { query }).then(toList),

  reviewEnrollment: (courseId: string, enrollmentId: string, payload: { decision: "approve" | "reject"; decision_note?: string }, ifMatch: string, reuseKey?: string) =>
    request<Enrollment>(`/teaching/courses/${courseId}/enrollments/${enrollmentId}/review`, {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  imports: {
    precheck: (courseId: string, payload: { rows?: string[]; file_name?: string }, reuseKey?: string) =>
      request<ImportJob>(`/teaching/courses/${courseId}/enrollment-imports/precheck`, {
        method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(),
      }).then((r) => r.data),
    get: (courseId: string, jobId: string) =>
      request<ImportJob>(`/teaching/courses/${courseId}/enrollment-imports/${jobId}`).then((r) => r.data),
  },

  // 模板
  templates: (courseId: string, query?: { page?: number }) =>
    request<Template[]>(`/teaching/courses/${courseId}/templates`, { query }).then(toList),

  createTemplate: (courseId: string, payload: { name: string; description?: string; category?: string }, reuseKey?: string) =>
    request<Template>(`/teaching/courses/${courseId}/templates`, {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),

  deleteTemplate: (courseId: string, templateId: string, ifMatch: string | number | null, reuseKey?: string) =>
    request<Template>(`/teaching/courses/${courseId}/templates/${templateId}`, {
      method: "DELETE", idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  templateVersions: (courseId: string, templateId: string) =>
    request<TemplateVersion[]>(`/teaching/courses/${courseId}/templates/${templateId}/versions`).then(toList),

  createTemplateVersion: (courseId: string, templateId: string, payload: Record<string, unknown>, reuseKey?: string) =>
    request<TemplateVersion>(`/teaching/courses/${courseId}/templates/${templateId}/versions`, {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),

  templateVersion: (courseId: string, versionId: string) =>
    request<TemplateVersion>(`/teaching/courses/${courseId}/template-versions/${versionId}`).then((r) => r.data),

  updateTemplateVersion: (courseId: string, versionId: string, payload: Record<string, unknown>, ifMatch: string | number | null, reuseKey?: string) =>
    request<TemplateVersion>(`/teaching/courses/${courseId}/template-versions/${versionId}`, {
      method: "PATCH", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  templateChapters: (courseId: string, versionId: string) =>
    request<TemplateChapter[]>(`/teaching/courses/${courseId}/template-versions/${versionId}/chapters`).then(toList),

  createTemplateChapter: (courseId: string, versionId: string, payload: { title: string; description?: string }, ifMatch: string | number | null, reuseKey?: string) =>
    request<TemplateChapter>(`/teaching/courses/${courseId}/template-versions/${versionId}/chapters`, {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  createTemplateTask: (courseId: string, chapterId: string, payload: { title: string; description?: string; task_type?: string }, ifMatch: string | number | null, reuseKey?: string) =>
    request<TemplateTask>(`/teaching/courses/${courseId}/template-chapters/${chapterId}/tasks`, {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  reorderChapters: (courseId: string, versionId: string, payload: { chapter_ids: string[] }, ifMatch: string, reuseKey?: string) =>
    request<unknown>(`/teaching/courses/${courseId}/template-versions/${versionId}/chapters/reorder`, {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  templateChapterTasks: (courseId: string, chapterId: string) =>
    request<TemplateTask[]>(`/teaching/courses/${courseId}/template-chapters/${chapterId}/tasks`).then(toList),

  templateOptions: (courseId: string) =>
    request<{
      runtime_adapters: Array<{
        public_id: string; name: string; code: string;
        runtime_type: string; driver: string; health_status: string;
      }>;
      images: Array<{ public_id: string; repository: string; display_tag?: string; digest: string; risk_level?: string }>;
      resource_profiles: Array<{
        public_id: string; code: string; name: string;
        cpu_millicores: number; memory_mb: number; disk_gb: number; network_mode?: string;
      }>;
      materials: Array<{ public_id: string; title: string; version_no: number; digest_sha256?: string }>;
    }>(`/teaching/courses/${courseId}/template-options`).then((r) => r.data),

  // 镜像
  experimentImages: (courseId: string) =>
    request<PlatformImage[]>(`/teaching/courses/${courseId}/experiment-images`).then(toList),

  prepareImage: (courseId: string, imageId: string, ifMatch: string, reuseKey?: string) =>
    request<PlatformImage>(`/teaching/courses/${courseId}/experiment-images/${imageId}/prepare`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  imageEvents: (courseId: string, imageId: string) =>
    request<Array<Record<string, unknown>>>(`/teaching/courses/${courseId}/experiment-images/${imageId}/events`).then(toList),

  // 预检与发布
  precheck: (courseId: string, versionId: string, ifMatch: string | number | null, reuseKey?: string) =>
    request<PrecheckRun>(`/teaching/courses/${courseId}/template-versions/${versionId}/precheck`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  precheckRuns: (courseId: string, versionId: string) =>
    request<PrecheckRun[]>(`/teaching/courses/${courseId}/template-versions/${versionId}/precheck-runs`).then(toList),

  publishTemplateVersion: (courseId: string, versionId: string, ifMatch: string | number | null, reuseKey?: string) =>
    request<unknown>(`/teaching/courses/${courseId}/template-versions/${versionId}/publish`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  saveExecutionSpec: (
    courseId: string,
    versionId: string,
    payload: {
      tests_json: string; language: string; entrypoint: string;
      timeout_seconds: number; memory_mb: number; cpu_millicores: number;
      comparator: string; network_mode: string;
    },
    ifMatch: string | number | null,
    reuseKey?: string,
  ) =>
    request<unknown>(`/teaching/courses/${courseId}/template-versions/${versionId}/execution-spec`, {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  publications: (courseId: string, query?: { page?: number; status?: string }) =>
    request<Publication[]>(`/teaching/courses/${courseId}/experiments`, { query }).then(toList),

  createPublication: (courseId: string, payload: Record<string, unknown>, reuseKey?: string) =>
    request<Publication>(`/teaching/courses/${courseId}/experiments`, {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),

  publication: (courseId: string, publicationId: string) =>
    request<Publication>(`/teaching/courses/${courseId}/experiments/${publicationId}`).then((r) => r.data),

  updatePublication: (courseId: string, publicationId: string, payload: Record<string, unknown>, ifMatch: string, reuseKey?: string) =>
    request<Publication>(`/teaching/courses/${courseId}/experiments/${publicationId}`, {
      method: "PATCH", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  publishPublication: (courseId: string, publicationId: string, ifMatch: string, reuseKey?: string) =>
    request<Publication>(`/teaching/courses/${courseId}/experiments/${publicationId}/publish`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  withdrawPublication: (courseId: string, publicationId: string, ifMatch: string, reuseKey?: string) =>
    request<Publication>(`/teaching/courses/${courseId}/experiments/${publicationId}/withdraw`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  closePublication: (courseId: string, publicationId: string, ifMatch: string, reuseKey?: string) =>
    request<Publication>(`/teaching/courses/${courseId}/experiments/${publicationId}/close`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  publicationTasks: (courseId: string, publicationId: string, query?: { page?: number }) =>
    request<Partial<Task>[]>(`/teaching/courses/${courseId}/experiments/${publicationId}/tasks`, { query }).then(taskListEnvelope),

  // 选课与邀请
  invitations: (courseId: string) =>
    request<Invitation[]>(`/teaching/courses/${courseId}/invitations`).then(toList),

  createInvitation: (
    courseId: string,
    payload: { usage_limit?: number; valid_days?: number; max_uses?: number; expires_at?: string } = {},
    reuseKey?: string,
  ) => {
    // The API contract (InvitationWrite) requires max_uses + expires_at; map
    // the UI-facing knobs onto it so calls never send unsupported fields.
    const body = {
      max_uses: payload.max_uses ?? payload.usage_limit ?? 20,
      expires_at:
        payload.expires_at ??
        new Date(Date.now() + (payload.valid_days ?? 30) * 86_400_000).toISOString(),
    };
    return request<Invitation>(`/teaching/courses/${courseId}/invitations`, {
      method: "POST",
      body,
      idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data);
  },

  // 学生过程
  progress: (courseId: string, query?: { page?: number; page_size?: number; section?: string }) =>
    request<Partial<Task>[]>(`/teaching/courses/${courseId}/progress`, { query }).then(taskListEnvelope),

  studentTaskWorkspace: (courseId: string, taskId: string) =>
    request<Record<string, unknown>>(`/teaching/courses/${courseId}/tasks/${taskId}/workspace`).then((r) => r.data),

  operationReplay: (courseId: string, taskId: string) =>
    request<Array<Record<string, unknown>>>(`/teaching/courses/${courseId}/tasks/${taskId}/operation-replay`).then(toList),

  // 评审
  reviews: (courseId: string, query?: { status?: string; page?: number }) =>
    request<ReviewSummary[]>(`/teaching/courses/${courseId}/reviews`, { query }).then(toList),

  rubrics: (courseId: string) =>
    request<Rubric[]>(`/teaching/courses/${courseId}/rubrics`).then(toList),

  review: (courseId: string, reviewId: string) =>
    request<ReviewDetail>(`/teaching/courses/${courseId}/reviews/${reviewId}`).then((r) => r.data),

  saveCriterionScores: (courseId: string, reviewId: string, payload: { scores: Array<{ criterion: string; score: number }> }, ifMatch?: string, reuseKey?: string) =>
    request<ReviewDetail>(`/teaching/courses/${courseId}/reviews/${reviewId}/criterion-scores`, {
      method: "PUT", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  addAnnotation: (courseId: string, reviewId: string, payload: { body: string }, ifMatch: string, reuseKey?: string) =>
    request<ReviewDetail>(`/teaching/courses/${courseId}/reviews/${reviewId}/annotations`, {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  revokeAnnotation: (courseId: string, annotationId: string, ifMatch: string, reuseKey?: string) =>
    request(`/teaching/courses/${courseId}/annotations/${annotationId}/revoke`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  decideReview: (courseId: string, reviewId: string, payload: { decision: "approve" | "return"; note?: string }, ifMatch: string, reuseKey?: string) =>
    request<ReviewDetail>(`/teaching/courses/${courseId}/reviews/${reviewId}/decide`, {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  startSimilarityRun: (courseId: string, taskId: string, reuseKey?: string) =>
    request<Record<string, unknown>>(`/teaching/courses/${courseId}/similarity-runs`, {
      method: "POST", body: { task_id: taskId }, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),

  submissionPreview: (courseId: string, taskId: string) =>
    request<Record<string, unknown>>(`/teaching/courses/${courseId}/tasks/${taskId}/submission-preview`).then((r) => r.data),

  // 分析
  analytics: (courseId: string, section: "overview" | "quality" | "resource-costs") =>
    request<Record<string, unknown>>(`/teaching/courses/${courseId}/analytics/${section}`).then((r) => r.data),

  analyticsSeries: (courseId: string, days?: number) =>
    request<{
      course_id: string;
      series: Array<{ period_start: string; metrics: Record<string, unknown>; calculated_at?: string }>;
    }>(`/teaching/courses/${courseId}/analytics/series`, { query: days ? { days } : undefined }).then((r) => r.data),

  riskSignals: (courseId: string) =>
    request<Array<{ id: string; kind?: string; message: string; student_name?: string }>>(`/teaching/courses/${courseId}/analytics/risk-signals`).then(toList),
};

/* ══════════ 平台端 ══════════ */

export const platformApi = {
  users: (query?: { page?: number; page_size?: number; search?: string }) =>
    request<PlatformUser[]>("/platform/users", { query }).then(toList),

  verifications: (query?: { page?: number; page_size?: number; status?: string }) =>
    request<Verification[]>("/platform/verifications", { query }).then(toList),

  reviewVerification: (id: string, payload: { decision: "approve" | "reject"; note?: string }, ifMatch: string, reuseKey?: string) =>
    request<Verification>(`/platform/verifications/${id}/review`, {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  governanceAlerts: (query?: { page?: number; page_size?: number; level?: string }) =>
    request<Anomaly[]>("/platform/governance/alerts", { query }).then(toList),

  governanceUsage: () =>
    request<Record<string, unknown>>("/platform/governance/usage").then((r) => r.data),

  courses: (query?: { page?: number; page_size?: number; status?: string }) =>
    request<Course[]>("/platform/courses", { query }).then(toList),

  freezeCourse: (courseId: string, payload: { reason?: string }, ifMatch: string, reuseKey?: string) =>
    request<Course>(`/platform/courses/${courseId}/freeze`, {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  precheckSummary: () =>
    request<Record<string, unknown>>("/platform/template-prechecks/summary").then((r) => r.data),

  images: (query?: { page?: number; page_size?: number; scan_status?: string }) =>
    request<PlatformImage[]>("/platform/images", { query }).then(toList),

  decideImage: (imageId: string, payload: { decision: "approve" | "reject"; note?: string }, ifMatch: string, reuseKey?: string) =>
    request<PlatformImage>(`/platform/images/${imageId}/decide`, {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  resourceProfiles: (query?: { page?: number; page_size?: number; status?: string }) =>
    request<ResourceProfile[]>("/platform/resource-profiles", { query }).then(toList),

  runtimeAdapters: () =>
    request<RuntimeAdapter[]>("/platform/runtime-adapters").then(toList),

  quotas: (query?: { page?: number; page_size?: number }) =>
    request<Quota[]>("/platform/quotas", { query }).then(toList),

  compensations: (query?: { status?: string; page?: number; page_size?: number }) =>
    request<Compensation[]>("/platform/compensations", { query }).then(toList),

  retryCompensation: (compensationId: string, payload: { reason: string }, ifMatch: string, reuseKey?: string) =>
    request<Compensation>("/platform/compensations", {
      method: "POST",
      body: { compensation_id: compensationId, ...payload },
      idempotencyKey: reuseKey ?? newIdempotencyKey(),
      ifMatch,
    }).then((r) => r.data),

  instances: (query?: { page?: number; page_size?: number; status?: string; orphaned?: boolean }) =>
    request<InstanceData[]>("/platform/instances", { query }).then(toList),

  destroyInstance: (instanceId: string, ifMatch: string, reuseKey?: string) =>
    request(`/platform/instances/${instanceId}/destroy`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  workspaceSessions: (query?: { page?: number; page_size?: number; status?: string }) =>
    request<WorkspaceSession[]>("/platform/workspaces/sessions", { query }).then(toList),

  anomalies: (query?: { kind?: string; page?: number; page_size?: number }) =>
    request<Anomaly[]>("/platform/tasks/anomalies", { query }).then(toList),

  scanAnomalies: (query?: { page?: number; page_size?: number }) =>
    request<Anomaly[]>("/platform/reports/scan-anomalies", { query }).then(toList),

  operationsOverview: () =>
    request<OperationsOverview>("/platform/operations/overview").then((r) => r.data),

  operationLogs: (query?: { page?: number; page_size?: number; search?: string; trace_id?: string }) =>
    request<OperationLog[]>("/platform/operations/logs", { query }).then(toList),

  agentModelRoutes: () =>
    request<ModelRoute[]>("/platform/agent/model-routes").then(toList),

  agentToolPolicies: () =>
    request<ToolPolicy[]>("/platform/agent/tool-policies").then(toList),

  agentUsageCosts: (query?: { page?: number; page_size?: number; window?: string }) =>
    request<UsageCost[]>("/platform/agent/usage-costs", { query }).then(toList),
};
