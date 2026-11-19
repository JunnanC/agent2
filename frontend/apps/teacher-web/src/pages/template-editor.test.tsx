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
  vi.mocked(teachingApi.templateOptions).mockResolvedValue({
    runtime_adapters: [{ public_id: "docker", name: "真实 Docker", driver: "DOCKER_LOCAL" }],
    images: [{ public_id: "image", repository: "experimental-platform-stdio", display_tag: "local", digest: "sha256:abc" }],
    resource_profiles: [
      { public_id: "profile-sm", name: "轻量 0.25 核 / 256 MB", cpu_millicores: 250, memory_mb: 256, disk_gb: 1 },
      { public_id: "profile", name: "标准 0.5 核 / 512 MB", cpu_millicores: 500, memory_mb: 512, disk_gb: 2 },
      { public_id: "profile-lg", name: "加强 1 核 / 1 GB", cpu_millicores: 1000, memory_mb: 1024, disk_gb: 2 },
    ],
    toolchains: [
      { language: "c", available: true },
      { language: "cpp", available: true },
      { language: "java", available: true },
      { language: "python", available: true },
      { language: "go", available: true },
    ],
  } as never);
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
it("判题资源只留档位选择，切换档位即保存", async () => {
  show(); await screen.findByText("题目编辑");
  // 运行方式和语言环境由平台统一维护，不再出现在教师界面
  expect(screen.queryByLabelText("运行方式")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("语言环境")).not.toBeInTheDocument();
  expect(screen.queryByText(/判题环境由平台统一维护/)).not.toBeInTheDocument();
  expect(screen.queryByText(/sha256/)).not.toBeInTheDocument();
  // 默认选中标准档
  expect(screen.getByRole("radio", { name: /标准 · 0.5 核 CPU \/ 512 MB 内存/ })).toBeChecked();
  // 切到加强档立即保存，且带上平台默认的适配器与镜像
  fireEvent.click(screen.getByRole("radio", { name: /加强 · 1 核 CPU \/ 1 GB 内存/ }));
  await waitFor(() => expect(teachingApi.updateTemplateVersion).toHaveBeenCalledWith("course", "v1", {
    runtime_type: "CONTAINER", runtime_adapter_id: "docker", image_id: "image", resource_profile_id: "profile-lg",
  }, "5"));
});

it("没有可用判题资源时提示联系管理员", async () => {
  vi.mocked(teachingApi.templateOptions).mockResolvedValue({
    runtime_adapters: [], images: [], resource_profiles: [], toolchains: [],
  } as never);
  show(); await screen.findByText("题目编辑");
  expect(await screen.findByText("暂无可用的判题资源，请联系管理员。")).toBeInTheDocument();
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
