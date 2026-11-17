import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { teachingApi } from "@edu/api-client";
import { Enrollments } from "./enrollments";

const writeText = vi.fn(async () => {});
vi.mock("@edu/api-client", () => ({ teachingApi: {
  enrollments: vi.fn(async () => ({ rows: [] })), course: vi.fn(async () => ({ title: "课程" })),
  invitations: vi.fn(async () => ({ rows: [{ public_id: "old", code: "abc***", status: "ACTIVE" }] })),
  createInvitation: vi.fn(async () => ({ public_id: "new", code: "plain-code-123" })),
} }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("generates a readable invitation from a legacy masked code and copies it", async () => {
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/c/enrollments"]}><Routes><Route path="/courses/:courseId/enrollments" element={<Enrollments />} /></Routes></MemoryRouter></ToastProvider></QueryClientProvider>);
  expect(await screen.findByText("abc***")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "复制邀请码" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith("plain-code-123"));
  expect(await screen.findByText("plain-code-123")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "复制" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledTimes(2));
  expect(writeText).not.toHaveBeenCalledWith("abc***");
  expect(teachingApi.createInvitation).toHaveBeenCalledTimes(1);
  client.clear();
});
