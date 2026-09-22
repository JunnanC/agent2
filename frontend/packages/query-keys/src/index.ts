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
