// @ts-expect-error Test the TypeScript source even when a stale emitted index.js exists.
import { reportApi, taskApi, workspaceApi } from "./index.ts";
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

  it("checkpoints 的 { items: [...] } 包装返回也能转成列表", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, {
      data: { items: [{ public_id: "cp-1", task_id: "t-1" }], current_version: 0, row_version: 1 },
      meta: { trace_id: "t1" },
    })));
    const list = await workspaceApi.checkpoints("t-1", "tok");
    expect(list.rows).toHaveLength(1);
    expect(list.currentVersion).toBe(0);
    expect(list.sessionRowVersion).toBe(1);
  });

  it("工作区运行请求会携带 X-Workspace-Token 头", async () => {
    const fetchMock = vi.fn(async (input: string | URL, init?: RequestInit) => {
      void input;
      void init;
      return jsonResponse(200, { ...okEnvelope, data: { public_id: "r-1", status: "PASSED" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    await workspaceApi.createExecutionRun("t-1", {}, "ws-token");
    const postCall = fetchMock.mock.calls.find(([, init]) => (init as RequestInit)?.method === "POST");
    expect(postCall).toBeTruthy();
    const headers = new Headers((postCall as [string | URL, RequestInit])[1].headers as HeadersInit);
    expect(headers.get("X-Workspace-Token")).toBe("ws-token");
    expect(headers.get("Idempotency-Key")).toBeTruthy();
  });

  it("等待快照任务完成，并携带会话版本与工作区令牌", async () => {
    vi.useFakeTimers();
    let reads = 0;
    const fetchMock = vi.fn(async (input: string | URL, init?: RequestInit) => {
      const url = String(input);
      const data = url.endsWith("/checkpoints")
        ? { items: [], current_version: 2, row_version: 7 }
        : init?.method === "POST"
          ? { public_id: "capture-1", status: "QUEUED", result_snapshot_id: null }
          : { public_id: "capture-1", status: ++reads === 1 ? "RUNNING" : "PASSED", result_snapshot_id: reads === 1 ? null : "snapshot-3" };
      return jsonResponse(200, { ...okEnvelope, data });
    });
    vi.stubGlobal("fetch", fetchMock);
    const capturing = workspaceApi.captureSnapshot("t-1", "token");
    await vi.runAllTimersAsync();
    expect((await capturing).result_snapshot_id).toBe("snapshot-3");
    expect(reads).toBe(2);
    const [, init] = fetchMock.mock.calls.find(([, options]) => options?.method === "POST")!;
    expect(new Headers(init?.headers).get("If-Match")).toBe('"7"');
    expect(new Headers(init?.headers).get("X-Workspace-Token")).toBe("token");
    expect(JSON.parse(init?.body as string)).toMatchObject({ kind: "CAPTURE", base_version: 2 });
  });

  it("判题资源可运行时不依赖公开用例的数量", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, {
      ...okEnvelope,
      data: { task: { public_id: "t-1" }, tests: { runnable: true, summary: [] } },
    })));
    const data = await workspaceApi.workbench("t-1");
    expect(data.tests_available).toBe(true);
    expect(data.tests).toEqual([]);
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
