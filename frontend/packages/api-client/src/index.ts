import { ensureCsrf, readCsrfToken, newIdempotencyKey, request } from "@edu/auth-client";
import type { EnvelopeSuccess } from "@edu/auth-client";
import type { components } from "./generated/schema";
import type {
  Anomaly, Announcement, CalendarEvent, Checkpoint, CheckpointList, Chapter, Compensation, Course,
  Enrollment, ExecutionRun, ImageCreateInput, ImageScanReportInput, ImportJob, Instance as InstanceData, Invitation, Material, Me,
  ModelRoute, NotificationItem, OperationLog, OperationsOverview, PlatformImage, PlatformUser,
  PortalContext, PrecheckRun, Publication, Quota, ReportDraft, ResourceProfile, ReviewDetail,
  ReviewResult, ReviewSummary, Rubric, RuntimeAdapter, StudentDashboard, Task, TeachingCourseList, Template,
  TemplateChapter, TemplateTask, ToolPolicy, TemplateVersion, UsageCost, Verification,
  WorkspaceOperationEvent, WorkspaceSession, WorkspaceStorageJob, AgentMessage, AgentMode, CourseResourceSummary,
  LearningHistoryData, NotificationPreferences, TimetableData, TimetableImport, AgentProfile, AgentSession,
  AgentToolCall, ToolRequest, ToolDecision, AgentFeedback, VerificationUpdate, NotificationPreferenceUpdate,
  EnrollmentExitCheck, CourseQuestion, CourseAnswer, DownloadGrant, DownloadGrantRevoke,
  ReportAttachmentData, ReportAttachmentUpload, ReportAttachmentCreate, LearningRecommendation, LearningRiskSignal,
  OIDCIdentity, OIDCStart, AIScoreBatch, AIScoreSuggestion,
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
          input: entry["input"] != null ? String(entry["input"]) : undefined,
          expected: entry["expected"] != null ? String(entry["expected"]) : undefined,
        };
      });
    }
  } else {
    testsList = undefined;
  }
  const rawTemplate = (data as { template?: unknown }).template;
  let templateCaps: Record<string, boolean> | null = null;
  if (rawTemplate != null && typeof rawTemplate === "object") {
    const rawCaps = (rawTemplate as { workspace_capabilities?: unknown }).workspace_capabilities;
    if (rawCaps != null && typeof rawCaps === "object") {
      templateCaps = Object.fromEntries(
        Object.entries(rawCaps as Record<string, unknown>)
          .filter((entry) => typeof entry[1] === "boolean")
          .map((entry) => [entry[0], entry[1] as boolean]),
      );
    }
  }
  return {
    ...data,
    task: data.task ? normalizeTask(data.task) : (data.task as never),
    chapters,
    tests: testsList,
    tests_count: (rawTests as { count?: number } | null)?.count ?? testsList?.length ?? 0,
    tests_available: (rawTests as { runnable?: boolean } | null)?.runnable ?? Boolean(testsList?.length),
    template_caps: templateCaps,
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
    request<Array<NotificationItem & { link_url?: string; task_id?: string; course_id?: string }>>("/notifications", { query }).then((response) => {
      const list = toList(response);
      return { ...list, rows: list.rows.map((item) => ({
        ...item, id: item.public_id ?? item.id, read: item.read_at != null || item.read === true,
        links: item.links ?? (item.link_url || item.task_id || item.course_id
          ? [{ url: item.link_url || undefined, task_id: item.task_id, course_id: item.course_id }] : []),
      })) };
    }),
  markNotificationRead: (id: string, ifMatch: string | number, reuseKey?: string) =>
    request(`/notifications/${id}/read`, { method: "POST", body: {}, ifMatch, idempotencyKey: reuseKey ?? newIdempotencyKey() }).then((r) => r.data),
  learningHistory: () => request<LearningHistoryData>("/me/learning-history").then((r) => r.data),
  timetable: (query?: { term_id?: string }) => request<TimetableData>("/me/timetable", { query }).then((r) => r.data),
  resourceSummary: (courseId: string) => request<CourseResourceSummary>(`/me/courses/${courseId}/resource-summary`).then((r) => r.data),
  notificationPreferences: () => request<NotificationPreferences>("/notification-preferences").then((r) => r.data),
  updateNotificationPreferences: (payload: NotificationPreferenceUpdate, ifMatch: string | number | null, reuseKey?: string) =>
    request<NotificationPreferences>("/notification-preferences", { method: "PATCH", body: payload, ifMatch, idempotencyKey: reuseKey ?? newIdempotencyKey() }).then((r) => r.data),
  changePassword: (payload: { current_password: string; new_password: string }, ifMatch: string | number, reuseKey?: string) =>
    request<Me>("/me/password", { method: "POST", body: payload, ifMatch, idempotencyKey: reuseKey ?? newIdempotencyKey() }).then((r) => r.data),
  verification: () => request<Verification>("/me/verification").then((r) => r.data),
  updateVerification: (payload: VerificationUpdate, ifMatch: string | number, reuseKey?: string) =>
    request<Verification>("/me/verification", { method: "PUT", body: payload, ifMatch, idempotencyKey: reuseKey ?? newIdempotencyKey() }).then((r) => r.data),
  oidcIdentities: () => request<OIDCIdentity[]>("/me/oidc-identities").then(toList),
  unlinkOidcIdentity: (identityId: string, ifMatch: string | number, reuseKey?: string) =>
    request<OIDCIdentity>(`/me/oidc-identities/${identityId}/unlink`, {
      method: "POST", body: {}, ifMatch, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),

  /* 平台端敏感写操作要求"近期认证"：提交密码刷新会话认证时间 */
  stepUpSession: (password: string, reuseKey?: string) =>
    request<{ recent: boolean; authenticated_at?: string }>("/auth/session/step-up", {
      method: "POST",
      body: { password },
      idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),
};

export const oidcApi = {
  start: (providerKey: string) => request<OIDCStart>(`/auth/oidc/${providerKey}/start`).then((r) => r.data),
  callback: (providerKey: string, query: { state: string; nonce: string; iss: string; code?: string; code_verifier?: string; subject?: string }) =>
    request<OIDCIdentity>(`/auth/oidc/${providerKey}/callback`, { query }).then((r) => r.data),
};

/* ══════════ 学生端 ══════════ */

export const studentApi = {
  dashboard: () => request<StudentDashboard>("/me/dashboard").then((r) => r.data),

  courses: (query?: { page?: number; page_size?: number; search?: string }) =>
    request<Course[]>("/courses", { query }).then(toList),
  resolveInvitation: (code: string) => request<Course>("/courses/invitations/resolve", { query: { code } }).then((r) => r.data),

  myEnrollments: (query?: { page?: number; page_size?: number; status?: string }) =>
    request<Enrollment[]>("/me/enrollments", { query }).then(toList),
  enrollment: (enrollmentId: string) => request<Enrollment>(`/me/enrollments/${enrollmentId}`).then((r) => r.data),
  dropCheck: (enrollmentId: string) => request<EnrollmentExitCheck>(`/me/enrollments/${enrollmentId}/drop-check`).then((r) => r.data),
  dropEnrollment: (enrollmentId: string, payload: { reason: string }, ifMatch: string | number, reuseKey?: string) =>
    request<Enrollment>(`/me/enrollments/${enrollmentId}/drop`, { method: "POST", body: payload, ifMatch, idempotencyKey: reuseKey ?? newIdempotencyKey() }).then((r) => r.data),

  coursesResource: <T>(courseId: string, resource: "chapters" | "materials" | "announcements" | "calendar" | "questions", query?: { page?: number; page_size?: number }) =>
    request<T[]>(`/courses/${courseId}/${resource}`, { query }).then(toList),

  courseDetail: (courseId: string) => request<Course>(`/courses/${courseId}`).then((r) => r.data),

  courseChapters: (courseId: string) =>
    request<Array<Chapter & { summary?: string; position?: number }>>(`/courses/${courseId}/chapters`).then((r) => {
      const list = toList(r);
      return { ...list, rows: list.rows.map((chapter) => ({ ...chapter, description: chapter.summary ?? chapter.description, sort_order: chapter.position ?? chapter.sort_order })) };
    }),

  courseMaterials: (courseId: string) =>
    request<Array<Material & { kind?: string }>>(`/courses/${courseId}/materials`).then((r) => {
      const list = toList(r);
      return { ...list, rows: list.rows.map((item) => ({ ...item, type: item.kind ?? item.type })) };
    }),

  courseAnnouncements: (courseId: string) =>
    request<Array<Announcement & { publish_at?: string }>>(`/courses/${courseId}/announcements`).then((r) => {
      const list = toList(r);
      return { ...list, rows: list.rows.map((item) => ({ ...item, published_at: item.publish_at ?? item.published_at })) };
    }),

  courseCalendarEvents: (courseId: string, query?: { start?: string; end?: string }) =>
    request<Array<CalendarEvent & { starts_at: string; ends_at?: string | null }>>(`/courses/${courseId}/calendar`, { query }).then((r) => {
      const list = toList(r);
      return { ...list, rows: list.rows.map((item) => ({
        ...item,
        start_at: item.starts_at !== undefined ? item.starts_at : item.start_at,
        end_at: item.ends_at !== undefined ? item.ends_at : item.end_at,
      })) };
    }),

  /** 加入课程（需要幂等键；APPROVAL 课程提交申请，OPEN 课程直接加入） */
  joinCourse: (courseId: string, payload: { invitation_code?: string; application_message?: string }, reuseKey?: string) =>
    request<Enrollment>(
      `/courses/${courseId}/enrollments`,
      { method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey() },
    ).then((r) => r.data),

  withdrawEnrollment: (enrollmentId: string, ifMatch: string | number, reuseKey?: string) =>
    request<Enrollment>(`/me/enrollments/${enrollmentId}/withdraw`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),
};

/* ══════════ 学生 Agent、课程问答与文件 ══════════ */

export const agentApi = {
  courseProfile: (courseId: string) => request<AgentProfile>(`/courses/${courseId}/agent-profile`).then((r) => r.data),
  createCourseSession: (courseId: string, mode: AgentMode, reuseKey?: string) => request<AgentSession>(`/courses/${courseId}/agent-sessions`, { method: "POST", body: { mode }, idempotencyKey: reuseKey ?? newIdempotencyKey() }).then((r) => r.data),
  createTaskSession: (taskId: string, mode: AgentMode, reuseKey?: string) => request<AgentSession>(`/tasks/${taskId}/agent-sessions`, { method: "POST", body: { mode }, idempotencyKey: reuseKey ?? newIdempotencyKey() }).then((r) => r.data),
  session: (sessionId: string) => request<AgentSession>(`/agent-sessions/${sessionId}`).then((r) => r.data),
  messages: (sessionId: string) => request<AgentMessage[]>(`/agent-sessions/${sessionId}/messages`).then(toList),
  sendMessage: (sessionId: string, body: string, reuseKey?: string) => request<AgentMessage>(`/agent-sessions/${sessionId}/messages`, { method: "POST", body: { body }, idempotencyKey: reuseKey ?? newIdempotencyKey() }).then((r) => r.data),
  requestToolCall: (sessionId: string, payload: ToolRequest, reuseKey?: string) => request<AgentToolCall>(`/agent-sessions/${sessionId}/tool-calls`, { method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey() }).then((r) => r.data),
  decideToolCall: (callId: string, payload: ToolDecision, ifMatch: string | number, reuseKey?: string) => request<{ public_id: string; status: string; row_version: number }>(`/agent-tool-calls/${callId}/decide`, { method: "POST", body: payload, ifMatch, idempotencyKey: reuseKey ?? newIdempotencyKey() }).then((r) => r.data),
  feedback: (messageId: string, payload: AgentFeedback, reuseKey?: string) => request<{ public_id: string; status: string }>(`/agent-messages/${messageId}/feedback`, { method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey() }).then((r) => r.data),
};

export const courseDiscussionApi = {
  questions: (courseId: string) => request<CourseQuestion[]>(`/courses/${courseId}/questions`).then(toList),
  createQuestion: (courseId: string, payload: { title: string; body: string }, reuseKey?: string) => request<CourseQuestion>(`/courses/${courseId}/questions/create`, { method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey() }).then((r) => r.data),
  answerQuestion: (questionId: string, body: string, reuseKey?: string) => request<CourseAnswer>(`/questions/${questionId}/answers`, { method: "POST", body: { body }, idempotencyKey: reuseKey ?? newIdempotencyKey() }).then((r) => r.data),
};

export const fileApi = {
  createDownloadGrant: (assetId: string, reuseKey?: string) => request<DownloadGrant>(`/files/${assetId}/download-grants`, { method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey() }).then((r) => r.data),
  revokeDownloadGrant: (grantId: string, ifMatch: string | number, reuseKey?: string) => request<DownloadGrantRevoke>(`/files/download-grants/${grantId}/revoke`, { method: "POST", body: {}, ifMatch, idempotencyKey: reuseKey ?? newIdempotencyKey() }).then((r) => r.data),
};

export const timetableApi = {
  retrieve: meApi.timetable,
  imports: () => request<TimetableImport[]>("/me/timetable-imports").then(toList),
  importJob: (jobId: string) => request<TimetableImport>(`/me/timetable-imports/${jobId}`).then((r) => r.data),
  upload: (file: File, termId?: string) => {
    const body = new FormData();
    body.append("file", file);
    if (termId) body.append("term_id", termId);
    return request<TimetableImport>("/me/timetable-imports", { method: "POST", body }).then((r) => r.data);
  },
  updateMapping: (jobId: string, mapping: Record<string, string>) => request<TimetableImport>(`/me/timetable-imports/${jobId}/mapping`, { method: "PUT", body: { mapping } }).then((r) => r.data),
  confirm: (jobId: string) => request<TimetableImport>(`/me/timetable-imports/${jobId}/confirm`, { method: "POST", body: {} }).then((r) => r.data),
};

export const studentAnalyticsApi = {
  recommendations: () => request<LearningRecommendation[]>("/analytics/recommendations").then(toList),
  riskSignals: () => request<LearningRiskSignal[]>("/analytics/risk-signals").then(toList),
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

  archive: (taskId: string) => request<Record<string, unknown>>(`/tasks/${taskId}/archive`).then((r) => r.data),
  stopRuntime: (runtimeId: string, taskVersion: string | number, reuseKey?: string) =>
    request<{ runtime_id: string; task_id: string; status: string }>(`/student/task-runtimes/${runtimeId}/stop`, {
      method: "POST", body: {}, ifMatch: taskVersion, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),
  operationReplay: (taskId: string) => request<Array<Record<string, unknown>>>(`/tasks/${taskId}/operation-replay`).then(toList),
};

/* ══════════ 工作区 ══════════ */

export interface WorkbenchAggregate {
  task: Task;
  session?: WorkspaceSession | null;
  chapters: Array<{ public_id: string; title: string; description?: string | null; sort_order: number; status?: string; tasks?: unknown; instructions?: string[] }>;
  content?: { description?: string | null; steps?: Array<Record<string, unknown>>; manual?: { asset_id: string; format: string; text: string | null } | null } | null;
  current_chapter?: { public_id: string; title: string; instructions?: string[] } | null;
  tests?: Array<{ key?: string; name: string; description?: string; input?: string; expected?: string }>;
  tests_available?: boolean;
  tests_count?: number;
  capabilities?: string[];
  /** 模板锁定的工作区能力声明(布尔开关,后端 template.workspace_capabilities) */
  template_caps?: Record<string, boolean> | null;
  submission?: { can_submit: boolean; blocked_reason?: { code?: string } | null };
  workspace?: {
    mode?: string;
    language?: string;
    language_policy?: {
      mode?: string;
      language?: string | null;
      allowed_languages?: string[];
      default_versions?: Record<string, string>;
    };
    toolchain_version?: string | null;
    last_synchronized_snapshot_id?: string | null;
    active_storage_job?: WorkspaceStorageJob | null;
  };
}

async function waitForStorageJob(job: WorkspaceStorageJob): Promise<WorkspaceStorageJob> {
  for (let attempt = 0; attempt < 60; attempt++) {
    if (job.status === "PASSED" && job.result_snapshot_id) return job;
    if (job.status === "FAILED" || job.status === "CANCELLED") {
      throw new Error(job.failure?.message || "工作区快照保存失败，请重试");
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
    job = await request<WorkspaceStorageJob>(`/workspace-storage-jobs/${job.public_id}`).then(r => r.data);
  }
  throw new Error("工作区快照仍在处理中，请稍后重试");
}

export const workspaceApi = {
  editorControl: async (sessionId: string, action: "save" | "reload", workspaceToken: string) => {
    await ensureCsrf();
    const requestId = newIdempotencyKey();
    const send = () => fetch(`/workspace/${sessionId}/webide/edu-control/${action}`, {
      method: "POST", credentials: "include", signal: AbortSignal.timeout(15000),
      headers: { "Content-Type": "application/json", "X-CSRFToken": readCsrfToken() ?? "", "X-Workspace-Token": workspaceToken },
      body: JSON.stringify({ session_id: sessionId, request_id: requestId }),
    });
    let response = await send();
    // Reload briefly stops the extension host. saveAll is safe to repeat; never bypass it.
    for (let attempt = 0; action === "save" && [502, 503].includes(response.status) && attempt < 4; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      response = await send();
    }
    if (!response.ok) throw new Error(action === "save" ? "编辑器保存失败，请先保存文件后重试" : "编辑器重载失败，请刷新工作台");
    const body = await response.json() as { schema_version?: number; session_id?: string; request_id?: string; dirty_files?: unknown; saved?: boolean };
    if (body.schema_version !== 1 || body.session_id !== sessionId || body.request_id !== requestId
      || !Array.isArray(body.dirty_files) || body.dirty_files.length || (action === "save" && body.saved !== true)) {
      throw new Error("编辑器仍有未保存文件，请保存后重试");
    }
  },
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

  captureSnapshot: async (taskId: string, workspaceToken: string) => {
    const state = await workspaceApi.checkpoints(taskId, workspaceToken);
    const job = await request<WorkspaceStorageJob>(`/tasks/${taskId}/workspace-storage-jobs`, {
      method: "POST",
      // Failed captures keep their sequence, so a new attempt needs a fresh one.
      body: { kind: "CAPTURE", client_seq: Date.now(), base_version: state.currentVersion },
      ifMatch: state.sessionRowVersion,
      idempotencyKey: newIdempotencyKey(),
      headers: { "X-Workspace-Token": workspaceToken },
    }).then(r => r.data);
    return waitForStorageJob(job);
  },

  storageJob: async (
    taskId: string,
    payload: { kind: "SWITCH" | "RESET"; language?: string },
    sessionRowVersion: number,
    workspaceToken: string,
    reuseKey?: string,
  ) => {
    const job = await request<WorkspaceStorageJob>(`/tasks/${taskId}/workspace-storage-jobs`, {
      method: "POST",
      body: payload,
      ifMatch: sessionRowVersion,
      idempotencyKey: reuseKey ?? newIdempotencyKey(),
      headers: { "X-Workspace-Token": workspaceToken },
    }).then((r) => r.data);
    return waitForStorageJob(job);
  },

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
    request<WorkspaceStorageJob | Record<string, unknown>>(`/tasks/${taskId}/checkpoints/${checkpointId}/restore`, {
      method: "POST",
      body: {},
      idempotencyKey: reuseKey ?? newIdempotencyKey(),
      ifMatch,
      headers: workspaceToken ? { "X-Workspace-Token": workspaceToken } : undefined,
    }).then(async (r) => "status" in r.data ? await waitForStorageJob(r.data as WorkspaceStorageJob) : r.data),

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

  stopRuntime: (runtimeId: string, ifMatch: string | number, reuseKey?: string) =>
    request(`/student/task-runtimes/${runtimeId}/stop`, {
      method: "POST", body: {}, ifMatch, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),

  operation: (
    sessionId: string,
    operation: string,
    arguments_: Record<string, unknown>,
    workspaceToken: string,
    reuseKey?: string,
  ) => request<WorkspaceOperationEvent>(`/workspace/${sessionId}/operations`, {
    prefix: "",
    method: "POST",
    body: { operation, arguments: arguments_ },
    idempotencyKey: reuseKey ?? newIdempotencyKey(),
    headers: { "X-Workspace-Token": workspaceToken },
  }).then((r) => r.data),
};

/* ══════════ 报告 ══════════ */

export const reportApi = {
  draft: (taskId: string) => request<ReportDraft>(`/tasks/${taskId}/report-draft`).then((r) => r.data),

  saveDraft: (taskId: string, payload: { body_markdown: string }, ifMatch?: string | null) =>
    request<ReportDraft>(`/tasks/${taskId}/report-draft`, {
      method: "PUT", body: payload, idempotencyKey: newIdempotencyKey(), ifMatch,
    }),

  reportVersions: (taskId: string) =>
    request<Array<Record<string, unknown>>>(`/tasks/${taskId}/report-versions`).then(toList),

  attachments: (taskId: string) =>
    request<ReportDraft>(`/tasks/${taskId}/report-draft`).then((r) => r.data.attachments),

  uploadAttachment: (taskId: string, payload: ReportAttachmentCreate, reuseKey?: string) =>
    request<ReportAttachmentUpload>(`/tasks/${taskId}/attachments`, {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),

  attachmentStatus: (taskId: string, assetId: string) => request<ReportAttachmentData>(`/tasks/${taskId}/attachments/${assetId}`).then((r) => r.data),
  completeAttachment: (taskId: string, assetId: string, ifMatch: string | number, reuseKey?: string) =>
    request<ReportAttachmentData>(`/tasks/${taskId}/attachments/${assetId}/complete`, {
      method: "POST", body: {}, ifMatch, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),

  createDownloadGrant: (assetId: string, reuseKey?: string) =>
    request<DownloadGrant>(`/files/${assetId}/download-grants`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),

  submitReport: (taskId: string, reuseKey?: string, ifMatch?: string | number | null) =>
    request<Record<string, unknown>>(`/tasks/${taskId}/submit-report`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  reviewResult: (taskId: string) =>
    request<components["schemas"]["ReviewResultData"]>(`/tasks/${taskId}/review-result`).then(({ data }): ReviewResult => {
      const rounds = data.rounds.map((round) => ({
        ...round,
        scores: round.scores ? { ...round.scores, criteria: round.scores.criteria.map((criterion) => ({
          ...criterion, score: criterion.score == null ? null : Number(criterion.score), max_score: Number(criterion.max_score),
        })) } : null,
        decision: round.decision ? { ...round.decision, score: Number(round.decision.score) } : null,
      }));
      return { ...data, rounds, score: rounds.find((round) => round.decision)?.decision?.score ?? null };
    }),
};

/* ══════════ 教师端 ══════════ */

/* ══════════ 评审详情归一 ══════════ */

function escapeReportHtml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/* 后端 review_detail_data 契约：
 - 评分标准在 scores.criteria（rubric/{version}/criteria），后端没有 rubric 字段；criteria 里同条目回带已存 score
 - submission 是 { kind, version | artifact }，报告正文在 version.body_markdown（markdown 而非 html）
 - annotations 用 public_id/status；status != ACTIVE 视为已撤销 */
function normalizeReviewDetail(raw: unknown): ReviewDetail {
  const base = (raw ?? {}) as Record<string, unknown>;
  const scores = base["scores"] as { criteria?: Array<Record<string, unknown>> } | undefined;
  const submission = base["submission"] as { version?: Record<string, unknown> | null } | undefined;
  const reportVersion = submission?.["version"] as Record<string, unknown> | null | undefined;
  const reportMarkdown = typeof reportVersion?.["body_markdown"] === "string" ? reportVersion["body_markdown"] : "";
  const criteria = (scores?.["criteria"] ?? []) as Array<Record<string, unknown>>;
  const annotations = (base["annotations"] ?? []) as Array<Record<string, unknown>>;
  return {
    ...(base as unknown as ReviewDetail),
    decision: typeof base["decision"] === "object" && base["decision"] !== null
      ? String((base["decision"] as Record<string, unknown>)["decision"] ?? "")
      : typeof base["decision"] === "string" ? base["decision"] : null,
    score: typeof base["decision"] === "object" && base["decision"] !== null && (base["decision"] as Record<string, unknown>)["score"] != null
      ? Number((base["decision"] as Record<string, unknown>)["score"])
      : null,
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
      method: "POST",
      // 后端 EnrollmentReviewSerializer 仅收大写 APPROVE/REJECT，备注字段为 note
      body: {
        decision: payload.decision.toUpperCase(),
        ...(payload.decision_note != null ? { note: payload.decision_note } : {}),
      },
      idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
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
      toolchains: Array<{
        language: string;
        toolchain_id: string;
        versions: Array<{ version: string; default: boolean }>;
        default_standard: string;
        standards: string[];
        entrypoint: string;
        available: boolean;
      }>;
    }>(`/teaching/courses/${courseId}/template-options`).then((r) => r.data),

  templateAssets: (courseId: string, templateId: string, versionId: string) =>
    request<Array<Record<string, unknown>>>(
      `/teaching/courses/${courseId}/templates/${templateId}/assets?version_id=${encodeURIComponent(versionId)}`,
    ).then(toList),

  createTemplateAsset: (
    courseId: string,
    templateId: string,
    payload: {
      version_id: string; purpose: string; file_name: string; media_type: string;
      size_bytes: number; digest_sha256: string;
    },
    ifMatch: string | number | null,
  ) => request<{ asset: Record<string, unknown>; upload: { url: string; fields: Record<string, string> } }>(
    `/teaching/courses/${courseId}/templates/${templateId}/assets`,
    { method: "POST", body: payload, idempotencyKey: newIdempotencyKey(), ifMatch },
  ).then((r) => r.data),

  completeTemplateAsset: (
    courseId: string, templateId: string, assetId: string, ifMatch: string | number | null,
  ) => request<Record<string, unknown>>(
    `/teaching/courses/${courseId}/templates/${templateId}/assets/${assetId}/complete`,
    { method: "POST", body: {}, idempotencyKey: newIdempotencyKey(), ifMatch },
  ).then((r) => r.data),

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
      tests_json: string; schema_version: 2; language: string | null;
      toolchain_version: string | null; language_standard: string | null;
      entrypoint: string | null;
      timeout_seconds: number; memory_mb: number; cpu_millicores: number;
      comparator: string; absolute_tolerance: number; relative_tolerance: number;
      network_mode: string;
      materials: Array<{ asset_id: string; role: string }>;
    },
    ifMatch: string | number | null,
    reuseKey?: string,
  ) =>
    request<TemplateVersion>(`/teaching/courses/${courseId}/template-versions/${versionId}/execution-spec`, {
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

  createRetakePublication: (
    courseId: string,
    publicationId: string,
    payload: { selected_enrollment_ids: string[]; window_start: string; window_end: string },
    reuseKey?: string,
  ) => request<Publication>(`/teaching/courses/${courseId}/experiments/${publicationId}/retakes`, {
    method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(),
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
    request<Partial<Task>[]>(`/teaching/courses/${courseId}/tasks`, { query }).then(taskListEnvelope),

  studentTaskWorkspace: (courseId: string, taskId: string) =>
    request<Record<string, unknown>>(`/teaching/courses/${courseId}/tasks/${taskId}/workspace`).then((r) => r.data),

  operationReplay: (courseId: string, taskId: string) =>
    request<Array<Record<string, unknown>>>(`/teaching/courses/${courseId}/tasks/${taskId}/operation-replay`).then(toList),

  // 评审
  reviews: (courseId: string, query?: { status?: string; page?: number; publication_id?: string; page_size?: number }) =>
    request<ReviewSummary[]>(`/teaching/courses/${courseId}/reviews`, { query }).then(toList),

  rubrics: (courseId: string) =>
    request<Rubric[]>(`/teaching/courses/${courseId}/rubrics`).then(toList),

  review: (courseId: string, reviewId: string) =>
    request<unknown>(`/teaching/courses/${courseId}/reviews/${reviewId}`, { query: { include_source: "1" } })
      .then((r) => r.data)
      .then(normalizeReviewDetail),

  aiScoreBatches: (courseId: string, publicationId: string) =>
    request<{ batches: AIScoreBatch[] }>(`/teaching/courses/${courseId}/ai-score-batches`, {
      query: { publication_id: publicationId },
    }).then((r) => r.data.batches),

  startAIScoreBatch: (courseId: string, publicationId: string) =>
    request<AIScoreBatch>(`/teaching/courses/${courseId}/ai-score-batches`, {
      method: "POST", body: { publication_id: publicationId }, idempotencyKey: newIdempotencyKey(),
    }).then((r) => r.data),

  aiScoreSuggestion: async (courseId: string, batchId: string, reviewId: string) => {
    let page = 1;
    while (true) {
      const { data } = await request<{ suggestions: AIScoreSuggestion[]; total: number }>(
        `/teaching/courses/${courseId}/ai-score-batches/${batchId}`, { query: { page, page_size: 100 } },
      );
      const suggestion = data.suggestions.find((item) => item.review_id === reviewId);
      if (suggestion || page * 100 >= data.total) return suggestion ?? null;
      page += 1;
    }
  },

  acceptAIScoreSuggestion: (courseId: string, reviewId: string, suggestionId: string, ifMatch: string) =>
    request<AIScoreSuggestion>(`/teaching/courses/${courseId}/reviews/${reviewId}/ai-score-suggestions/${suggestionId}/accept`, {
      method: "POST", body: {}, idempotencyKey: newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  saveCriterionScores: (courseId: string, reviewId: string, payload: { scores: Array<{ criterion_id: string; score: number; note?: string }> }, ifMatch?: string, reuseKey?: string) =>
    request<ReviewDetail>(`/teaching/courses/${courseId}/reviews/${reviewId}/criterion-scores`, {
      method: "PUT", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  addAnnotation: (courseId: string, reviewId: string, payload: { body: string; target_ref: string; anchor: Record<string, unknown> }, ifMatch: string, reuseKey?: string) =>
    request<unknown>(`/teaching/courses/${courseId}/reviews/${reviewId}/annotations`, {
      method: "POST",
      // 契约 AnnotationWriteSerializer：target_type/target_ref/anchor 必填
      body: { target_type: "REPORT_TEXT", target_ref: payload.target_ref, anchor: payload.anchor, body: payload.body },
      idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  revokeAnnotation: (courseId: string, reviewId: string, annotationId: string, ifMatch: string, reuseKey?: string) =>
    request(`/teaching/courses/${courseId}/reviews/${reviewId}/annotations/${annotationId}/revoke`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  decideReview: (courseId: string, reviewId: string, payload: { decision: "approve" | "return"; note?: string }, ifMatch: string, reuseKey?: string) =>
    request<ReviewDetail>(`/teaching/courses/${courseId}/reviews/${reviewId}/decide`, {
      method: "POST",
      // 后端 ReviewDecisionEnum 仅收大写 APPROVE/REJECT；页面语义 return(退回修改)对应 REJECT
      body: {
        decision: payload.decision === "approve" ? "APPROVE" : "REJECT",
        ...(payload.note ? { feedback: payload.note } : {}),
      },
      idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
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
      method: "POST",
      // 后端 IdentityReviewSerializer 仅收大写 APPROVE/REJECT，备注字段为 reason
      body: {
        decision: payload.decision.toUpperCase(),
        ...(payload.note != null ? { reason: payload.note } : {}),
      },
      idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
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
      method: "POST",
      // 后端 decide_image 仅收大写 APPROVED/REJECTED，备注字段为 reason
      body: {
        decision: payload.decision === "approve" ? "APPROVED" : "REJECTED",
        ...(payload.note != null ? { reason: payload.note } : {}),
      },
      idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  createImage: (payload: ImageCreateInput, reuseKey?: string) =>
    request<PlatformImage>("/platform/images", {
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

  resolveImage: (imageId: string, ifMatch: string, reuseKey?: string) =>
    request<PlatformImage>(`/platform/images/${imageId}/resolve`, {
      method: "POST",
      body: {},
      idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  /* 镜像在运行时重建后摘要漂移:重新向运行时解析当前摘要(后台任务) */
  reResolveImage: (imageId: string, ifMatch: string, reuseKey?: string) =>
    request<PlatformImage>(`/platform/images/${imageId}/re-resolve`, {
      method: "POST",
      body: {},
      idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  reportImageScan: (imageId: string, payload: ImageScanReportInput, ifMatch: string, reuseKey?: string) =>
    request<PlatformImage>(`/platform/images/${imageId}`, {
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
    request<OperationLog[]>("/platform/operations/audit", { query }).then(toList),

  agentModelRoutes: () =>
    request<ModelRoute[]>("/platform/agent/model-routes").then(toList),

  agentToolPolicies: () =>
    request<ToolPolicy[]>("/platform/agent/tool-policies").then(toList),

  agentUsageCosts: (query?: { page?: number; page_size?: number; window?: string }) =>
    request<UsageCost[]>("/platform/agent/usage-costs", { query }).then(toList),
};
