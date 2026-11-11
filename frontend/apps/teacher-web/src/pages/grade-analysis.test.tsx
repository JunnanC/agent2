import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { teachingApi } from "@edu/api-client";
import { GradeAnalysis } from "./grade-analysis";

vi.mock("@edu/api-client", () => ({ teachingApi: {
  publications: vi.fn(), progress: vi.fn(), reviews: vi.fn(), review: vi.fn(), enrollments: vi.fn(),
  createRetakePublication: vi.fn(),
} }));

let client: QueryClient;
beforeEach(() => {
  vi.resetAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  vi.mocked(teachingApi.publications).mockResolvedValue({ rows: [
    { public_id: "publication-1", title: "Experiment", status: "PUBLISHED", row_version: "1" },
  ], total: 1, page: 1, pageSize: 100 } as never);
  vi.mocked(teachingApi.progress).mockResolvedValue({ rows: [
    { public_id: "task-1", publication_id: "publication-1", student_id: "student-1", student_name: "Alice", status: "APPROVED" },
  ], total: 1, page: 1, pageSize: 100 } as never);
  vi.mocked(teachingApi.reviews).mockResolvedValue({ rows: [], total: 0, page: 1, pageSize: 100 } as never);
  vi.mocked(teachingApi.enrollments).mockResolvedValue({ rows: [
    { public_id: "enrollment-1", student_id: "student-1", student_name: "Alice", status: "ACTIVE" },
    { public_id: "enrollment-2", student_id: "student-2", student_name: "Bob", status: "ACTIVE" },
  ], total: 2, page: 1, pageSize: 100 } as never);
  vi.mocked(teachingApi.createRetakePublication).mockResolvedValue({
    public_id: "retake-publication", status: "PUBLISHED",
  } as never);
});
afterEach(() => { cleanup(); client.clear(); });

it("selects active enrolled students with an original task and creates a linked retake", async () => {
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter><GradeAnalysis courseId="course-1" /></MemoryRouter></ToastProvider></QueryClientProvider>);
  await screen.findByRole("option", { name: "Experiment" });
  fireEvent.change(screen.getByRole("combobox", { name: "选择成绩统计实验" }), {
    target: { value: "publication-1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "重新发布实验" }));
  await screen.findByRole("checkbox", { name: "选择Alice" });
  expect(screen.queryByRole("checkbox", { name: "选择Bob" })).not.toBeInTheDocument();
  expect(teachingApi.enrollments).toHaveBeenCalledWith("course-1", { status: "ACTIVE", page: 1 });

  fireEvent.click(screen.getByRole("checkbox", { name: "选择Alice" }));
  const start = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString().slice(0, 16);
  const end = new Date(Date.now() + 48 * 60 * 60 * 1000).toISOString().slice(0, 16);
  fireEvent.change(screen.getByLabelText("重新开放时间"), { target: { value: start } });
  fireEvent.change(screen.getByLabelText("重新提交截止时间"), { target: { value: end } });
  fireEvent.click(screen.getByRole("button", { name: "确认批量重新发布" }));

  await waitFor(() => expect(teachingApi.createRetakePublication).toHaveBeenCalledWith(
    "course-1",
    "publication-1",
    {
      selected_enrollment_ids: ["enrollment-1"],
      window_start: expect.any(String),
      window_end: expect.any(String),
    },
    expect.any(String),
  ));
  const payload = vi.mocked(teachingApi.createRetakePublication).mock.calls[0]![2];
  expect(Date.parse(payload.window_start)).not.toBeNaN();
  expect(Date.parse(payload.window_end)).not.toBeNaN();
});

it("shows and permits retry after a retake creation failure", async () => {
  vi.mocked(teachingApi.createRetakePublication).mockRejectedValue(new Error("已存在补做任务"));
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter><GradeAnalysis courseId="course-1" /></MemoryRouter></ToastProvider></QueryClientProvider>);
  await screen.findByRole("option", { name: "Experiment" });
  fireEvent.change(screen.getByRole("combobox", { name: "选择成绩统计实验" }), {
    target: { value: "publication-1" },
  });
  fireEvent.click(screen.getByRole("button", { name: "重新发布实验" }));
  fireEvent.click(await screen.findByRole("checkbox", { name: "选择Alice" }));
  const start = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString().slice(0, 16);
  const end = new Date(Date.now() + 48 * 60 * 60 * 1000).toISOString().slice(0, 16);
  fireEvent.change(screen.getByLabelText("重新开放时间"), { target: { value: start } });
  fireEvent.change(screen.getByLabelText("重新提交截止时间"), { target: { value: end } });
  fireEvent.click(screen.getByRole("button", { name: "确认批量重新发布" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("已存在补做任务");
  expect(screen.getByRole("button", { name: "确认批量重新发布" })).toBeEnabled();
  vi.mocked(teachingApi.createRetakePublication).mockResolvedValue({ status: "PUBLISHED" } as never);
  fireEvent.click(screen.getByRole("button", { name: "确认批量重新发布" }));
  await waitFor(() => expect(teachingApi.createRetakePublication).toHaveBeenCalledTimes(2));
  expect(vi.mocked(teachingApi.createRetakePublication).mock.calls[0]![3])
    .toBe(vi.mocked(teachingApi.createRetakePublication).mock.calls[1]![3]);
});

it("counts the original experiment once and uses the server effective grade", async () => {
  vi.mocked(teachingApi.progress).mockResolvedValue({ rows: [
    { public_id: "task-1", publication_id: "publication-1", student_id: "student-1", student_name: "Alice", score: "60.00", has_retake: true },
    { public_id: "task-retake", publication_id: "retake", student_id: "student-1", student_name: "Alice", score: "60.00", retake_of_task_id: "task-1" },
  ], total: 2, page: 1, pageSize: 100 } as never);
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter><GradeAnalysis courseId="course-1" /></MemoryRouter></ToastProvider></QueryClientProvider>);
  await screen.findByText("60.00");
  expect(screen.getAllByText("Alice")).toHaveLength(1);
  expect(teachingApi.reviews).not.toHaveBeenCalled();
});
