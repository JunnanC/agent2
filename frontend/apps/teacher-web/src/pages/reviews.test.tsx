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
async function show(expectedText = "固定报告", rowName = /打开答卷：学生 · 实验/, taskId = "task") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/course/publishing/pub/reviews"]}><Routes>
    <Route path="/courses/:courseId/publishing/:publicationId/reviews" element={<Reviews />} />
  </Routes></MemoryRouter></ToastProvider></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: rowName }));
  await waitFor(() => expect(assessmentTeachingApi.review).toHaveBeenCalledWith("course", taskId));
  await screen.findByText("学生试卷");
  expect(screen.queryByRole("navigation", { name: "面包屑" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("当前成绩")).toBeInTheDocument();
  if (expectedText) await screen.findByText(expectedText);
}
it("按发布筛选交卷，AI 建议需教师确认保存", async () => {
  await show();
  expect(assessmentTeachingApi.reviews).toHaveBeenCalledWith("course", "pub");
  fireEvent.click(screen.getByRole("button", { name: "获取报告 AI 建议" }));
  fireEvent.click(await screen.findByRole("button", { name: "填入建议分" }));
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
      question_id: "q1", title: "栈", description: "栈顶元素最先出栈。", task_type: "SINGLE_CHOICE",
      options: [{ id: "a", text: "先进先出" }, { id: "b", text: "后进先出" }],
      selected_option_ids: ["b"], correct_option_ids: ["b"], score: "5", max_score: "5",
    }],
  } as never);

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/course/publishing/pub/reviews"]}><Routes>
    <Route path="/courses/:courseId/publishing/:publicationId/reviews" element={<Reviews />} />
  </Routes></MemoryRouter></ToastProvider></QueryClientProvider>);

  fireEvent.click(await screen.findByRole("button", { name: /打开答卷：李四 · 选择题/ }));
  expect(await screen.findByRole("heading", { name: "选择题答卷" })).toBeInTheDocument();
  expect(screen.getAllByText(/5 \/ 5/).length).toBeGreaterThan(0);
  expect(screen.getAllByText("后进先出").length).toBeGreaterThan(0);
  expect(screen.getByText("栈顶元素最先出栈。")).toBeInTheDocument();
  client.clear();
});

it("shows programming prompts, public samples, and submitted source in the paper", async () => {
  vi.mocked(assessmentTeachingApi.reviews).mockResolvedValue([{
    task_id: "code-task", student_name: "王同学", title: "数组求和", kind: "PROGRAMMING",
    version_no: 1, status: "SUBMITTED", review_status: "PENDING",
  }]);
  vi.mocked(assessmentTeachingApi.review).mockResolvedValue({
    student_name: "王同学",
    sections: [{ kind: "PROGRAMMING", status: "SUBMITTED", submission_version: 1,
      row_version: 3, grading_status: "COMPLETED", score: "8", max_score: "10",
      questions: [{ id: "q1", title: "数组求和", description: "输入整数数组并输出元素之和。",
        instructions: "使用标准输入输出。", task_type: "PROGRAMMING", language: "python",
        samples: [{ input: "1 2 3", output: "6" }], score: "8", max_score: "10" }] }],
    sources: [{ question_id: "q1", language: "python", files: { "main.py": "print(sum(map(int, input().split())))" } }],
    report: null, report_criteria: [], choice_answers: [],
  } as never);

  await show("", /打开答卷：王同学 · 数组求和/, "code-task");
  expect(screen.getByText("输入整数数组并输出元素之和。")).toBeInTheDocument();
  expect(screen.getByText("使用标准输入输出。")).toBeInTheDocument();
  fireEvent.click(screen.getByText("公开示例"));
  expect(screen.getByText("1 2 3")).toBeInTheDocument();
  fireEvent.click(screen.getByText("查看学生代码（python）"));
  expect(screen.getByText("print(sum(map(int, input().split())))")).toBeInTheDocument();
});

it("shows returned reports in the submission list and detail", async () => {
  vi.mocked(assessmentTeachingApi.reviews).mockResolvedValue([{
    task_id: "task", student_name: "学生", title: "实验", kind: "PROGRAMMING",
    version_no: 2, status: "RETURNED", review_status: "RETURNED",
  }]);
  vi.mocked(assessmentTeachingApi.review).mockResolvedValue({
    student_name: "学生", sections: [{ kind: "PROGRAMMING", status: "RETURNED",
      review_status: "RETURNED", submission_version: 2, row_version: 7, questions: [], grading_status: "RETURNED" }],
    sources: [], report: { body_markdown: "固定报告", version_no: 2 },
    report_criteria: [{ id: "criterion", title: "分析", max_score: "10" }],
  } as never);
  await show();
  expect(screen.getAllByText("已退回").length).toBeGreaterThan(0);
  expect(screen.getByRole("button", { name: "保存报告评分" })).toBeDisabled();
});
