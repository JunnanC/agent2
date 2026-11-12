import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@edu/auth-client", () => ({ request: vi.fn() }));

import { request } from "@edu/auth-client";

import { assessmentApi } from "./assessment";

describe("assessment commands", () => {
  beforeEach(() => {
    vi.mocked(request).mockReset();
    vi.mocked(request).mockResolvedValue({ data: {}, meta: {} });
  });

  it("preserves source whitespace, an empty file and the draft version", async () => {
    const files = { "main.py": "  print(1)  \n", "empty.txt": "" };
    await assessmentApi.saveCode("task", "question", "python", files, 7);
    expect(request).toHaveBeenCalledWith("/tasks/task/questions/question/code/python", {
      method: "PUT", body: { files }, ifMatch: 7,
    });
  });

  it("requires the same caller-owned key when retrying a submission", async () => {
    const versions = { first: 2, second: 5 };
    await assessmentApi.submitChoices("task", versions, "same-command");
    await assessmentApi.submitChoices("task", versions, "same-command");
    expect(vi.mocked(request).mock.calls[0]).toEqual(vi.mocked(request).mock.calls[1]);
    expect(request).toHaveBeenCalledWith("/tasks/task/sections/choice/submissions", {
      method: "POST", body: { versions }, idempotencyKey: "same-command",
    });
  });

  it("keeps different question and language drafts on distinct endpoints", async () => {
    await assessmentApi.codeDraft("task", "one", "python");
    await assessmentApi.codeDraft("task", "one", "cpp");
    await assessmentApi.codeDraft("task", "two", "python");
    const endpoints = vi.mocked(request).mock.calls.map(([endpoint]) => endpoint);
    expect(new Set(endpoints).size).toBe(3);
  });
});
