import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { Templates } from "./templates";

vi.mock("@edu/api-client", () => ({ teachingApi: {
  course: vi.fn(async () => ({ title: "课程" })),
  templates: vi.fn(async () => ({ rows: [
    { public_id: "published", name: "已发布模板", status: "PUBLISHED", current_version_no: 1 },
    { public_id: "draft", name: "草稿模板", status: "DRAFT", current_version_no: 2 },
  ], total: 2 })),
  createTemplate: vi.fn(), deleteTemplate: vi.fn(),
} }));

afterEach(cleanup);

it("keeps template actions grouped for rows with different action counts", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/course/templates"]}>
    <Routes><Route path="/courses/:courseId/templates" element={<Templates />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);

  const published = await screen.findByText("已发布模板");
  const publishedActions = published.closest("tr")?.querySelector(".table-actions");
  expect(publishedActions).not.toBeNull();
  expect(within(publishedActions as HTMLElement).getAllByRole("link")).toHaveLength(2);

  const draft = screen.getByText("草稿模板");
  const draftActions = draft.closest("tr")?.querySelector(".table-actions");
  expect(draftActions).not.toBeNull();
  expect(within(draftActions as HTMLElement).getAllByRole("link")).toHaveLength(2);
  expect(within(draftActions as HTMLElement).getByRole("button", { name: "删除" })).toBeInTheDocument();
  client.clear();
});
