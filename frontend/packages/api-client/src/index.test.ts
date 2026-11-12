// @ts-expect-error Test the TypeScript source even when a stale emitted index.js exists.
import { taskApi } from "./index.ts";
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


});
