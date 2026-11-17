import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { teachingApi } from "@edu/api-client";
import { Publishing } from "./publishing";

vi.mock("@edu/api-client", () => ({ teachingApi: {
  courseResource: vi.fn(async () => ({rows:[]})),
  publications: vi.fn(async () => ({ rows: [{ public_id: "p1", status: "DRAFT", title: "实验", template_version_id: "v1" }] })),
  templateVersion: vi.fn(async () => ({ public_id: "v1", status: "PUBLISHED", row_version: "9" })),
  precheckRuns: vi.fn(async () => ({ rows: [{ status: "PASSED", stage_results: [] }] })),
  precheck: vi.fn(),
} }));
afterEach(cleanup);
it("reuses an already published template's precheck without sending a conflicting command", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/c1/publishing"]}><Routes><Route path="/courses/:courseId/publishing" element={<Publishing />} /></Routes></MemoryRouter></ToastProvider></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "检查预检状态" }));
  await waitFor(() => expect(teachingApi.templateVersion).toHaveBeenCalledWith("c1", "v1"));
  expect(await screen.findByText("该模板版本已通过预检，可直接发布实验")).toBeInTheDocument();
  expect(teachingApi.precheck).not.toHaveBeenCalled();
  client.clear();
});
