import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { teachingApi } from "@edu/api-client";
import { TemplateEditor } from "./template-editor";

vi.mock("@edu/api-client", () => ({ teachingApi: {
  templateVersions: vi.fn(async () => ({ rows: [{ public_id: "version-1", status: "DRAFT", row_version: "5", version_no: 1 }] })),
  templateChapters: vi.fn(async () => ({ rows: [] })),
  templateOptions: vi.fn(async () => ({})), precheckRuns: vi.fn(async () => ({ rows: [] })),
  saveExecutionSpec: vi.fn(async () => ({ public_id: "version-1", row_version: "6" })),
  precheck: vi.fn(async () => ({})),
} }));

it("starts precheck with the saved version even while the list cache is stale", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/course-1/templates/template-1/edit"]}>
    <Routes><Route path="/courses/:courseId/templates/:templateId/edit" element={<TemplateEditor />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);
  await screen.findAllByText(/v1 · DRAFT/);
  fireEvent.click(screen.getByRole("button", { name: /预检与发布/ }));
  fireEvent.click(await screen.findByRole("button", { name: "保存执行规格并运行预检" }));
  await waitFor(() => expect(teachingApi.precheck).toHaveBeenCalledWith("course-1", "version-1", "6"));
  client.clear();
});
