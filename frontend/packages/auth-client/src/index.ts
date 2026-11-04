/**
 * 门户请求层（对接 docs/frontend/frontend-backend-integration-guide.md）：
 * - Django session/cookie 认证：credentials: "include"，不用 Bearer。
 * - CSRF：首次写请求前调用 GET /auth/csrf 设置 csrftoken cookie，请求自动携带 X-CSRFToken；CSRF_FAILED 重试一次。
 * - 幂等：需要幂等的命令必须带 Idempotency-Key；同一业务命令重试复用同一 key；IN_PROGRESS 延迟重试。
 * - 乐观锁：If-Match "<row_version>"；412 视为 ROW_VERSION_CONFLICT，调用方负责合并，不覆盖本地编辑。
 * - 错误归一：任何非 2xx 解析 { error: {...} }；错误码决定会话失效 / 权限 / 重试语义。
 * - 诊断：自动生成 X-Request-ID；保留 error.trace_id 与响应 meta.trace_id。
 */

export const API_PREFIX = "/api/v2";

export interface ApiErrorPayload {
  code: string;
  message: string;
  detail?: unknown;
  trace_id?: string;
  retryable?: boolean;
}

export class ApiError extends Error {
  readonly status: number;
  readonly url: string;
  readonly method: string;
  readonly traceId?: string;
  readonly requestId?: string;
  readonly payload?: ApiErrorPayload;
  readonly kind: ApiErrorKind;

  constructor(init: {
    status: number; url: string; method: string; requestId?: string;
    payload?: ApiErrorPayload; kind: ApiErrorKind;
  }) {
    super(init.payload?.message || `请求失败（${init.status}）`);
    this.name = "ApiError";
    this.status = init.status;
    this.url = init.url;
    this.method = init.method;
    this.requestId = init.requestId;
    this.payload = init.payload;
    this.kind = init.kind;
    this.traceId = init.payload?.trace_id;
  }
}

export type ApiErrorKind =
  | "auth"            // 需要重新登录
  | "forbidden"       // 无权限/资格
  | "conflict"        // ROW_VERSION_CONFLICT（乐观锁）
  | "state-conflict"  // 409 状态机冲突
  | "validation"
  | "rate-limited"
  | "unavailable"
  | "not-found"
  | "server"
  | "network"
  | "unknown";

const AUTH_ERROR_CODES = new Set(["AUTH_REQUIRED", "SESSION_EXPIRED", "SESSION_PORTAL_MISMATCH"]);
const FORBIDDEN_CODES = new Set([
  "PORTAL_ACCESS_DENIED", "TEACHER_QUALIFICATION_REQUIRED", "PLATFORM_ACCESS_REQUIRED",
  "PERMISSION_DENIED", "FORBIDDEN",
]);

function classify(status: number, code?: string): ApiErrorKind {
  if (code && AUTH_ERROR_CODES.has(code)) return "auth";
  if (code && FORBIDDEN_CODES.has(code)) return "forbidden";
  if (code === "ROW_VERSION_CONFLICT" || status === 412) return "conflict";
  if (code === "CSRF_FAILED") return "validation";
  if (status === 400 || status === 422) return "validation";
  if (status === 404) return "not-found";
  if (status === 409) return "state-conflict";
  if (status === 429) return "rate-limited";
  if (status >= 500) return "unavailable";
  if (status === 428) return "validation";
  return "unknown";
}

/* ── CSRF ── */

export function readCsrfToken(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match?.[1] ? decodeURIComponent(match[1]) : null;
}

export async function ensureCsrf(): Promise<void> {
  if (readCsrfToken()) return;
  const response = await fetch(`${API_PREFIX}/auth/csrf`, {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiError({
      status: response.status, url: `${API_PREFIX}/auth/csrf`, method: "GET",
      kind: classify(response.status, await readErrorCode(response)),
    });
  }
}

async function readErrorCode(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.clone().json()) as { error?: ApiErrorPayload };
    return body?.error?.code;
  } catch {
    return undefined;
  }
}

/* ── 请求封装 ── */

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  /** 是否需要幂等键（大多数 POST 与指定 PUT）；复用 key via reuseKey */
  idempotent?: boolean;
  /** 幂等键：同一业务命令网络重试时必须复用 */
  idempotencyKey?: string;
  /** 乐观锁 If-Match，值为 row_version（后端要求 ETag 引号形式，请求层自动补引号） */
  ifMatch?: string | number | null;
  query?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
  accept?: string;
  /** 额外请求头（工作区链路需要 X-Workspace-Token），不要用它覆盖认证头 */
  headers?: Record<string, string>;
  /** 覆盖默认的 /api/v2 前缀（工作区网关挂在站点根 /workspace 下时传 ""） */
  prefix?: string;
}

const IDEMPOTENCY_RETRY_WAIT_MS = 800;
const IDEMPOTENCY_MAX_RETRIES = 3;

export interface EnvelopeSuccess<T> {
  data: T;
  meta: Partial<{ page: number; page_size: number; total: number; trace_id: string }> & Record<string, unknown>;
  etag?: string;
}

function absoluteUrl(path: string, query?: RequestOptions["query"], prefix: string = API_PREFIX): string {
  const params = new URLSearchParams();
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value == null) continue;
      params.set(key, String(value));
    }
  }
  const suffix = params.toString();
  return `${prefix}${path}${suffix ? `?${suffix}` : ""}`;
}

