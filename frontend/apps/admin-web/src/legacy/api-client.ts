import { ApiError as AuthApiError, request } from "@edu/auth-client";

export * from "../../../../packages/api-client/src/index";

export class RequestIntent {
  readonly key = crypto.randomUUID();
}

export class ApiError extends Error {
  readonly payload: { error: { message: string; trace_id?: string } };
  readonly traceId?: string;

  constructor(readonly status: number, message: string, traceId?: string) {
    super(message);
    this.name = "ApiError";
    this.traceId = traceId;
    this.payload = { error: { message, trace_id: traceId } };
  }
}

export async function apiRequestWithMetadata<T>(path: string, init: {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  headers?: HeadersInit;
  body?: BodyInit | null;
  ifMatch?: string;
  intent?: RequestIntent;
  signal?: AbortSignal;
} = {}): Promise<{ payload: T; etag?: string; traceId?: string }> {
  const apiPath = path.replace(/^\/api\/v2/, "");
  const headers = new Headers(init.headers);
  let body: unknown;
  if (typeof init.body === "string" && headers.get("Content-Type")?.includes("application/json")) {
    body = JSON.parse(init.body);
  } else {
    body = init.body;
  }

  try {
    const response = await request<T>(apiPath, {
      method: init.method,
      headers: Object.fromEntries(headers.entries()),
      body,
      ifMatch: init.ifMatch,
      idempotencyKey: init.intent?.key,
      signal: init.signal,
    });
    return { payload: response as T, etag: response.etag, traceId: String(response.meta.trace_id ?? "") };
  } catch (error) {
    if (error instanceof AuthApiError) {
      throw new ApiError(error.status, error.payload?.message ?? error.message, error.traceId);
    }
    throw error;
  }
}

export type ListEnvelope<T> = { data: T[]; meta?: Record<string, unknown> };
export type WorkspaceEnvelope<T> = { data: T; meta: Record<string, unknown> };
export type UserData = { public_id: string; display_name: string; username: string; email: string; account_status: string; row_version: number };
export type VerificationData = { public_id: string; display_name: string; status: string; reason?: string; row_version: number; user_id: string; identity_type: string; organization_name?: string | null; identity_number_masked: string };
export type QualificationData = { public_id: string; display_name: string; status: string; reason?: string; row_version: number };
export type AdminAssignmentData = { public_id: string; display_name: string; status: string; granted_at: string; row_version: number };
export type CourseListResponse = { data: Array<{ public_id: string; title: string; code: string; owner_name: string; status: string }> };
export type ImageData = any;
export type ImageListResponse = any;
export type PolicyData = any;
export type PolicyListResponse = any;
export type QuotaData = any;
export type QuotaListResponse = any;
export type ResourceProfileData = any;
export type ResourceProfileListResponse = any;
export type RuntimeAdapterData = any;
export type RuntimeAdapterListResponse = any;
export type UsageResponse = any;
export type AlertListResponse = { data: Array<{ code: string; resource_ref: string; severity: string; message: string }> };
export type PublicationData = any;
export type TaskData = any;
export type CompensationData = { public_id: string; task_type: string; subject_type: string; subject_ref: string; status: string; attempt_count: number; max_attempts: number; error_code: string; trace_id: string; row_version: number };
export type CompensationListResponse = { data: CompensationData[] };
export type InstanceData = { public_id: string; external_id: string; task_id: string | null; course_id: string | null; status: string; external_status: string; orphan: boolean; resource_leak: boolean; row_version: number };
export type InstanceListResponse = { data: InstanceData[] };
export type WorkspaceSessionData = any;
export type PlatformPrecheckSummaryResponse = any;
export type AllowlistData = any;
export type AllowlistListResponse = any;
