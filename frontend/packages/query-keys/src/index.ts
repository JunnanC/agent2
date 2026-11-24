/**
 * TanStack Query 键工厂。
 * 约定：数组第一段为域，第二段为资源/视图，第三段为筛选或 id。
 * SSE 事件只触发对应域的失效；logout / SESSION_EXPIRED 时清空整个缓存。
 */

export type QueryFilter = Record<string, string | number | boolean | null | undefined>;

const stable = (filter: QueryFilter = {}): Array<string | number | boolean> => {
  const entries = Object.entries(filter)
    .filter(([, value]) => value != null && value !== "")
    .sort(([a], [b]) => a.localeCompare(b));
  return entries.map(([key, value]) => `_${key}=${String(value)}`);
};

export const keys = {
  /* 通用 */
  me: () => ["me"] as const,
  context: () => ["context"] as const,
  notifications: (filter?: QueryFilter) => ["notifications", ...stable(filter)] as const,
  notificationPreferences: () => ["notification-preferences"] as const,

  /* 学生端 */
  studentDashboard: () => ["student", "dashboard", stable()] as const,
  courses: (filter: QueryFilter = {}) => ["courses", ...stable(filter)] as const,
  enrollments: (filter: QueryFilter = {}) => ["student-enrollments", ...stable(filter)] as const,
  enrollment: (id: string) => ["student-enrollments", id] as const,
  timetable: (termId?: string) => ["student", "timetable", termId ?? "current"] as const,
  releasedGrades: (courseId: string, publications: string[] = []) => ["teaching", "released-grades", courseId, ...publications] as const,
  teachingTimetable: (termId?: string) => ["teaching", "timetable", ...(termId ? [termId] : [])] as const,
  teachingCourseTimetable: (courseId: string) => ["teaching", "timetable", "course", courseId] as const,
  timetableImports: () => ["teaching", "timetable-imports"] as const,
  timetableImport: (jobId: string) => ["teaching", "timetable-imports", jobId] as const,
  learningHistory: () => ["student", "learning-history"] as const,
  agentProfile: (courseId: string) => ["courses", courseId, "agent-profile"] as const,
  activeAgentSession: (courseId: string, taskId?: string) => ["active-agent-session", courseId, taskId ?? "course"] as const,
  agentSession: (sessionId: string) => ["agent-sessions", sessionId] as const,
  agentMessages: (sessionId: string) => ["agent-sessions", sessionId, "messages"] as const,
  course: (courseId: string) => ["courses", courseId] as const,
  courseResource: (courseId: string, resource: string, filter: QueryFilter = {}) =>
    ["courses", courseId, resource, ...stable(filter)] as const,
  tasks: (filter: QueryFilter = {}) => ["tasks", ...stable(filter)] as const,
  task: (taskId: string) => ["tasks", taskId] as const,
  assessment: (taskId: string) => ["tasks", taskId, "assessment"] as const,
  assessmentDraft: (taskId: string, questionId: string, language: string = "choice") =>
    ["tasks", taskId, "assessment", "drafts", questionId, language] as const,
  taskTransitions: (taskId: string) => ["tasks", taskId, "transitions"] as const,
  taskExtension: (taskId: string) => ["tasks", taskId, "extensions"] as const,
  reportAttachments: (taskId: string) => ["tasks", taskId, "attachments"] as const,
  riskSignals: (filter: QueryFilter = {}) => ["analytics", "risk-signals", ...stable(filter)] as const,
  recommendations: (filter: QueryFilter = {}) => ["analytics", "recommendations", ...stable(filter)] as const,

  /* 教师端 */
  teachingCourses: (filter: QueryFilter = {}) => ["teaching-courses", ...stable(filter)] as const,
  teachingCourse: (courseId: string) => ["teaching-courses", courseId] as const,
  teachingCourseResource: (courseId: string, resource: string, filter: QueryFilter = {}) =>
    ["teaching-courses", courseId, resource, ...stable(filter)] as const,
  teachingEnrollments: (courseId: string, filter: QueryFilter = {}) =>
    ["teaching-courses", courseId, "enrollments", ...stable(filter)] as const,
  teachingEnrollment: (courseId: string, enrollmentId: string) =>
    ["teaching-courses", courseId, "enrollments", enrollmentId] as const,
  teachingStaff: (courseId: string) => ["teaching-courses", courseId, "staff"] as const,
  invitations: (courseId: string) => ["teaching-courses", courseId, "invitations"] as const,
  importJob: (courseId: string, jobId: string) => ["teaching-courses", courseId, "enrollment-imports", jobId] as const,
  templates: (courseId: string, filter: QueryFilter = {}) =>
    ["teaching-templates", courseId, ...stable(filter)] as const,
  template: (courseId: string, templateId: string) => ["teaching-templates", courseId, templateId] as const,
  templateOptions: (courseId: string) => ["teaching-templates", courseId, "options"] as const,
  templateVersions: (courseId: string, templateId: string) =>
    ["teaching-templates", courseId, templateId, "versions"] as const,
  templateVersion: (_courseId: string, versionId: string) =>
    ["teaching-template-versions", versionId] as const,
  templateChapters: (versionId: string) => ["teaching-template-versions", versionId, "chapters"] as const,
  templateChapterTasks: (chapterId: string) =>
    ["teaching-template-chapters", chapterId, "tasks"] as const,
  precheckRuns: (versionId: string, filter: QueryFilter = {}) =>
    ["teaching-template-versions", versionId, "precheck-runs", ...stable(filter)] as const,
  experimentImages: (courseId: string, filter: QueryFilter = {}) =>
    ["teaching-experiment-images", courseId, ...stable(filter)] as const,
  publications: (courseId: string, filter: QueryFilter = {}) =>
    ["teaching-publications", courseId, ...stable(filter)] as const,
  publication: (courseId: string, publicationId: string) =>
    ["teaching-publications", courseId, publicationId] as const,
  publicationTasks: (courseId: string, publicationId: string, filter: QueryFilter = {}) =>
    ["teaching-publications", courseId, publicationId, "tasks", ...stable(filter)] as const,
  rubrics: (courseId: string) => ["teaching-rubrics", courseId] as const,
  reviews: (courseId: string, filter: QueryFilter = {}) =>
    ["teaching-reviews", courseId, ...stable(filter)] as const,
  review: (courseId: string, reviewId: string) => ["teaching-reviews", courseId, reviewId] as const,
  reviewScores: (courseId: string, reviewId: string) =>
    ["teaching-reviews", courseId, reviewId, "criterion-scores"] as const,
  reviewAnnotations: (courseId: string, reviewId: string) =>
    ["teaching-reviews", courseId, reviewId, "annotations"] as const,
  similarityRun: (_courseId: string, runId: string) => ["teaching-similarity-runs", runId] as const,
  teachingAnalytics: (courseId: string, section: string, filter: QueryFilter = {}) =>
    ["teaching-analytics", courseId, section, ...stable(filter)] as const,
  teachingProgress: (courseId: string, filter: QueryFilter = {}) =>
    ["teaching-analytics", courseId, "progress", ...stable(filter)] as const,

  /* 平台端 */
  platformUsers: (filter: QueryFilter = {}) => ["platform", "users", ...stable(filter)] as const,
  verifications: (filter: QueryFilter = {}) => ["platform", "verifications", ...stable(filter)] as const,
  governanceAlerts: (filter: QueryFilter = {}) => ["platform", "governance", "alerts", ...stable(filter)] as const,
  governanceUsage: (filter: QueryFilter = {}) => ["platform", "governance", "usage", ...stable(filter)] as const,
  precheckSummary: (filter: QueryFilter = {}) =>
    ["platform", "template-prechecks", "summary", ...stable(filter)] as const,
  images: (filter: QueryFilter = {}) => ["platform", "images", ...stable(filter)] as const,
  image: (imageId: string) => ["platform", "images", imageId] as const,
  resourceProfiles: (filter: QueryFilter = {}) => ["platform", "resource-profiles", ...stable(filter)] as const,
  runtimeAdapters: (filter: QueryFilter = {}) => ["platform", "runtime-adapters", ...stable(filter)] as const,
  quotas: (filter: QueryFilter = {}) => ["platform", "quotas", ...stable(filter)] as const,
  instances: (filter: QueryFilter = {}) => ["platform", "instances", ...stable(filter)] as const,
  anomalies: (filter: QueryFilter = {}) => ["platform", "anomalies", "tasks", ...stable(filter)] as const,
  scanAnomalies: (filter: QueryFilter = {}) => ["platform", "anomalies", "reports", ...stable(filter)] as const,
  operationsOverview: () => ["platform", "operations", "overview"] as const,
  operationLogs: (filter: QueryFilter = {}) => ["platform", "operations", "logs", ...stable(filter)] as const,
  agentModelRoutes: () => ["platform", "agent", "model-routes"] as const,
  agentToolPolicies: () => ["platform", "agent", "tool-policies"] as const,
  agentUsageCosts: (filter: QueryFilter = {}) => ["platform", "agent", "usage-costs", ...stable(filter)] as const,
  agentEvalSuites: () => ["platform", "agent", "eval-suites"] as const,
};

export type QueryKeyTree = typeof keys;
