import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
// Vitest must bypass a generated sibling index.js in this checkout; production imports use the package entrypoint.
// @ts-expect-error Vitest resolves the TypeScript source directly.
import { agentApi, meApi, oidcApi, reportApi, studentApi, taskApi, timetableApi } from "./index.ts";

const envelope = (data: unknown) => ({ data, meta: { trace_id: "trace-1" } });

describe("student API contracts", () => {
  beforeEach(() => {
    document.cookie = "csrftoken=student-contract; Path=/";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/auth/csrf")) {
        return new Response(JSON.stringify(envelope({ csrf: "ok" })), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.includes("/auth/oidc/campus/start")) {
        return new Response(JSON.stringify(envelope({ authorization_url: "https://issuer/authorize", state: "s" })), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.includes("/auth/oidc/campus/callback")) {
        return new Response(JSON.stringify(envelope({ public_id: "identity-1" })), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.includes("/notifications/notice-1/read")) {
        return new Response(JSON.stringify(envelope({ public_id: "notice-1", row_version: 2 })), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.includes("/me/timetable-imports") && init?.method === "POST") {
        return new Response(JSON.stringify(envelope({ public_id: "job-1", status: "MAPPING_REQUIRED", row_errors: [] })), { status: 201, headers: { "Content-Type": "application/json" } });
      }
      return new Response(JSON.stringify(envelope([])), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
  });

  afterEach(() => { document.cookie = "csrftoken=; Max-Age=0; Path=/"; vi.unstubAllGlobals(); });

  it("uses the course calendar resource and maps backend date fields", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify(envelope([{ starts_at: "2026-11-01T00:00:00Z", ends_at: null, title: "实验" }])), { status: 200, headers: { "Content-Type": "application/json" } }));
    const result = await studentApi.courseCalendarEvents("course-1");
    expect(result.rows[0]).toMatchObject({ start_at: "2026-11-01T00:00:00Z", end_at: null });
    expect(String(vi.mocked(fetch).mock.calls[0]?.[0])).toContain("/courses/course-1/calendar");
  });

  it("sends notification version and idempotency headers", async () => {
    await meApi.markNotificationRead("notice-1", 1, "read-once");
    const init = vi.mocked(fetch).mock.calls.at(-1)?.[1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("If-Match")).toBe('"1"');
    expect(headers.get("Idempotency-Key")).toBe("read-once");
  });

  it("keeps the uploaded workbook as multipart FormData", async () => {
    const workbook = new File(["xlsx-bytes"], "schedule.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
    await timetableApi.upload(workbook, "term-1");
    const init = vi.mocked(fetch).mock.calls.at(-1)?.[1] as RequestInit;
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBe(workbook);
    expect((init.body as FormData).get("term_id")).toBe("term-1");
    expect(new Headers(init.headers).get("Content-Type")).toBeNull();
  });

  it("supports OIDC start and callback wrappers", async () => {
    const start = await oidcApi.start("campus");
    expect(start.authorization_url).toContain("/authorize");
    await oidcApi.callback("campus", { state: "s", nonce: "n", iss: "https://issuer", subject: "sub" });
    expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).toContain("subject=sub");
  });

  it("sends enrollment commands with latest version and distinct command bodies", async () => {
    await studentApi.dropCheck("enrollment-1");
    expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).toContain("/me/enrollments/enrollment-1/drop-check");
    await studentApi.dropEnrollment("enrollment-1", { reason: "选课调整" }, 9, "drop-once");
    const [url, init] = vi.mocked(fetch).mock.calls.at(-1)!;
    expect(String(url)).toContain("/me/enrollments/enrollment-1/drop");
    expect(JSON.parse(String(init?.body))).toEqual({ reason: "选课调整" });
    expect(new Headers(init?.headers).get("If-Match")).toBe('"9"');
    expect(new Headers(init?.headers).get("Idempotency-Key")).toBe("drop-once");
    await studentApi.withdrawEnrollment("enrollment-1", 3, "withdraw-once");
    expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).toContain("/withdraw");
    expect(new Headers(vi.mocked(fetch).mock.calls.at(-1)?.[1]?.headers).get("If-Match")).toBe('"3"');
  });

  it("uploads mappings with PUT and confirms through the separate POST route", async () => {
    await timetableApi.updateMapping("job-1", { course_title: "课程名" });
    expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).toContain("/me/timetable-imports/job-1/mapping");
    expect(vi.mocked(fetch).mock.calls.at(-1)?.[1]?.method).toBe("PUT");
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls.at(-1)?.[1]?.body))).toEqual({ mapping: { course_title: "课程名" } });
    await timetableApi.confirm("job-1");
    expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).toContain("/me/timetable-imports/job-1/confirm");
    expect(vi.mocked(fetch).mock.calls.at(-1)?.[1]?.method).toBe("POST");
  });

  it("stops a runtime with the task version required by the backend", async () => {
    await taskApi.stopRuntime("runtime-1", 12, "stop-once");
    expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).toContain("/student/task-runtimes/runtime-1/stop");
    const headers = new Headers(vi.mocked(fetch).mock.calls.at(-1)?.[1]?.headers);
    expect(headers.get("If-Match")).toBe('"12"');
    expect(headers.get("Idempotency-Key")).toBe("stop-once");
  });

  it("uses course/task Agent scope and preserves asynchronous message acknowledgements", async () => {
    await agentApi.createTaskSession("task-1", "REPORT_COACH", "session-once");
    expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).toContain("/tasks/task-1/agent-sessions");
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls.at(-1)?.[1]?.body))).toEqual({ mode: "REPORT_COACH" });
    await agentApi.createCourseSession("course-1", "KNOWLEDGE_QA", "course-session");
    expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).toContain("/courses/course-1/agent-sessions");
    const acknowledged = { public_id: "message-1", role: "USER", status: "COMPLETE", body: "问题" };
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify(envelope(acknowledged)), { status: 202 }));
    expect(await agentApi.sendMessage("session-1", "问题", "message-once")).toEqual(acknowledged);
    expect(new Headers(vi.mocked(fetch).mock.calls.at(-1)?.[1]?.headers).get("Idempotency-Key")).toBe("message-once");
    await agentApi.decideToolCall("tool-1", { decision: "REJECTED" }, 7, "tool-once");
    expect(new Headers(vi.mocked(fetch).mock.calls.at(-1)?.[1]?.headers).get("If-Match")).toBe('"7"');
    expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).toContain("/agent-tool-calls/tool-1/decide");
  });

  it("normalizes decimal review scores and preserves permission to revise a returned report", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify(envelope({ task_id: "task-1", task_status: "REPORT_DRAFT", allowed_actions: ["REVISE_AND_RESUBMIT"], rounds: [
      { review_id: "review-1", round_no: 1, status: "DECIDED", scores: { criteria: [{ public_id: "c-1", title: "实现", score: "42.50", max_score: "50.00" }] }, annotations: [], decision: { decision: "REJECT", score: "42.50", feedback: "请修改" } },
    ] })), { status: 200 }));
    const result = await reportApi.reviewResult("task-1");
    expect(result.score).toBe(42.5);
    expect(result.rounds[0]?.scores?.criteria[0]).toMatchObject({ score: 42.5, max_score: 50 });
    expect(result.allowed_actions).toContain("REVISE_AND_RESUBMIT");
  });
});
