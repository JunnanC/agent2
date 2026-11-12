import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { taskApi } from "@edu/api-client";
import { ToastProvider } from "@edu/ui";
import { TaskDetail } from "./task-detail";

vi.mock("@edu/api-client", () => ({ taskApi: { detail: vi.fn(), requestExtension: vi.fn() } }));
vi.mock("@/components/course-agent", () => ({ CourseAgent: () => null }));
const fixture = {
  public_id: "task-1", title: "算法实验", course_id: "course-1", status: "ASSIGNED",
  assessment_available: true, allowed_actions: ["request_extension"], blockers: [], row_version: "2",
};
beforeEach(() => { vi.resetAllMocks(); vi.mocked(taskApi.detail).mockResolvedValue(fixture as never); });
function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/experiments/task-1"]}>
    <Routes><Route path="/experiments/:taskId" element={<TaskDetail />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);
}
it("提供轻量答题入口", async () => {
  show();
  expect(await screen.findByRole("link", { name: "进入实验答题" })).toHaveAttribute("href", "/experiments/task-1/assessment");
  expect(screen.queryByRole("button", { name: /启动|进入实验工作台/ })).not.toBeInTheDocument();
});
it("旧格式任务提示重新发布", async () => {
  vi.mocked(taskApi.detail).mockResolvedValue({ ...fixture, assessment_available: false } as never);
  show();
  expect(await screen.findByText(/此任务使用已停用的工作区格式/)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "进入实验答题" })).not.toBeInTheDocument();
});
it("保留版本检查的延期申请", async () => {
  vi.mocked(taskApi.requestExtension).mockResolvedValue({});
  show();
  fireEvent.click(await screen.findByRole("button", { name: "申请延期" }));
  fireEvent.change(screen.getByLabelText("申请原因"), { target: { value: "需要更多时间" } });
  fireEvent.click(screen.getByRole("button", { name: "提交延期申请" }));
  await waitFor(() => expect(taskApi.requestExtension).toHaveBeenCalledWith("task-1", { reason: "需要更多时间" }, "2"));
});
