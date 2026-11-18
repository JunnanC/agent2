import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { teachingApi } from "@edu/api-client";
import { GradeAnalysis } from "./grade-analysis";

vi.mock("@edu/api-client", () => ({ teachingApi: {
  publications: vi.fn(), progress: vi.fn(), enrollments: vi.fn(), createRetakePublication: vi.fn(),
} }));

afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(teachingApi.publications).mockResolvedValue({ rows: [{ public_id: "pub-1", title: "实验一" }], total: 1 } as never);
  vi.mocked(teachingApi.progress).mockResolvedValue({ rows: [
    { public_id: "task-1", publication_id: "pub-1", student_id: "student-1", student_name: "张三", title: "实验一", status: "COMPLETED", score: "90" },
    { public_id: "task-2", publication_id: "pub-1", student_id: "student-2", student_name: "李四", title: "实验一", status: "SUBMITTED", score: null },
  ], total: 2 } as never);
});

it("searches all experiment rows by student and links to that task's review", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/course/analytics"]}>
    <Routes><Route path="/courses/:courseId/analytics" element={<GradeAnalysis courseId="course" />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);

  expect(await screen.findByText("张三")).toBeInTheDocument();
  expect(screen.getByText("李四")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("searchbox", { name: "搜索全部实验中的学生" }), { target: { value: "李四" } });
  expect(screen.getByText("李四")).toBeInTheDocument();
  expect(screen.queryByText("张三")).toBeNull();
  expect(screen.getByRole("link", { name: "编程与报告评审" })).toHaveAttribute("href", "/courses/course/reviews?task=task-2");
  client.clear();
});
