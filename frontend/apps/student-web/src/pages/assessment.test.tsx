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
} }));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

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
