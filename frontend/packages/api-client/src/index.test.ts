// @ts-expect-error Test the TypeScript source even when a stale emitted index.js exists.
import { reportApi, taskApi, teachingApi } from "./index.ts";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

function jsonResponse(status: number, body: unknown, headers?: Record<string, string>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

const okEnvelope = { data: {}, meta: { trace_id: "t1" } };

/**
 * 契约对齐测试（对应 docs/frontend/frontend-backend-integration-guide.md）：
 * - row_version 实测为数字，前端需转字符串展示
 * - allowed_actions 实测为大写（ENTER / REQUEST_EXTENSION），前端统一小写
 * - current_failure 为对象（可以为空对象），非数组
 */
describe("task 数据边界规范化", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, {
      ...okEnvelope,
      data: {
        public_id: "01M5EES0WBQ53F1CRNPQQ1MS1X",
        title: "Linux 网络故障排查",
        course_id: "course-1",
        publication_id: "pub-1",
        status: "READY",
        progress: 0,
        row_version: 3,
        allowed_actions: ["ENTER", "REQUEST_EXTENSION"],
        blockers: [],
        current_failure: {},
      },
    })));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("detail 返回的 row_version 转字符串、动作转小写", async () => {
    const task = await taskApi.detail("01M5EES0WBQ53F1CRNPQQ1MS1X");
    expect(task.row_version).toBe("3");
    expect(task.allowed_actions).toEqual(["enter", "request_extension"]);
    expect(task.blockers).toEqual([]);
    expect(task.status).toBe("READY");
  });

  it("AI suggestions paginate to the selected review and adoption sends its version", async () => {
    document.cookie = "csrftoken=ai-csrf; Path=/";
    const fetchMock = vi.fn(async (_input: string | URL, _init?: RequestInit) => jsonResponse(200, okEnvelope))
      .mockResolvedValueOnce(jsonResponse(200, { data: { suggestions: [], total: 101 } }))
      .mockResolvedValueOnce(jsonResponse(200, { data: { suggestions: [
        { public_id: "suggestion", review_id: "review", review_row_version: 7, status: "READY" },
      ], total: 101 } }));
    vi.stubGlobal("fetch", fetchMock);
    expect((await teachingApi.aiScoreSuggestion("course", "batch", "review"))?.public_id).toBe("suggestion");
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("page=2");
    await teachingApi.acceptAIScoreSuggestion("course", "review", "suggestion", "7");
    const init = fetchMock.mock.calls[2]?.[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("If-Match")).toBe('"7"');
    expect(new Headers(init.headers).get("Idempotency-Key")).toBeTruthy();
  });

  it("字段缺失时不抛错（空数组保底）", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, { ...okEnvelope, data: { public_id: "t2" } })));
    const task = await taskApi.detail("t2");
    expect(task.allowed_actions).toEqual([]);
    expect(task.blockers).toEqual([]);
  });

  it("rows_class 列表响应也做同样的规范化", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, {
      data: [{ public_id: "t-x", status: "ASSIGNED", row_version: 9, allowed_actions: ["START"] }],
      meta: { page: 1, page_size: 20, total: 1, trace_id: "t1" },
    })));
    const list = await taskApi.list({});
    expect(list.rows[0]?.row_version).toBe("9");
    expect(list.rows[0]?.allowed_actions).toEqual(["start"]);
  });

  it("从最新已决策评审轮次读取成绩，保留零分", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, {
      ...okEnvelope,
      data: { task_id: "t-1", rounds: [
        { round_no: 2, decision: null },
        { round_no: 1, decision: { decision: "REJECT", score: 0 } },
      ] },
    })));
    expect((await reportApi.reviewResult("t-1")).score).toBe(0);
  });
});
