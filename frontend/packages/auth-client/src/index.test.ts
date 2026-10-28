import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, newIdempotencyKey, request } from "./index";

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
    vi.unstubAllGlobals();
  });

  it("GET 请求不需要 CSRF 与幂等键", async () => {
    const result = await request<{ ok: boolean }>("/courses?page=1", { query: { page: 1 } });
    expect(result.data).toEqual({ ok: true });
    expect(result.etag ?? null).toBeNull();
  });

  it("POST 缺少幂等键时抛出 428 业务错误", async () => {
    await expect(request("/tasks", { method: "POST", body: { a: 1 } }))
      .rejects.toMatchObject({ payload: { code: "IDEMPOTENCY_KEY_REQUIRED" }, status: 428 });
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
