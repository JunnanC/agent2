import type { components, paths } from './generated/schema'

export type HealthResponse =
  paths['/api/v2/health']['get']['responses'][200]['content']['application/json']
export type MeResponse = components['schemas']['MeResponse']
export type MeData = components['schemas']['MeData']
export type UserData = components['schemas']['UserData']
export type VerificationData = components['schemas']['VerificationData']
export type QualificationData = components['schemas']['QualificationData']
export type AdminAssignmentData = components['schemas']['AdminAssignmentData']
export type CourseData = components['schemas']['CourseData']
export type CourseListResponse = components['schemas']['CourseListResponse']
export type CourseResponse = components['schemas']['CourseResponse']
export type EnrollmentData = components['schemas']['EnrollmentData']
export type EnrollmentListResponse = components['schemas']['EnrollmentListResponse']
export type EnrollmentResponse = components['schemas']['EnrollmentResponse']
export type StaffData = components['schemas']['StaffData']
export type GrantData = components['schemas']['GrantData']
export type RuntimeAdapterData = components['schemas']['RuntimeAdapterData']
export type RuntimeAdapterListResponse = components['schemas']['RuntimeAdapterListResponse']
export type RuntimeAdapterResponse = components['schemas']['RuntimeAdapterResponse']
export type ImageData = components['schemas']['ImageData']
export type ImageListResponse = components['schemas']['ImageListResponse']
export type ImageResponse = components['schemas']['ImageResponse']
export type ResourceProfileData = components['schemas']['ResourceProfileData']
export type ResourceProfileListResponse = components['schemas']['ResourceProfileListResponse']
export type ResourceProfileResponse = components['schemas']['ResourceProfileResponse']
export type QuotaData = components['schemas']['QuotaData']
export type QuotaListResponse = components['schemas']['QuotaListResponse']
export type QuotaResponse = components['schemas']['QuotaResponse']
export type PolicyData = components['schemas']['PolicyData']
export type PolicyListResponse = components['schemas']['PolicyListResponse']
export type PolicyResponse = components['schemas']['PolicyResponse']
export type AllowlistData = components['schemas']['AllowlistData']
export type AllowlistListResponse = components['schemas']['AllowlistListResponse']
export type AllowlistResponse = components['schemas']['AllowlistResponse']
export type ResourceSummaryData = components['schemas']['ResourceSummaryData']
export type ResourceSummaryResponse = components['schemas']['ResourceSummaryResponse']
export type UsageResponse = components['schemas']['UsageResponse']
export type AlertListResponse = components['schemas']['AlertListResponse']
export type TemplateData = components['schemas']['TemplateData']
export type TemplateListResponse = components['schemas']['TemplateListResponse']
export type TemplateResponse = components['schemas']['TemplateResponse']
export type TemplateVersionData = components['schemas']['TemplateVersionData']
export type TemplateVersionListResponse = components['schemas']['TemplateVersionListResponse']
export type TemplateVersionResponse = components['schemas']['TemplateVersionResponse']
export type TemplateOptionsResponse = components['schemas']['TemplateOptionsResponse']
export type PrecheckRunData = components['schemas']['PrecheckRunData']
export type PrecheckRunListResponse = components['schemas']['PrecheckRunListResponse']
export type PrecheckRunResponse = components['schemas']['PrecheckRunResponse']
export type TemplateAssetData = components['schemas']['TemplateAssetData']
export type TemplateAssetResponse = components['schemas']['TemplateAssetResponse']
export type TemplateAssetUploadResponse = components['schemas']['TemplateAssetUploadResponse']
export type RubricData = components['schemas']['RubricData']
export type RubricListResponse = components['schemas']['RubricListResponse']
export type RubricResponse = components['schemas']['RubricResponse']
export type RubricVersionData = components['schemas']['RubricVersionData']
export type RubricVersionListResponse = components['schemas']['RubricVersionListResponse']
export type RubricVersionResponse = components['schemas']['RubricVersionResponse']
export type PlatformPrecheckSummaryResponse = components['schemas']['PlatformPrecheckSummaryResponse']
export type PublicationData = components['schemas']['PublicationData']
export type TaskData = components['schemas']['TaskData']
export type ProvisioningJob = components['schemas']['ProvisioningJob']
export type ProvisioningStageEvent = components['schemas']['ProvisioningStageEvent']
export type ProvisioningActionResponse = components['schemas']['ProvisioningActionResponse']
export type DashboardData = components['schemas']['DashboardData']
export type ExtensionData = components['schemas']['ExtensionData']
export type TransitionData = components['schemas']['TransitionData']
export type GenericResponse = components['schemas']['GenericResponse']
export type PublicationWrite = components['schemas']['PublicationWrite']
export type PublicationPatch = components['schemas']['PatchedPublicationPatch']
export type TaskExtensionWrite = components['schemas']['TaskExtensionWrite']
export type TaskExtensionDecision = components['schemas']['TaskExtensionDecision']
export type ChapterData = Record<string, unknown>
export type MaterialData = Record<string, unknown>
export type QuestionData = Record<string, unknown>

