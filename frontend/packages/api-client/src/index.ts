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

export type WorkspaceCapabilities = Record<string, boolean>
export type WorkspaceSessionData = {
  public_id: string
  task_id: string
  course_id: string
  instance_id: string
  portal: 'USER'
  status: 'ACTIVE' | 'REVOKED' | 'EXPIRED'
  capabilities: WorkspaceCapabilities
  expires_at: string
  revoked_at: string | null
  current_version: number
  latest_client_seq: number
  row_version: number
  workspace_token?: string
}
export type WorkspaceSnapshotData = {
  public_id: string
  task_id: string
  session_id: string
  version_no: number
  client_seq: number
  base_version: number
  digest_sha256: string
  size_bytes: number
  media_type: string
  saved_at: string
}
export type WorkspaceCheckpointData = {
  public_id: string
  task_id: string
  session_id: string
  checkpoint_no: number
  name: string
  source_seq: number
  digest_sha256: string
  version_no: number
  created_at: string
  retention_until: string | null
}
export type WorkspaceCheckpointListData = {
  items: WorkspaceCheckpointData[]
  current_version: number
  row_version: number
}
export type WorkspaceOperationData = {
  public_id: string
  task_id: string
  seq: number
  event_type: string
  phase: string
  payload: Record<string, unknown>
  result_summary: string
  occurred_at: string
  trace_id: string
}
export type WorkspaceEnvelope<T> = { data: T; meta: { trace_id?: string } }
export type ReportAttachmentData = components['schemas']['ReportAttachmentData']
export type ReportAttachmentUploadResponse = components['schemas']['ReportAttachmentUploadResponse']
export type ReportDraftResponse = components['schemas']['ReportDraftResponse']
export type ReportVersionData = components['schemas']['ReportVersionData']
export type ReportVersionListResponse = components['schemas']['ReportVersionListResponse']
export type ReportVersionResponse = components['schemas']['ReportVersionResponse']
export type SystemArtifactData = components['schemas']['SystemArtifactData']
export type ReportCompleteResponse = components['schemas']['ReportCompleteResponse']
export type ReportPreviewResponse = components['schemas']['ReportPreviewResponse']
export type ReportScanAnomalySummary = components['schemas']['ReportScanAnomalySummary']
export type DownloadGrantResponse = components['schemas']['DownloadGrantResponse']
export type DownloadGrantRevokeResponse = components['schemas']['DownloadGrantRevokeResponse']
export type ReviewListResponse = components['schemas']['ReviewListResponse']
export type ReviewDetailResponse = components['schemas']['ReviewDetailResponse']
export type CriterionScoresResponse = components['schemas']['CriterionScoresResponse']
export type AnnotationResponse = components['schemas']['AnnotationResponse']
export type ReviewDecisionResponse = components['schemas']['ReviewDecisionResponse']
export type ReviewResultResponse = components['schemas']['ReviewResultResponse']
export type SimilarityRunResponse = components['schemas']['SimilarityRunResponse']
export type SimilarityMatchListResponse = components['schemas']['SimilarityMatchListResponse']
export type ReviewMonitorResponse = components['schemas']['ReviewMonitorResponse']
export type ArchiveData = components['schemas']['ArchiveData']
export type ArchiveResponse = components['schemas']['ArchiveResponse']
export type ArchiveListResponse = components['schemas']['ArchiveListResponse']
export type ArchiveExportResponse = components['schemas']['ArchiveExportResponse']
export type InstanceData = components['schemas']['InstanceData']
export type InstanceListResponse = components['schemas']['InstanceListResponse']
export type InstanceResponse = components['schemas']['InstanceResponse']
export type CompensationData = components['schemas']['CompensationData']
export type CompensationListResponse = components['schemas']['CompensationListResponse']
export type CompensationResponse = components['schemas']['CompensationResponse']

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
  workspaceToken?: string
}

let workspaceToken: string | undefined
export function setWorkspaceToken(token: string | undefined): void { workspaceToken = token }
export function clearWorkspaceToken(): void { workspaceToken = undefined }

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
  if (init.workspaceToken ?? workspaceToken) headers.set('X-Workspace-Token', init.workspaceToken ?? workspaceToken ?? '')

  const requestInit = { ...init }
  delete requestInit.ifMatch
  delete requestInit.intent
  delete requestInit.workspaceToken
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

