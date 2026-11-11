import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { Reviews } from "./reviews";

const api = vi.hoisted(() => ({
  reviews: vi.fn(), review: vi.fn(), aiScoreBatches: vi.fn(), aiScoreSuggestion: vi.fn(),
  startAIScoreBatch: vi.fn(), acceptAIScoreSuggestion: vi.fn(), saveCriterionScores: vi.fn(),
}));
vi.mock("@edu/api-client", () => ({ teachingApi: api }));

const summary = { public_id: "review", publication_id: "publication", student_name: "Student",
  publication_title: "Experiment", status: "PENDING", row_version: "7" };
const suggestion = { public_id: "suggestion", review_row_version: 7, status: "READY", criteria: [
  { criterion_id: "correct", score: "55", rationale: "Source supports the result", evidence: "print(42)" },
] };
let client: QueryClient;
beforeEach(() => {
  vi.resetAllMocks();
  api.reviews.mockResolvedValue({ total: 1, rows: [summary] });
  api.review.mockResolvedValue({ ...summary, rubric: { criteria: [
    { public_id: "correct", title: "Correctness", max_score: "60", score: null },
  ] }, project: { language: "python", snapshot_id: "frozen", guidance: {}, files: [
    { path: "main.py", content: "print(42)", truncated: false },
  ] } });
  api.aiScoreBatches.mockResolvedValue([{ public_id: "batch" }]);
  api.aiScoreSuggestion.mockResolvedValue(suggestion);
  api.acceptAIScoreSuggestion.mockResolvedValue({});
  api.saveCriterionScores.mockResolvedValue({});
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});
afterEach(() => { cleanup(); client.clear(); });

async function openReview() {
  render(<QueryClientProvider client={client}><ToastProvider>
    <MemoryRouter initialEntries={["/courses/course/reviews"]}><Routes>
      <Route path="/courses/:courseId/reviews" element={<Reviews />} />
    </Routes></MemoryRouter>
  </ToastProvider></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "开始评审" }));
}

it("shows frozen source and waits for explicit teacher adoption", async () => {
  await openReview();
  expect(await screen.findByText("main.py")).toBeInTheDocument();
  expect(await screen.findByText("Source supports the result")).toBeInTheDocument();
  expect(api.acceptAIScoreSuggestion).not.toHaveBeenCalled();
  expect(screen.getByRole("spinbutton")).toHaveValue(null);
  fireEvent.click(screen.getByRole("button", { name: "采纳此份建议评分" }));
  await waitFor(() => expect(api.acceptAIScoreSuggestion)
    .toHaveBeenCalledWith("course", "review", "suggestion", "7"));
});

it("disables stale advice while leaving manual scoring available", async () => {
  api.aiScoreSuggestion.mockResolvedValue({ ...suggestion, review_row_version: 6 });
  await openReview();
  expect(await screen.findByText("评审已更新，请重新生成建议。")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "采纳此份建议评分" })).toBeDisabled();
  fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "58" } });
  fireEvent.click(screen.getByRole("button", { name: "保存评分" }));
  await waitFor(() => expect(api.saveCriterionScores).toHaveBeenCalledWith(
    "course", "review", { scores: [{ criterion_id: "correct", score: 58 }] }, "7",
  ));
});

it("keeps manual scoring available after provider failure", async () => {
  api.aiScoreSuggestion.mockResolvedValue({ ...suggestion, status: "FAILED", criteria: [] });
  await openReview();
  expect(await screen.findByText("生成失败，可人工评分")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "采纳此份建议评分" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "52" } });
  expect(screen.getByRole("button", { name: "保存评分" })).toBeEnabled();
});
