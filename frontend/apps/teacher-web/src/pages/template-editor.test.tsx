import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { teachingApi } from "@edu/api-client";
import { TemplateEditor } from "./template-editor";

vi.mock("@/components/assessment-questions", () => ({ AssessmentQuestions: () => <p>题目编辑</p> }));
vi.mock("@edu/api-client", () => ({ teachingApi: {
  templateVersions: vi.fn(), templateOptions: vi.fn(), precheckRuns: vi.fn(),
  precheck: vi.fn(), updateTemplateVersion: vi.fn(), createTemplateVersion: vi.fn(), publishTemplateVersion: vi.fn(),
} }));
afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(teachingApi.templateVersions).mockResolvedValue({ rows: [{ public_id: "v1", status: "DRAFT", row_version: "5", version_no: 1 }], total: 1 } as never);
  vi.mocked(teachingApi.templateOptions).mockResolvedValue({ runtime_adapters: [{ public_id: "docker", name: "真实 Docker", driver: "DOCKER_LOCAL" }], images: [{ public_id: "image", repository: "stdio", digest: "sha256:abc" }], resource_profiles: [{ public_id: "profile", name: "规格" }] } as never);
  vi.mocked(teachingApi.precheckRuns).mockResolvedValue({ rows: [], total: 0 } as never);
});
function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/course/templates/template"]}><Routes>
    <Route path="/courses/:courseId/templates/:templateId" element={<TemplateEditor />} />
  </Routes></MemoryRouter></ToastProvider></QueryClientProvider>);
}
it("纯选择题无需运行环境即可编辑并预检", async () => {
  show();
  expect(await screen.findByText("题目编辑")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "执行预检" }));
  await waitFor(() => expect(teachingApi.precheck).toHaveBeenCalledWith("course", "v1", "5"));
  expect(screen.queryByText(/execution_spec/)).not.toBeInTheDocument();
});
it("编程环境只保存治理资源，不生成旧运行 JSON", async () => {
  show(); await screen.findByText("题目编辑");
  fireEvent.change(screen.getByLabelText("运行适配器"), { target: { value: "docker" } });
  fireEvent.change(screen.getByLabelText("执行镜像"), { target: { value: "image" } });
  fireEvent.change(screen.getByLabelText("资源规格"), { target: { value: "profile" } });
  fireEvent.click(screen.getByRole("button", { name: "保存运行环境" }));
  await waitFor(() => expect(teachingApi.updateTemplateVersion).toHaveBeenCalledWith("course", "v1", {
    runtime_type: "CONTAINER", runtime_adapter_id: "docker", image_id: "image", resource_profile_id: "profile",
  }, "5"));
});

it("执行预检失败后显示公开示例的校验原因", async () => {
  const run = { public_id: "failed-run", template_version_id: "v1" };
  vi.mocked(teachingApi.precheckRuns)
    .mockResolvedValueOnce({ rows: [], total: 0, page: 1, pageSize: 0 })
    .mockResolvedValueOnce({ rows: [{ ...run, status: "QUEUED" }], total: 1, page: 1, pageSize: 1 })
    .mockResolvedValue({ rows: [{
      ...run, status: "FAILED", error_code: "TEMPLATE_VALIDATION_ERROR",
      error_detail: { reference_solutions: "reference_does_not_pass_samples" },
    }], total: 1, page: 1, pageSize: 1 });
  show();
  await waitFor(() => expect(teachingApi.precheckRuns).toHaveBeenCalledWith("course", "v1"));
  fireEvent.click(screen.getByRole("button", { name: "执行预检" }));
  expect(await screen.findByText(/参考解未通过公开示例/, {}, { timeout: 4000 })).toBeInTheDocument();
});
