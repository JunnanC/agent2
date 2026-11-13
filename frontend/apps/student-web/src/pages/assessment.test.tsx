import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { assessmentApi } from "@edu/api-client";
import { ToastProvider } from "@edu/ui";
import { AssessmentWorkbench } from "./assessment";

vi.mock("@edu/api-client", () => ({ assessmentApi: {
  get: vi.fn(async () => ({
    task_id: "task", questions: [{ id: "q", title: "栈", description: "访问顺序", instructions: "", task_type: "SINGLE_CHOICE", max_score: "5", options: [{ id: "a", text: "先进先出" }, { id: "b", text: "后进先出" }] }],
    sections: [{ kind: "CHOICE", status: "NOT_SUBMITTED", grading_status: "NOT_SUBMITTED", score: null, deadline: "2099-01-01T00:00:00Z" }],
    server_time: new Date().toISOString(), all_submitted: false, choice_answers_visible: false,
  })),
  choiceDraft: vi.fn(async () => ({ selected_option_ids: [], row_version: 1 })),
  history: vi.fn(async () => []),
  saveChoice: vi.fn(async () => ({ selected_option_ids: ["b"], row_version: 2 })),
  submitChoices: vi.fn(async () => ({ version_no: 1 })),
  codeDraft: vi.fn(async () => ({ files: {}, row_version: 1, language: "python" })),
  saveCode: vi.fn(async () => ({ files: {}, row_version: 1, language: "python" })),
  reportDraft: vi.fn(async () => ({ body_markdown: "", row_version: 1, attachments: [] })),
  saveReport: vi.fn(async () => ({ body_markdown: "", row_version: 1 })),
  submitProgramming: vi.fn(async () => ({ version_no: 1 })),
  run: vi.fn(),
  runResult: vi.fn(),
} }));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("shows the submitted answer sheet and per-question score after the deadline", async () => {
  vi.mocked(assessmentApi.get).mockResolvedValueOnce({
    task_id: "task",
    questions: [{
      id: "q", title: "栈", description: "访问顺序", instructions: "", task_type: "SINGLE_CHOICE",
      max_score: "5", options: [{ id: "a", text: "先进先出" }, { id: "b", text: "后进先出" }],
      correct_option_ids: ["b"], explanation: "",
    }],
    sections: [{
      kind: "CHOICE", status: "SUBMITTED", grading_status: "COMPLETED", score: "5",
      max_score: "5", deadline: "2020-01-01T00:00:00Z", editable: false, submission_version: 1,
      questions: [{ id: "q", score: "5", max_score: "5", language: "" }],
    }],
    server_time: new Date().toISOString(), all_submitted: true, choice_answers_visible: true,
  } as never);
  vi.mocked(assessmentApi.history).mockResolvedValueOnce([{
    kind: "CHOICE", version_no: 1, submitted_at: "2026-01-01T00:00:00Z", is_current: true,
    answers: [{ question_id: "q", selected_option_ids: ["b"], language: "", snapshot_digest: null }],
    report: null,
  }]);

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/experiments/task/assessment"]}>
    <Routes><Route path="/experiments/:taskId/assessment" element={<AssessmentWorkbench />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);

  await waitFor(() => expect(screen.getByRole("radio", { name: "后进先出" })).toBeChecked());
  expect(screen.getByRole("radio", { name: "先进先出" })).not.toBeChecked();
  expect(screen.getByText("本题得分：5 / 5 · 正确")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "查看答卷" }));
  expect(await screen.findByText("第 1 次提交答卷")).toBeTruthy();
  client.clear();
});

it("saves answers and flushes before submitting only the choice section", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/experiments/task/assessment"]}>
    <Routes><Route path="/experiments/:taskId/assessment" element={<AssessmentWorkbench />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("radio", { name: "后进先出" }));
  await waitFor(() => expect(assessmentApi.saveChoice).toHaveBeenCalledWith("task", "q", ["b"], 1));
  expect(screen.queryByText(/正确选项/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "提交选择题卷" }));
  fireEvent.click(await screen.findByRole("button", { name: "确认交卷" }));
  await waitFor(() => expect(assessmentApi.submitChoices).toHaveBeenCalled());
  expect(assessmentApi.submitChoices).toHaveBeenCalledWith("task", { q: 1 }, expect.any(String));
  client.clear();
});

it("downloads the current submitted report version, not the editable draft", async () => {
  vi.mocked(assessmentApi.get).mockResolvedValueOnce({
    task_id: "task",
    questions: [{
      id: "p", title: "编程", description: "", instructions: "", task_type: "PROGRAMMING",
      max_score: "10", allowed_languages: ["python"], selected_language: "python",
      samples: [], starter_files: {}, limits: {},
    }],
    sections: [{
      kind: "PROGRAMMING", status: "SUBMITTED", grading_status: "COMPLETED", score: "10",
      deadline: "2020-01-01T00:00:00Z", submission_version: 1, editable: false,
    }],
    server_time: new Date().toISOString(), all_submitted: true, choice_answers_visible: false,
  } as never);
  vi.mocked(assessmentApi.history).mockResolvedValueOnce([{
    kind: "PROGRAMMING", version_no: 2, submitted_at: "2026-01-01T00:00:00Z",
    is_current: true, report: "# 已提交报告", answers: [],
  }]);
  const blobs: Blob[] = [];
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true, value: vi.fn((blob: Blob) => { blobs.push(blob); return "blob:report"; }),
  });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/experiments/task/assessment"]}>
    <Routes><Route path="/experiments/:taskId/assessment" element={<AssessmentWorkbench />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);

  fireEvent.click(await screen.findByRole("button", { name: "下载已提交报告" }));
  await waitFor(() => expect(blobs).toHaveLength(1));
  const text = await new Promise<string>((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(blobs[0]!);
  });
  expect(text).toContain("- 提交版本：第 2 次");
  expect(text).toContain("- 提交时间：");
  expect(text).toContain("- 本部分得分：");
  expect(text).toContain("# 已提交报告");
  expect(click).toHaveBeenCalled();
  click.mockRestore();
  client.clear();
});
