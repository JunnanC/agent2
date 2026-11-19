import { newIdempotencyKey, request } from "@edu/auth-client";
import type { EnvelopeSuccess } from "@edu/auth-client";
import type {
  Anomaly, Announcement, CalendarEvent, Chapter, Compensation, Course,
  Enrollment, ImageCreateInput, ImageScanReportInput, ImportJob, Invitation, Material, Me,
  ModelRoute, NotificationItem, OperationLog, OperationsOverview, PlatformImage, PlatformUser,
  PortalContext, PrecheckRun, Publication, Quota, ResourceProfile, Rubric,
  RuntimeAdapter, StudentDashboard, Task, TeachingCourseList, Template,
  TemplateChapter, TemplateTask, ToolPolicy, TemplateVersion, UsageCost, Verification,
  AgentMessage, AgentMode, CourseResourceSummary,
  LearningHistoryData, NotificationPreferences, TimetableData, TimetableImport, AgentProfile, AgentSession,
  AgentToolCall, ToolRequest, ToolDecision, AgentFeedback, VerificationUpdate, NotificationPreferenceUpdate,
  EnrollmentExitCheck, CourseQuestion, CourseAnswer, DownloadGrant, DownloadGrantRevoke,
  ReportAttachmentData, ReportAttachmentUpload, ReportAttachmentCreate, LearningRecommendation, LearningRiskSignal,
  OIDCIdentity, OIDCStart,
} from "./types";

export * from "./types";
export * from "./assessment";

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
    request<Array<Chapter & { content?: string; summary?: string; position?: number }>>(`/courses/${courseId}/chapters`).then((r) => {
      const list = toList(r);
      return { ...list, rows: list.rows.map((chapter) => ({ ...chapter, description: chapter.summary || chapter.description, sort_order: chapter.position ?? chapter.sort_order })) };
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

  /** 邀请码提交入课申请，教师审核后生效。 */
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

  extensions: (taskId: string) =>
    request<Array<Record<string, unknown>>>(`/tasks/${taskId}/extensions`).then(toList),

  requestExtension: (taskId: string, payload: { reason: string }, ifMatch: string, reuseKey?: string) =>
    request(`/tasks/${taskId}/extension-requests`, {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

  archive: (taskId: string) => request<Record<string, unknown>>(`/tasks/${taskId}/archive`).then((r) => r.data),

};

/* ══════════ 报告 ══════════ */

export const reportApi = {
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

  createAnnouncement: (courseId: string, payload: { title: string; body?: string; pinned?: boolean }, reuseKey?: string) =>
    request<Announcement>(`/teaching/courses/${courseId}/announcements`, {
      method: "POST", body: payload, idempotencyKey: reuseKey ?? newIdempotencyKey(),
    }).then((r) => r.data),

  publishAnnouncement: (courseId: string, announcementId: string, ifMatch: string, reuseKey?: string) =>
    request<Announcement>(`/teaching/courses/${courseId}/announcements/${announcementId}/publish`, {
      method: "POST", body: {}, idempotencyKey: reuseKey ?? newIdempotencyKey(), ifMatch,
    }).then((r) => r.data),

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
      images: Array<{ public_id: string; repository: string; display_name?: string; display_tag?: string; digest: string; risk_level?: string }>;
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



  rubrics: (courseId: string) =>
    request<Rubric[]>(`/teaching/courses/${courseId}/rubrics`).then(toList),

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

export interface StudentImportRow {
  row_number: number; student_number: string; status: "CREATED" | "FAILED";
  user_id?: string; error?: string;
}

export const platformApi = {
  importStudents: (csv: string, idempotencyKey: string) =>
    request<{ rows: StudentImportRow[] }>("/platform/student-imports", {
      method: "POST", body: { csv }, idempotencyKey,
    }).then((r) => r.data),
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
