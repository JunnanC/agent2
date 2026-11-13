import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { assessmentTeachingApi, teachingApi } from "@edu/api-client";
import { Students } from "./students";

vi.mock("@edu/api-client", () => ({
  teachingApi: { progress: vi.fn() },
  assessmentTeachingApi: { reviews: vi.fn() },
}));

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(teachingApi.progress).mockResolvedValue({
    rows: [{
      public_id: "task-1", student_name: "张三", title: "选择题实验", status: "APPROVED",
      progress: 100, effective_deadline: "2020-01-01T00:00:00Z", report_required: false,
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
