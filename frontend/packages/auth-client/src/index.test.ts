import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
// @ts-expect-error Exercise the source rather than a stale emitted sibling index.js.
import { ApiError, newIdempotencyKey, request } from "./index.ts";

function jsonResponse(status: number, body: unknown, headers?: Record<string, string>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

const okEnvelope = { data: {}, meta: { trace_id: "t1" } };

describe("auth-client request", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      const headers = Object.fromEntries(
        Object.entries((init?.headers as Record<string, string>) ?? {}),
      );
      if (url.endsWith("/auth/csrf")) {
        return new Response(JSON.stringify({ data: { csrf: "ready" } }), {
          status: 200, headers: { "Set-Cookie": "csrftoken=abc", "Content-Type": "application/json" },
        });
      }
      if (url.endsWith("/conflict")) {
        return jsonResponse(412, { error: { code: "ROW_VERSION_CONFLICT", message: "版本冲突", trace_id: "x" } });
      }
      if (url.endsWith("/in-progress")) {
        const count = (headers["X-Retry-Count"] ?? "0");
        if (Number(count) === 0) {
          return jsonResponse(409, { error: { code: "IDEMPOTENCY_REQUEST_IN_PROGRESS", message: "处理中" } });
        }
        return jsonResponse(200, { ...okEnvelope, data: { id: "done" } });
      }
      if (method === "POST" && !headers["Idempotency-Key"] && !url.endsWith("/auth/login")) {
        return jsonResponse(428, { error: { code: "IDEMPOTENCY_KEY_REQUIRED", message: "缺少幂等键" } });
      }
      return jsonResponse(200, { ...okEnvelope, data: { ok: true } });
    }));
  });

  afterEach(() => {
    document.cookie = "csrftoken=; Max-Age=0; Path=/";
    vi.unstubAllGlobals();
  });

  it("GET 请求不需要 CSRF 与幂等键", async () => {
    const result = await request<{ ok: boolean }>("/courses?page=1", { query: { page: 1 } });
    expect(result.data).toEqual({ ok: true });
    expect(result.etag ?? null).toBeNull();
  });

  it("normalizes Content-Type casing without duplicate JSON media types", async () => {
    await request("/tasks", {
      method: "POST", body: {}, idempotencyKey: "header-regression",
      headers: { "content-type": "application/json" },
    });
    const init = vi.mocked(fetch).mock.calls.at(-1)?.[1] as RequestInit;
    expect(new Headers(init.headers).get("content-type")).toBe("application/json");
  });

  it("POST 缺少幂等键时抛出 428 业务错误", async () => {
    await expect(request("/tasks", { method: "POST", body: { a: 1 } }))
      .rejects.toMatchObject({ payload: { code: "IDEMPOTENCY_KEY_REQUIRED" }, status: 428 });
  });

  it("retains the workbook and multipart boundary handling when retrying CSRF", async () => {
    const body = new FormData();
    body.append("file", new File(["xlsx-content"], "schedule.xlsx"));
    let posts = 0;
    vi.mocked(fetch).mockImplementation(async (input) => {
      if (String(input).endsWith("/auth/csrf")) {
        document.cookie = "csrftoken=refreshed; Path=/";
        return jsonResponse(200, okEnvelope);
      }
      posts += 1;
      return posts === 1 ? jsonResponse(403, { error: { code: "CSRF_FAILED", message: "retry" } }) : jsonResponse(200, okEnvelope);
    });
    await request("/me/timetable-imports", { method: "POST", body, headers: { "Content-Type": "application/json" }, idempotencyKey: "upload-once" });
    const requests = vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "POST");
    expect(requests).toHaveLength(2);
    for (const [, init] of requests) {
      expect(init?.body).toBe(body);
      expect(new Headers(init?.headers).get("Content-Type")).toBeNull();
      expect(new Headers(init?.headers).get("Idempotency-Key")).toBe("upload-once");
    }
  });

  it("412 归一为冲突类型", async () => {
    const error = await request("/conflict", { method: "PUT", body: 1, idempotencyKey: newIdempotencyKey() })
      .catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).kind).toBe("conflict");
  });

  it("If-Match 与幂等键都进入请求头", async () => {
    await request("/tasks", {
      method: "PUT", body: { x: 1 },
      idempotencyKey: "key-1", ifMatch: '"2"',
    });
    const init = vi.mocked(fetch).mock.calls.at(-1)?.[1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers["If-Match"]).toBe('"2"');
    expect(headers["Idempotency-Key"]).toBe("key-1");
    expect(headers["X-CSRFToken"]).toBeUndefined(); // 测试环境未写 cookie（HttpOnly 语义）
  });
});
