export const systemKeys = {
  all: ['system'] as const,
  health: () => [...systemKeys.all, 'health'] as const,
}

export const accountKeys = {
  all: ['accounts'] as const,
  me: () => ['me'] as const,
  verification: () => [...accountKeys.all, 'verification'] as const,
  users: (filters: object = {}) => [...accountKeys.all, 'users', filters] as const,
  teachers: (filters: object = {}) => [...accountKeys.all, 'teachers', filters] as const,
  admins: (filters: object = {}) => [...accountKeys.all, 'admins', filters] as const,
  verifications: (filters: object = {}) => [...accountKeys.all, 'verifications', filters] as const,
}

export const courseKeys = {
  all: ['courses'] as const,
  catalog: (filters: object = {}) => [...courseKeys.all, 'catalog', filters] as const,
  detail: (courseId: string) => [...courseKeys.all, 'detail', courseId] as const,
  content: (courseId: string, resource: string) => [...courseKeys.all, 'content', courseId, resource] as const,
  myEnrollments: (filters: object = {}) => ['me', 'enrollments', filters] as const,
  teaching: (filters: object = {}) => ['teaching', 'courses', filters] as const,
  teachingDetail: (courseId: string) => ['teaching', 'courses', courseId] as const,
  staff: (courseId: string) => ['teaching', 'courses', courseId, 'staff'] as const,
  roster: (courseId: string, filters: object = {}) => ['teaching', 'courses', courseId, 'enrollments', filters] as const,
  job: (courseId: string, jobId: string) => ['teaching', 'courses', courseId, 'jobs', jobId] as const,
}

export const governanceKeys = {
  all: ['governance'] as const,
  runtimes: () => [...governanceKeys.all, 'runtimes'] as const,
  images: () => [...governanceKeys.all, 'images'] as const,
  profiles: () => [...governanceKeys.all, 'profiles'] as const,
  quotas: () => [...governanceKeys.all, 'quotas'] as const,
  policies: (kind = 'RUNTIME_SECURITY') => [...governanceKeys.all, 'policies', kind] as const,
  allowlists: () => [...governanceKeys.all, 'allowlists'] as const,
  usage: () => [...governanceKeys.all, 'usage'] as const,
  alerts: () => [...governanceKeys.all, 'alerts'] as const,
  courseSummary: (courseId: string) => [...governanceKeys.all, 'course', courseId] as const,
  resourceSummary: (courseId: string) => [...governanceKeys.all, 'resource', courseId] as const,
}

export const templateKeys = {
  all: ['templates'] as const,
  list: (courseId: string) => [...templateKeys.all, courseId, 'list'] as const,
  options: (courseId: string) => [...templateKeys.all, courseId, 'options'] as const,
  detail: (courseId: string, templateId: string) => [...templateKeys.all, courseId, templateId] as const,
  versions: (courseId: string, templateId: string) => [...templateKeys.detail(courseId, templateId), 'versions'] as const,
  version: (courseId: string, versionId: string) => [...templateKeys.all, courseId, 'versions', versionId] as const,
  prechecks: (courseId: string, versionId: string) => [...templateKeys.version(courseId, versionId), 'prechecks'] as const,
  asset: (courseId: string, templateId: string, assetId: string) => [...templateKeys.detail(courseId, templateId), 'assets', assetId] as const,
  platformSummary: () => [...templateKeys.all, 'platform-summary'] as const,
}

export const rubricKeys = {
  all: ['rubrics'] as const,
  list: (courseId: string) => [...rubricKeys.all, courseId, 'list'] as const,
  versions: (courseId: string, rubricId: string) => [...rubricKeys.all, courseId, rubricId, 'versions'] as const,
  version: (courseId: string, versionId: string) => [...rubricKeys.all, courseId, 'versions', versionId] as const,
}

export const experimentKeys = {
  all: ['experiments'] as const,
  publications: (courseId: string) => [...experimentKeys.all, 'publications', courseId] as const,
  publication: (courseId: string, publicationId: string) => [...experimentKeys.publications(courseId), publicationId] as const,
  tasks: (courseId: string, publicationId: string, filters: object = {}) => [...experimentKeys.publication(courseId, publicationId), 'tasks', filters] as const,
  progress: (courseId: string) => [...experimentKeys.all, 'progress', courseId] as const,
  extensionRequests: (courseId: string, filters: object = {}) => [...experimentKeys.all, 'extensions', courseId, filters] as const,
  dashboard: () => ['me', 'experiment-dashboard'] as const,
  myTasks: (filters: object = {}) => ['me', 'experiment-tasks', filters] as const,
  task: (taskId: string) => ['me', 'experiment-task', taskId] as const,
  provisioningJob: (taskId: string) => [...experimentKeys.task(taskId), 'provisioning-job'] as const,
  transitions: (taskId: string) => [...experimentKeys.task(taskId), 'transitions'] as const,
  extensions: (taskId: string) => [...experimentKeys.task(taskId), 'extensions'] as const,
  anomalies: () => [...experimentKeys.all, 'anomalies'] as const,
}

