import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { assessmentTeachingApi, teachingApi } from "@edu/api-client";
import { Home } from "./home";

vi.mock("@edu/api-client", () => ({
  teachingApi: { courses: vi.fn(), publications: vi.fn(), progress: vi.fn() },
  assessmentTeachingApi: { reviews: vi.fn() },
}));

it("excludes graded, returned and choice submissions from pending reports", async () => {
  vi.mocked(teachingApi.courses).mockResolvedValue({ rows: [{ public_id: "course", title: "课程", status: "ACTIVE" }], total: 1 } as never);
  vi.mocked(teachingApi.publications).mockResolvedValue({ rows: [], total: 0 } as never);
  vi.mocked(teachingApi.progress).mockResolvedValue({ rows: [{ status: "APPROVED" }], total: 1 } as never);
  vi.mocked(assessmentTeachingApi.reviews).mockResolvedValue([
    { kind: "PROGRAMMING", status: "SUBMITTED", review_status: "COMPLETED" },
    { kind: "PROGRAMMING", status: "RETURNED", review_status: "RETURNED" },
    { kind: "PROGRAMMING", status: "SUBMITTED", review_status: "PENDING" },
    { kind: "CHOICE", status: "SUBMITTED", review_status: "NOT_REQUIRED" },
  ] as never);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><Home /></MemoryRouter></QueryClientProvider>);
  await waitFor(() => expect(screen.getByText("班级完成率").closest(".metric")?.querySelector("strong")?.textContent).toBe("100%"));
  expect(screen.getByText("待评审报告").closest(".metric")?.querySelector("strong")?.textContent).toBe("1");
  client.clear();
});