export interface ApiFailure {
  error: {
    code: string
    message: string
    detail: unknown
    trace_id: string
    retryable: boolean
  }
}

export interface PageMeta {
  page: number
  page_size: number
  total: number
  trace_id: string
}

export interface ListEnvelope<T> {
  data: T[]
  meta: PageMeta
}

export interface ApiResult<T> {
  payload: T
  etag: string | null
  traceId: string
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly payload: ApiFailure,
  ) {
    super(payload.error.message)
    this.name = 'ApiError'
  }

  get traceId(): string {
    return this.payload.error.trace_id
  }
}

function bodyFingerprint(body: BodyInit | null | undefined): string {
  if (body == null) return ''
  if (typeof body === 'string') return body
  if (body instanceof URLSearchParams) return body.toString()
  if (body instanceof FormData) {
    return JSON.stringify(
      Array.from(body.entries(), ([key, value]) => [
        key,
        typeof value === 'string' ? value : `${value.name}:${value.size}:${value.type}`,
      ]),
    )
  }
  throw new TypeError('Idempotent requests require a stable string, URLSearchParams, or FormData body')
}

export class RequestIntent {
  readonly key: string
  private fingerprint: string | undefined

  constructor(key: string = crypto.randomUUID()) {
    this.key = key
  }

  bind(body: BodyInit | null | undefined): string {
    const next = bodyFingerprint(body)
    if (this.fingerprint !== undefined && this.fingerprint !== next) {
      throw new Error('Request body changed; create a new RequestIntent')
    }
    this.fingerprint = next
    return this.key
  }
}

export interface ApiRequestInit extends RequestInit {
  ifMatch?: string
  intent?: RequestIntent
}

function csrfToken(): string | undefined {
  const item = document.cookie
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith('csrftoken='))
  return item ? decodeURIComponent(item.slice('csrftoken='.length)) : undefined
}

function isUnsafeMethod(method: string): boolean {
  return !['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method)
}

function normalizeFailure(status: number, value: unknown, traceId: string): ApiFailure {
  if (
    typeof value === 'object' &&
    value !== null &&
    'error' in value &&
    typeof value.error === 'object' &&
    value.error !== null
  ) {
    return value as ApiFailure
  }
  return {
    error: {
      code: `HTTP_${status}`,
      message: '请求无法处理',
      detail: {},
      trace_id: traceId,
      retryable: status === 429 || status >= 500,
    },
  }
}

export async function apiRequestWithMetadata<T>(
  path: string,
  init: ApiRequestInit = {},
): Promise<ApiResult<T>> {
  if (!path.startsWith('/')) throw new TypeError('API requests must use same-origin relative paths')
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (!headers.has('Accept')) headers.set('Accept', 'application/json')
  if (isUnsafeMethod(method) && !headers.has('X-CSRFToken')) {
    const token = csrfToken()
    if (token) headers.set('X-CSRFToken', token)
  }
  if (init.ifMatch) headers.set('If-Match', init.ifMatch)
  if (init.intent) headers.set('Idempotency-Key', init.intent.bind(init.body))

  const requestInit = { ...init }
  delete requestInit.ifMatch
  delete requestInit.intent
  const response = await fetch(path, {
    ...requestInit,
    method,
    credentials: 'include',
    headers,
  })
  const traceId = response.headers.get('X-Request-ID') ?? ''
  const text = await response.text()
  let value: unknown = undefined
  if (text) {
    try {
      value = JSON.parse(text)
    } catch {
      value = undefined
    }
  }
  if (!response.ok) throw new ApiError(response.status, normalizeFailure(response.status, value, traceId))
  return {
    payload: value as T,
    etag: response.headers.get('ETag'),
    traceId,
  }
}

export async function apiRequest<T>(path: string, init?: ApiRequestInit): Promise<T> {
  return (await apiRequestWithMetadata<T>(path, init)).payload
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiRequest<HealthResponse>('/api/v2/health', { signal })
}
