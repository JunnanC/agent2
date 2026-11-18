import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { assessmentTeachingApi } from "@edu/api-client";
import { Reviews } from "./reviews";

vi.mock("@edu/api-client", () => ({ assessmentTeachingApi: {
  reviews: vi.fn(), review: vi.fn(), saveReview: vi.fn(), reportSuggestion: vi.fn(),
} }));
afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(assessmentTeachingApi.reviews).mockResolvedValue([{ task_id: "task", student_name: "学生", title: "实验", kind: "PROGRAMMING", version_no: 2, status: "SUBMITTED" }]);
  vi.mocked(assessmentTeachingApi.review).mockResolvedValue({ student_name: "学生", sections: [{ kind: "PROGRAMMING", status: "SUBMITTED", submission_version: 2, row_version: 7, questions: [], grading_status: "COMPLETED" }], sources: [], report: { body_markdown: "固定报告" }, report_criteria: [{ id: "criterion", title: "分析", max_score: "10" }] } as never);
  vi.mocked(assessmentTeachingApi.reportSuggestion).mockResolvedValue({ submission_version: 2, criteria: [{ criterion_id: "criterion", score: "9", rationale: "依据", evidence: "报告" }] });
});
async function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/course/publishing/pub/reviews"]}><Routes>
    <Route path="/courses/:courseId/publishing/:publicationId/reviews" element={<Reviews />} />
  </Routes></MemoryRouter></ToastProvider></QueryClientProvider>);
  await screen.findByRole("option", { name: /学生 · 实验/ });
  const select = screen.getByRole("combobox") as HTMLSelectElement;
  select.value = "task";
  fireEvent.change(select);
  expect(select.value).toBe("task");
  await waitFor(() => expect(assessmentTeachingApi.review).toHaveBeenCalledWith("course", "task"));
  await screen.findByText("固定报告");
}
it("按发布筛选交卷，AI 建议需教师确认保存", async () => {
  await show();
  expect(assessmentTeachingApi.reviews).toHaveBeenCalledWith("course", "pub");
  fireEvent.click(screen.getByRole("button", { name: "获取报告 AI 建议" }));
  fireEvent.click(await screen.findByRole("button", { name: "填入建议，人工核对后保存" }));
  expect(assessmentTeachingApi.saveReview).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "保存报告评分" }));
  await waitFor(() => expect(assessmentTeachingApi.saveReview).toHaveBeenCalledWith("course", "task", {
    submission_version: 2, scores: { criterion: "9" }, feedback: "",
  }, 7));
});

it("从任务链接打开时自动载入指定学生的评审", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/course/reviews?task=task"]}><Routes>
    <Route path="/courses/:courseId/reviews" element={<Reviews />} />
  </Routes></MemoryRouter></ToastProvider></QueryClientProvider>);

  await waitFor(() => expect(assessmentTeachingApi.review).toHaveBeenCalledWith("course", "task"));
  expect(await screen.findByText("固定报告")).toBeInTheDocument();
  client.clear();
});
it("AI 失败仍可人工填写报告分", async () => {
  vi.mocked(assessmentTeachingApi.reportSuggestion).mockRejectedValue(new Error("offline"));
  await show();
  fireEvent.click(screen.getByRole("button", { name: "获取报告 AI 建议" }));
  expect(await screen.findByText("报告 AI 建议暂不可用，请人工评分")).toBeInTheDocument();
  expect(screen.getByRole("spinbutton")).toBeEnabled();
});

it("shows a read-only answer sheet for choice submissions", async () => {
  vi.mocked(assessmentTeachingApi.reviews).mockResolvedValue([{
    task_id: "choice-task", student_name: "李四", title: "选择题", kind: "CHOICE",
    version_no: 1, status: "SUBMITTED",
  }]);
  vi.mocked(assessmentTeachingApi.review).mockResolvedValue({
    student_name: "李四",
    sections: [{
      kind: "CHOICE", status: "SUBMITTED", submission_version: 1, row_version: 3,
      questions: [], grading_status: "COMPLETED", max_score: "5",
    }],
    sources: [], report: null, report_criteria: [],
    choice_answers: [{
      question_id: "q1", title: "栈", task_type: "SINGLE_CHOICE",
      options: [{ id: "a", text: "先进先出" }, { id: "b", text: "后进先出" }],
      selected_option_ids: ["b"], correct_option_ids: ["b"], score: "5", max_score: "5",
    }],
  } as never);

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/course/publishing/pub/reviews"]}><Routes>
    <Route path="/courses/:courseId/publishing/:publicationId/reviews" element={<Reviews />} />
  </Routes></MemoryRouter></ToastProvider></QueryClientProvider>);

  const select = await screen.findByRole("combobox") as HTMLSelectElement;
  await screen.findByRole("option", { name: /李四 · 选择题 · 选择题/ });
  select.value = "choice-task";
  fireEvent.change(select);
  expect(await screen.findByText("李四 · 选择题答卷")).toBeInTheDocument();
  expect(screen.getByText("5 / 5")).toBeInTheDocument();
  client.clear();
});

it("shows returned reports in the submission list and detail", async () => {
  vi.mocked(assessmentTeachingApi.reviews).mockResolvedValue([{
    task_id: "task", student_name: "学生", title: "实验", kind: "PROGRAMMING",
    version_no: 2, status: "RETURNED", review_status: "RETURNED",
  }]);
  vi.mocked(assessmentTeachingApi.review).mockResolvedValue({
    student_name: "学生", sections: [{ kind: "PROGRAMMING", status: "RETURNED",
      review_status: "RETURNED", submission_version: 2, row_version: 7, questions: [], grading_status: "RETURNED" }],
    sources: [], report: { body_markdown: "固定报告" }, report_criteria: [],
  } as never);
  await show();
  expect(screen.getByRole("option", { name: /已退回/ })).toBeInTheDocument();
  expect(screen.getByText("报告评审：已退回")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "保存报告评分" })).toBeDisabled();
});