export async function downloadFileInMemory(
  path: string,
  onProgress?: (received: number, total: number | null) => void,
): Promise<Blob> {
  if (!path.startsWith('/files/')) throw new TypeError('Download path is invalid')
  const response = await fetch(path, { credentials: 'include', headers: { Accept: 'application/octet-stream' } })
  if (!response.ok || !response.body) throw new Error('DOWNLOAD_FAILED')
  const totalHeader = response.headers.get('Content-Length')
  const total = totalHeader ? Number(totalHeader) : null
  const reader = response.body.getReader()
  const chunks: ArrayBuffer[] = []
  let received = 0
  try {
    while (true) {
      const result = await reader.read()
      if (result.done) break
      const chunk = new Uint8Array(result.value.byteLength)
      chunk.set(result.value)
      chunks.push(chunk.buffer)
      received += result.value.byteLength
      onProgress?.(received, total)
    }
  } finally {
    reader.releaseLock()
  }
  return new Blob(chunks, { type: response.headers.get('Content-Type') ?? 'application/octet-stream' })
}

export function saveMemoryBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiRequest<HealthResponse>('/api/v2/health', { signal })
}

export async function enterWorkspace(taskId: string, ifMatch: string, intent = new RequestIntent()): Promise<ApiResult<WorkspaceEnvelope<{ task: TaskData; session: WorkspaceSessionData }>>> {
  const result = await apiRequestWithMetadata<WorkspaceEnvelope<{ task: TaskData; session: WorkspaceSessionData }>>(`/api/v2/tasks/${encodeURIComponent(taskId)}/enter`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, ifMatch, intent, body: '{}' })
  setWorkspaceToken(result.payload.data.session.workspace_token)
  return result
}

export async function renewWorkspaceSession(sessionId: string, token?: string, intent = new RequestIntent()): Promise<ApiResult<WorkspaceEnvelope<WorkspaceSessionData>>> {
  const result = await apiRequestWithMetadata<WorkspaceEnvelope<WorkspaceSessionData>>(`/api/v2/workspace-sessions/${encodeURIComponent(sessionId)}/renew`, { method: 'POST', body: '{}', headers: { 'Content-Type': 'application/json' }, workspaceToken: token, intent })
  setWorkspaceToken(result.payload.data.workspace_token)
  return result
}

export async function revokeWorkspaceSession(sessionId: string, ifMatch: string, token?: string, intent = new RequestIntent()): Promise<ApiResult<WorkspaceEnvelope<WorkspaceSessionData>>> {
  const result = await apiRequestWithMetadata<WorkspaceEnvelope<WorkspaceSessionData>>(`/api/v2/workspace-sessions/${encodeURIComponent(sessionId)}/revoke`, { method: 'POST', body: '{}', headers: { 'Content-Type': 'application/json' }, ifMatch, workspaceToken: token, intent })
  clearWorkspaceToken()
  return result
}

export async function saveWorkspaceSnapshot(taskId: string, input: { clientSeq: number; baseVersion: number; file: Blob }, token?: string): Promise<ApiResult<WorkspaceEnvelope<{ snapshot: WorkspaceSnapshotData; confirmed_seq: number; result: string }>>> {
  const body = new FormData()
  body.set('client_seq', String(input.clientSeq))
  body.set('base_version', String(input.baseVersion))
  body.set('snapshot', input.file, 'workspace-snapshot.bin')
  return apiRequestWithMetadata<WorkspaceEnvelope<{ snapshot: WorkspaceSnapshotData; confirmed_seq: number; result: string }>>(`/api/v2/tasks/${encodeURIComponent(taskId)}/workspace-snapshot`, { method: 'PUT', body, workspaceToken: token })
}

export function getWorkspaceCheckpoints(taskId: string): Promise<ApiResult<WorkspaceEnvelope<WorkspaceCheckpointListData>>> {
  return apiRequestWithMetadata<WorkspaceEnvelope<WorkspaceCheckpointListData>>(`/api/v2/tasks/${encodeURIComponent(taskId)}/checkpoints`)
}

export function createWorkspaceCheckpoint(taskId: string, name: string, token?: string, intent = new RequestIntent()): Promise<ApiResult<WorkspaceEnvelope<WorkspaceCheckpointData>>> {
  return apiRequestWithMetadata<WorkspaceEnvelope<WorkspaceCheckpointData>>(`/api/v2/tasks/${encodeURIComponent(taskId)}/checkpoints`, { method: 'POST', body: JSON.stringify({ name }), headers: { 'Content-Type': 'application/json' }, workspaceToken: token, intent })
}

export function restoreWorkspaceCheckpoint(taskId: string, checkpointId: string, rowVersion: number, token?: string, intent = new RequestIntent()): Promise<ApiResult<WorkspaceEnvelope<WorkspaceSnapshotData>>> {
  return apiRequestWithMetadata<WorkspaceEnvelope<WorkspaceSnapshotData>>(`/api/v2/tasks/${encodeURIComponent(taskId)}/checkpoints/${encodeURIComponent(checkpointId)}/restore`, { method: 'POST', body: '{}', headers: { 'Content-Type': 'application/json' }, ifMatch: `"${rowVersion}"`, workspaceToken: token, intent })
}
