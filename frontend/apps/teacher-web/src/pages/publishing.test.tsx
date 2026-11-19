import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { teachingApi } from "@edu/api-client";
import { Publishing } from "./publishing";

vi.mock("@edu/api-client", () => ({ teachingApi: {
  courseResource: vi.fn(async () => ({ rows: [{ public_id: "chapter-1", title: "第一章" }] })),
  templates: vi.fn(async () => ({ rows: [] })),
  rubrics: vi.fn(async () => ({ rows: [] })),
  publications: vi.fn(async () => ({ rows: [{ public_id: "p1", status: "DRAFT", title: "实验", template_version_id: "v1" }] })),
  templateVersion: vi.fn(async () => ({ public_id: "v1", status: "PUBLISHED", row_version: "9" })),
  createPublication: vi.fn(),
  precheckRuns: vi.fn(async () => ({ rows: [{ status: "PASSED", stage_results: [] }] })),
  precheck: vi.fn(),
} }));
afterEach(cleanup);
it("预检没有阶段记录时仍显示失败状态和原因", async () => {
  vi.mocked(teachingApi.precheckRuns).mockResolvedValueOnce({ rows: [{
    public_id: "failed-run", template_version_id: "v1",
    status: "FAILED", stage_results: [], error_code: "PRECHECK_WORKER_FAILED", error_detail: {},
  }], total: 1, page: 1, pageSize: 1 });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/c1/publishing"]}><Routes>
    <Route path="/courses/:courseId/publishing" element={<Publishing />} />
  </Routes></MemoryRouter></ToastProvider></QueryClientProvider>);

  expect(await screen.findByText("预检服务执行失败，请重新预检。")).toBeInTheDocument();
  expect(screen.getByText("未通过")).toBeInTheDocument();
  expect(screen.queryByText("预检进行中")).not.toBeInTheDocument();
  client.clear();
});

it("reuses an already published template's precheck without sending a conflicting command", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/c1/publishing"]}><Routes><Route path="/courses/:courseId/publishing" element={<Publishing />} /></Routes></MemoryRouter></ToastProvider></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "检查预检状态" }));
  await waitFor(() => expect(teachingApi.templateVersion).toHaveBeenCalledWith("c1", "v1"));
  expect(await screen.findByText("该模板版本已通过预检，可直接发布实验")).toBeInTheDocument();
  expect(teachingApi.precheck).not.toHaveBeenCalled();
  client.clear();
});

it("creates a programming publication without requiring a report or rubric", async () => {
  vi.mocked(teachingApi.templates).mockResolvedValue({ rows: [{
    public_id: "template-1", name: "模板", current_version_id: "version-1",
  }] } as never);
  vi.mocked(teachingApi.templateVersion).mockResolvedValue({
    public_id: "version-1", status: "PUBLISHED", row_version: "9",
    chapters: [{ tasks: [{ task_type: "PROGRAMMING" }] }],
  } as never);

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/c1/publishing?template=template-1"]}><Routes>
    <Route path="/courses/:courseId/publishing" element={<Publishing />} />
  </Routes></MemoryRouter></ToastProvider></QueryClientProvider>);
  const reportRequired = await screen.findByRole("checkbox", { name: "需要提交实验报告" });
  fireEvent.click(reportRequired);
  expect(reportRequired).not.toBeChecked();
  fireEvent.change(screen.getByLabelText("所属课程章节"), { target: { value: "chapter-1" } });
  fireEvent.change(screen.getByLabelText(/发布标题/), { target: { value: "不要求报告的编程实验" } });
  fireEvent.change(screen.getByLabelText(/开放时间/), { target: { value: "2026-12-01T09:00" } });
  fireEvent.change(screen.getByLabelText(/截止时间/), { target: { value: "2026-12-02T09:00" } });
  fireEvent.click(screen.getByRole("button", { name: "创建草稿" }));

  await waitFor(() => expect(teachingApi.createPublication).toHaveBeenCalledWith("c1", expect.objectContaining({
    report_required: false,
    rubric_version_id: null,
  })));
  client.clear();
});
