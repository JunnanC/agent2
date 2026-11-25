import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { teachingApi } from "@edu/api-client";
import type { Invitation } from "@edu/api-client";
import { CourseLayout } from "@/app/course-layout";
import { Enrollments } from "./enrollments";

const writeText = vi.fn(async () => {});
vi.mock("@edu/api-client", () => ({ teachingApi: {
  enrollments: vi.fn(async () => ({ rows: [] })), course: vi.fn(async () => ({ title: "课程" })),
  publications: vi.fn(async () => ({ rows: [], total: 0 })),
  invitations: vi.fn(async () => ({ rows: [{ public_id: "old", code: "abc***", status: "ACTIVE" }] })),
  createInvitation: vi.fn(async () => ({ public_id: "new", code: "plain-code-123" })),
} }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

function renderEnrollments() {
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/c/enrollments"]}>
    <Routes><Route path="/courses/:courseId/enrollments" element={<CourseLayout><Enrollments /></CourseLayout>} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);
  return client;
}

it("opens invitation management and copies a new code when the old code is masked", async () => {
  const client = renderEnrollments();
  expect(await screen.findByRole("link", { name: "管理邀请码" })).toHaveAttribute("href", "/courses/c/enrollments#course-invitation");
  fireEvent.click(screen.getByText("管理课程邀请码", { selector: "summary" }));
  const actions = screen.getByRole("group", { name: "课程邀请码" });
  const invitation = within(actions);
  await invitation.findByText("旧邀请码已脱敏，可生成新码");
  expect(invitation.getByRole("button", { name: "复制邀请码" })).toBeDisabled();
  fireEvent.click(invitation.getByRole("button", { name: "生成邀请码" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith("plain-code-123"));
  expect(await invitation.findByText("plain-code-123")).toBeInTheDocument();
  fireEvent.click(invitation.getByRole("button", { name: "复制邀请码" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledTimes(2));
  expect(writeText).not.toHaveBeenCalledWith("abc***");
  expect(teachingApi.createInvitation).toHaveBeenCalledExactlyOnceWith("c", { valid_days: 30 });
  client.clear();
});

it("copies the existing readable invitation without generating a new one", async () => {
  const active: Invitation = { public_id: "active", course_id: "c", status: "ACTIVE", code: "existing-code", recoverable: true };
  vi.mocked(teachingApi.invitations).mockResolvedValueOnce({ rows: [active], total: 1, page: 1, pageSize: 20 });
  const client = renderEnrollments();
  await screen.findByRole("heading", { name: "课程" });
  fireEvent.click(await screen.findByText("管理课程邀请码", { selector: "summary" }));
  const invitation = within(screen.getByRole("group", { name: "课程邀请码" }));
  expect(await invitation.findByText("existing-code")).toBeInTheDocument();
  expect(invitation.getByRole("button", { name: "重新生成邀请码" })).toBeEnabled();
  fireEvent.click(invitation.getByRole("button", { name: "复制邀请码" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledExactlyOnceWith("existing-code"));
  expect(teachingApi.createInvitation).not.toHaveBeenCalled();
  client.clear();
});
