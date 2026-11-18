import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { assessmentTeachingApi, teachingApi } from "@edu/api-client";
import { Students } from "./students";

vi.mock("@edu/api-client", () => ({
  teachingApi: { progress: vi.fn() },
  assessmentTeachingApi: { reviews: vi.fn(), review: vi.fn() },
}));

afterEach(cleanup);

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(teachingApi.progress).mockResolvedValue({
    rows: [{
      public_id: "task-1", student_name: "张三", title: "选择题实验", status: "APPROVED",
      progress: 100, score: "88.00", effective_deadline: "2020-01-01T00:00:00Z", report_required: false,
    }],
    total: 1,
  } as never);
  vi.mocked(assessmentTeachingApi.reviews).mockResolvedValue([]);
});

it("treats an approved choice task as finished, with report marked not applicable", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/course/students"]}>
    <Routes><Route path="/courses/:courseId/students" element={<Students />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);

  expect(await screen.findByText("张三")).toBeTruthy();
  expect(screen.getByText("已结束")).toBeTruthy();
  expect(screen.getByText("不适用")).toBeTruthy();
  expect(screen.getByText("正常")).toBeTruthy();
  expect(screen.queryByText("逾期未完成")).toBeNull();
  client.clear();
});

it("counts only reports awaiting review and shows completed and returned reports", async () => {
  vi.mocked(teachingApi.progress).mockResolvedValue({ rows: [
    { public_id: "done", student_name: "已评分学生", title: "实验", status: "APPROVED", progress: 100 },
    { public_id: "returned", student_name: "退回学生", title: "实验", status: "REPORT_DRAFT", progress: 0 },
  ], total: 2 } as never);
  vi.mocked(assessmentTeachingApi.reviews).mockResolvedValue([
    { task_id: "done", kind: "PROGRAMMING", status: "SUBMITTED", review_status: "COMPLETED" },
    { task_id: "returned", kind: "PROGRAMMING", status: "RETURNED", review_status: "RETURNED" },
    { task_id: "pending", kind: "PROGRAMMING", status: "SUBMITTED", review_status: "PENDING" },
    { task_id: "choice", kind: "CHOICE", status: "SUBMITTED", review_status: "NOT_REQUIRED" },
  ] as never);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/course/students"]}>
    <Routes><Route path="/courses/:courseId/students" element={<Students />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);
  expect(await screen.findByText("已完成评审")).toBeTruthy();
  expect(screen.getByText("已退回")).toBeTruthy();
  expect(screen.getByText("报告待审").closest(".metric")?.textContent).toContain("1");
  client.clear();
});

it("filters all progress rows by student, experiment, or score and opens the selected submission", async () => {
  vi.mocked(teachingApi.progress).mockImplementation(async (_courseId, query) => ({
    rows: query?.page === 2
      ? [{ public_id: "task-2", student_name: "李四", title: "编程实验", status: "COMPLETED", progress: 100, score: "95.00" }]
      : [{ public_id: "task-1", student_name: "张三", title: "选择题实验", status: "APPROVED", progress: 100, score: "88.00" }],
    total: 2,
  } as never));
  vi.mocked(assessmentTeachingApi.review).mockResolvedValue({
    student_name: "李四", sections: [], report_criteria: [], report: null,
  } as never);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/course/students"]}>
    <Routes><Route path="/courses/:courseId/students" element={<Students />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);

  expect(await screen.findByText("李四")).toBeTruthy();
  expect(teachingApi.progress).toHaveBeenCalledTimes(2);
  fireEvent.change(screen.getByRole("searchbox", { name: "搜索学生、实验或成绩" }), { target: { value: "95" } });
  expect(screen.getByText("李四")).toBeTruthy();
  expect(screen.queryByText("张三")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "查看答卷" }));
  expect(await screen.findByText("提交预览 · 编程实验")).toBeTruthy();
  expect(assessmentTeachingApi.review).toHaveBeenCalledWith("course", "task-2");
  client.clear();
});