async function parseResponse<T>(response: Response, url: string, method: string): Promise<EnvelopeSuccess<T>> {
  const requestId = response.headers.get("X-Request-ID") ?? undefined;
  if (!response.ok) {
    let payload: ApiErrorPayload | undefined;
    try {
      const body = (await response.json()) as { error?: ApiErrorPayload };
      payload = body?.error;
    } catch {
      payload = undefined;
    }
    throw new ApiError({
      status: response.status, url, method, requestId,
      payload: payload ?? { code: `HTTP_${response.status}`, message: "服务暂时无法处理请求" },
      kind: classify(response.status, payload?.code),
    });
  }
  if (response.status === 204) {
    return { data: null as T, meta: {} };
  }
  const body = (await response.json()) as { data?: T; meta?: EnvelopeSuccess<T>["meta"]; error?: ApiErrorPayload };
  if (body?.error && body.data == null) {
    throw new ApiError({
      status: response.status, url, method, requestId,
      payload: body.error, kind: classify(403, body.error.code),
    });
  }
  return {
    data: (body?.data ?? null) as T,
    meta: (body?.meta ?? {}) as EnvelopeSuccess<T>["meta"],
    etag: response.headers.get("ETag") ?? undefined,
  };
}

export interface RequestHooks {
  /** 收到会话失效时清缓存并回登录，由 app 注入 */
  onAuthExpired?: (error: ApiError) => void;
  /** 诊断上报：仅记录 URL/method/status/code/trace，不含敏感内容 */
  onErrorReport?: (error: ApiError) => void;
}

let hooks: RequestHooks = {};

export function configureRequestHooks(next: RequestHooks): void {
  hooks = next;
}

function newRequestKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `req-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<EnvelopeSuccess<T>> {
  const method = options.method ?? "GET";
  const url = absoluteUrl(path, options.query, options.prefix);
  const isMutation = method !== "GET";
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const headers: Record<string, string> = {
    Accept: options.accept ?? "application/json",
    ...(options.headers ?? {}),
  };

  if (options.body != null) {
    for (const name of Object.keys(headers)) {
      if (name.toLowerCase() === "content-type") delete headers[name];
    }
    // FormData 的 multipart boundary 由浏览器设置。
    if (!isFormData) headers["Content-Type"] = "application/json";
  }
  if (isMutation) {
    // 请求层统一补充 CSRF；相对路径由同源代理/网关决定门户
    await ensureCsrf();
    const token = readCsrfToken();
    if (token) headers["X-CSRFToken"] = token;
    headers["X-Request-ID"] = newRequestKey();
    if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;
    if (options.ifMatch != null && options.ifMatch !== "") {
      const etagValue = String(options.ifMatch);
      headers["If-Match"] = etagValue.startsWith('"') && etagValue.endsWith('"')
        ? etagValue
        : `"${etagValue}"`;
    }
  }

  const attempt = async (retryCount: number): Promise<EnvelopeSuccess<T>> => {
    let response: Response;
    try {
      response = await fetch(url, {
        method,
        credentials: "include",
        headers,
        body: isFormData ? options.body as FormData : options.body != null ? JSON.stringify(options.body) : undefined,
        signal: options.signal,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      const networkError = new ApiError({
        status: 0, url, method, kind: "network",
        payload: { code: "NETWORK_ERROR", message: "网络连接失败，请检查网络后重试。", retryable: true },
      });
      hooks.onErrorReport?.(networkError);
      throw networkError;
    }

    try {
      return await parseResponse<T>(response, url, method);
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;

      // CSRF 失败：重取 csrf cookie 后重试一次
      if (error.payload?.code === "CSRF_FAILED" && retryCount === 0) {
        document.cookie = "csrftoken=; Max-Age=0; Path=/";
        await ensureCsrf();
        const token = readCsrfToken();
        if (token) headers["X-CSRFToken"] = token;
        return attempt(retryCount + 1);
      }

      // 幂等命令仍在执行：用同一个 key 延迟重试
      if (error.payload?.code === "IDEMPOTENCY_REQUEST_IN_PROGRESS" && retryCount < IDEMPOTENCY_MAX_RETRIES) {
        await new Promise((resolve) => setTimeout(resolve, IDEMPOTENCY_RETRY_WAIT_MS * (retryCount + 1)));
        return attempt(retryCount + 1);
      }

      if (error.kind === "auth") {
        hooks.onAuthExpired?.(error);
      }
      hooks.onErrorReport?.(error);
      throw error;
    }
  };

  return attempt(0);
}

export function newIdempotencyKey(): string {
  return newRequestKey();
}

/* ── 认证流程 ── */

export interface MeDataRaw {
  public_id: string;
  email: string;
  username: string;
  display_name: string;
  account_status: string;
  row_version: string;
  portal: "USER" | "TEACHING" | "PLATFORM";
  eligible_portals: string[];
  teacher_qualification?: unknown;
  platform_admin_assignment?: unknown;
  permissions: string[];
  course_scopes?: unknown[];
}

export const authFlow = {
  /** 登录前初始化 CSRF cookie */
  initCsrf: async (): Promise<void> => {
    await ensureCsrf();
  },
  login: async (identifier: string, password: string): Promise<EnvelopeSuccess<MeDataRaw>> => {
    const response = await request<MeDataRaw>("/auth/login", {
      method: "POST",
      body: { identifier, password },
    });
    return response;
  },
  logout: async (all = false): Promise<void> => {
    await request(`/auth/logout${all ? "-all" : ""}`, { method: "POST" });
  },
  me: async (): Promise<EnvelopeSuccess<MeDataRaw>> => {
    const response = await request<MeDataRaw>("/me", { method: "GET" });
    return response;
  },
};

export function isEnvelope<T>(value: unknown): value is EnvelopeSuccess<T> {
  return typeof value === "object" && value !== null && "data" in value;
}
