import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { TemplateEditor } from "./template-editor";

vi.mock("@edu/api-client", () => ({ teachingApi: {
  templateVersions: vi.fn(async () => ({ rows: [{ public_id: "v1", status: "PRECHECK_PASSED", row_version: "8", version_no: 1 }] })),
  templateChapters: vi.fn(async () => ({ rows: [] })), templateOptions: vi.fn(async () => ({})),
  precheckRuns: vi.fn(async () => ({ rows: [{ public_id: "run", status: "PASSED", stage_results: [{ stage: "ASSETS", result: "PASSED" }] }] })),
} }));

it("shows the backend PASSED status and stage_results as completed", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/c/templates/t/edit"]}>
    <Routes><Route path="/courses/:courseId/templates/:templateId/edit" element={<TemplateEditor />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: /预检与发布/ }));
  expect(await screen.findByText("ASSETS")).toBeInTheDocument();
  expect(screen.queryByText("预检进行中")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "发布模板版本" })).toBeEnabled();
  client.clear();
});