export const workspaceKeys = {
  all: ['workspaces'] as const,
  workbench: (taskId: string) => [...workspaceKeys.all, 'workbench', taskId] as const,
  session: (taskId: string) => [...workspaceKeys.all, 'session', taskId] as const,
  snapshot: (taskId: string) => [...workspaceKeys.all, 'snapshot', taskId] as const,
  storageJob: (jobId: string) => [...workspaceKeys.all, 'storage-job', jobId] as const,
  checkpoints: (taskId: string) => [...workspaceKeys.all, 'checkpoints', taskId] as const,
  replay: (taskId: string, scope = 'user') => [...workspaceKeys.all, 'replay', scope, taskId] as const,
  executions: (taskId: string) => [...workspaceKeys.all, 'executions', taskId] as const,
  execution: (taskId: string, executionId: string) => [...workspaceKeys.executions(taskId), executionId] as const,
  teacher: (courseId: string, taskId: string) => [...workspaceKeys.all, 'teacher', courseId, taskId] as const,
  adminSessions: () => [...workspaceKeys.all, 'admin', 'sessions'] as const,
}

export const reportKeys = {
  all: ['reports'] as const,
  draft: (taskId: string) => [...reportKeys.all, 'draft', taskId] as const,
  versions: (taskId: string) => [...reportKeys.all, 'versions', taskId] as const,
  preview: (courseId: string, taskId: string) => [...reportKeys.all, 'preview', courseId, taskId] as const,
  scanAnomalies: () => [...reportKeys.all, 'scan-anomalies'] as const,
}

export const reviewKeys = {
  all: ['reviews'] as const,
  queue: (courseId: string, filters: object = {}) => [...reviewKeys.all, 'queue', courseId, filters] as const,
  detail: (courseId: string, reviewId: string) => [...reviewKeys.all, 'detail', courseId, reviewId] as const,
  scores: (courseId: string, reviewId: string) => [...reviewKeys.detail(courseId, reviewId), 'scores'] as const,
  annotations: (courseId: string, reviewId: string) => [...reviewKeys.detail(courseId, reviewId), 'annotations'] as const,
  similarity: (courseId: string, runId: string) => [...reviewKeys.all, 'similarity', courseId, runId] as const,
  similarityMatches: (courseId: string, runId: string) => [...reviewKeys.similarity(courseId, runId), 'matches'] as const,
  result: (taskId: string) => [...reviewKeys.all, 'result', taskId] as const,
  monitor: () => [...reviewKeys.all, 'monitor'] as const,
}

export const archiveKeys = {
  all: ['archives'] as const,
  user: (taskId: string) => [...archiveKeys.all, 'user', taskId] as const,
  course: (courseId: string) => [...archiveKeys.all, 'course', courseId] as const,
  detail: (courseId: string, archiveId: string) => [...archiveKeys.course(courseId), archiveId] as const,
  instances: () => [...archiveKeys.all, 'platform', 'instances'] as const,
  compensations: (status = '') => [...archiveKeys.all, 'platform', 'compensations', status] as const,
}

export const agentKeys = {
  all: ['agents'] as const,
  profile: (courseId: string) => [...agentKeys.all, 'profile', courseId] as const,
  sessions: (courseId: string) => [...agentKeys.all, 'sessions', courseId] as const,
  session: (sessionId: string) => [...agentKeys.all, 'session', sessionId] as const,
  messages: (sessionId: string) => [...agentKeys.session(sessionId), 'messages'] as const,
  teachingProfiles: (courseId: string) => [...agentKeys.all, 'teaching', 'profiles', courseId] as const,
  teachingKnowledge: (courseId: string) => [...agentKeys.all, 'teaching', 'knowledge', courseId] as const,
  teachingFeedback: (courseId: string) => [...agentKeys.all, 'teaching', 'feedback', courseId] as const,
  platformPolicies: () => [...agentKeys.all, 'platform', 'policies'] as const,
}

export const notificationKeys = {
  all: ['notifications'] as const,
  list: (portal = '') => [...notificationKeys.all, 'list', portal] as const,
  preference: (portal = '') => [...notificationKeys.all, 'preference', portal] as const,
}

export const analyticsKeys = {
  all: ['analytics'] as const,
  recommendations: () => [...analyticsKeys.all, 'recommendations'] as const,
  risks: (courseId = '') => [...analyticsKeys.all, 'risks', courseId] as const,
  overview: (courseId: string) => [...analyticsKeys.all, 'overview', courseId] as const,
  quality: (courseId: string) => [...analyticsKeys.all, 'quality', courseId] as const,
  resourceCosts: (courseId: string) => [...analyticsKeys.all, 'resource-costs', courseId] as const,
  projections: () => [...analyticsKeys.all, 'projections'] as const,
}

export const integrationKeys = {
  all: ['integrations'] as const,
  providers: () => [...integrationKeys.all, 'providers'] as const,
  clients: () => [...integrationKeys.all, 'clients'] as const,
  deliveries: () => [...integrationKeys.all, 'deliveries'] as const,
}
