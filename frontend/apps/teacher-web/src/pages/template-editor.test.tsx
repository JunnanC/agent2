import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { teachingApi } from "@edu/api-client";
import { TemplateEditor } from "./template-editor";

vi.mock("@edu/api-client", () => ({ teachingApi: {
  templateVersions: vi.fn(async () => ({ rows: [{ public_id: "version-1", status: "DRAFT", row_version: "5", version_no: 1 }] })),
  templateChapters: vi.fn(async () => ({ rows: [] })),
  templateOptions: vi.fn(async () => ({ images: [{ public_id: "image-2", repository: "test-image" }], runtime_adapters: [{ public_id: "adapter-2", name: "Docker 新适配器" }], resource_profiles: [{ public_id: "profile-2", name: "小规格" }], toolchains: [
    { language: "c", toolchain_id: "gnu-gcc", versions: [{ version: "12.2.0", default: true }], default_standard: "c17", standards: ["c17"], entrypoint: "main.c", available: false },
    { language: "python", toolchain_id: "cpython", versions: [{ version: "3.14.0", default: true }], default_standard: "3", standards: ["3"], entrypoint: "main.py", available: true },
  ] })), precheckRuns: vi.fn(async () => ({ rows: [] })),
  saveExecutionSpec: vi.fn(async () => ({ public_id: "version-1", row_version: "6" })),
  precheck: vi.fn(async () => ({})),
  updateTemplateVersion: vi.fn(async () => ({})),
} }));

afterEach(cleanup);

it("saves the selected runtime adapter together with image and resource profile", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/course-1/templates/template-1/edit"]}>
    <Routes><Route path="/courses/:courseId/templates/:templateId/edit" element={<TemplateEditor />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: /运行环境/ }));
  fireEvent.click(await screen.findByRole("radio", { name: /test-image/ }));
  fireEvent.click(screen.getByRole("radio", { name: /Docker 新适配器/ }));
  fireEvent.click(screen.getByRole("radio", { name: /小规格/ }));
  fireEvent.click(screen.getByRole("button", { name: "保存运行环境" }));
  await waitFor(() => expect(teachingApi.updateTemplateVersion).toHaveBeenCalledWith("course-1", "version-1", {
    runtime_adapter_id: "adapter-2", image_id: "image-2", resource_profile_id: "profile-2",
  }, "5"));
  client.clear();
});

it("starts precheck with the saved version even while the list cache is stale", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/course-1/templates/template-1/edit"]}>
    <Routes><Route path="/courses/:courseId/templates/:templateId/edit" element={<TemplateEditor />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);
  await screen.findAllByText(/v1 · DRAFT/);
  fireEvent.click(screen.getByRole("button", { name: /预检与发布/ }));
  const languages = await screen.findByLabelText("编程语言");
  expect(languages).toHaveValue("");
  expect(screen.getByRole("option", { name: /学生自选（当前可用：python）/ })).toBeInTheDocument();
  fireEvent.change(languages, { target: { value: "c" } });
  expect(screen.getByLabelText("工具链版本")).toHaveValue("");
  expect(screen.getByText(/gnu-gcc 12\.2\.0；c17；当前运行镜像未提供该工具链/)).toBeInTheDocument();
  fireEvent.change(languages, { target: { value: "python" } });
  expect(screen.getByText(/工具链：cpython 3\.14\.0；3/)).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "保存执行规格并运行预检" }));
  await waitFor(() => expect(teachingApi.precheck).toHaveBeenCalledWith("course-1", "version-1", "6"));
  expect(teachingApi.saveExecutionSpec).toHaveBeenCalledWith(
    "course-1",
    "version-1",
    expect.objectContaining({
      schema_version: 2,
      language: "python",
      toolchain_version: null,
      language_standard: null,
      absolute_tolerance: 1e-6,
      relative_tolerance: 1e-6,
    }),
    "5",
  );
  client.clear();
});
