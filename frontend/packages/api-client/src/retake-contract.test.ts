import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
// @ts-expect-error Vitest resolves this package source directly.
import { teachingApi } from "./index.ts";

describe("retake API contract", () => {
  beforeEach(() => {
    document.cookie = "csrftoken=retake-contract; Path=/";
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      data: { public_id: "retake-1", status: "PUBLISHED", retake_of_publication_id: "pub-1" },
      meta: { trace_id: "trace-1" },
    }), { status: 201, headers: { "Content-Type": "application/json" } })));
  });

  afterEach(() => vi.unstubAllGlobals());

  it("posts selected enrollment IDs and reuses the supplied idempotency key", async () => {
    const payload = {
      selected_enrollment_ids: ["enrollment-1", "enrollment-2"],
      window_start: "2026-11-07T09:00:00.000Z",
      window_end: "2026-11-08T09:00:00.000Z",
    };
    const response = await teachingApi.createRetakePublication(
      "course-1", "pub-1", payload, "retake-retry-key",
    );
    expect(response.retake_of_publication_id).toBe("pub-1");
    const [url, init] = vi.mocked(fetch).mock.calls[0]!;
    expect(String(url)).toContain(
      "/teaching/courses/course-1/experiments/pub-1/retakes",
    );
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual(payload);
    expect(new Headers(init?.headers).get("Idempotency-Key")).toBe("retake-retry-key");
  });
});
