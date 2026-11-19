import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { studentApi } from "@edu/api-client";
import type { Enrollment } from "@edu/api-client";
import { ToastProvider } from "@edu/ui";
import { Courses } from "./courses";

vi.mock("@edu/api-client", () => ({ studentApi: {
  myEnrollments: vi.fn(), enrollment: vi.fn(), dropCheck: vi.fn(), dropEnrollment: vi.fn(), withdrawEnrollment: vi.fn(),
} }));
vi.mock("@/components/student-timetable", () => ({ StudentTimetable: () => null }));
vi.mock("@/components/learning-history", () => ({ LearningHistory: () => null }));

const active = { public_id: "en-active", course_id: "active-course", course_title: "已加入课程", status: "ACTIVE", row_version: "1" } as Enrollment;
const pending = { public_id: "en-pending", course_id: "pending-course", course_title: "待审核课程", status: "PENDING", row_version: "2" } as Enrollment;
const list = (rows: Enrollment[]) => ({ rows, page: 1, pageSize: 100, total: rows.length });
let client: QueryClient;
let rows: Enrollment[];
beforeEach(() => {
  vi.resetAllMocks();
  rows = [active, pending];
  vi.mocked(studentApi.myEnrollments).mockImplementation(async (query) => list(rows.filter((row) => row.status === query?.status)));
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
});
afterEach(() => { cleanup(); client.clear(); });
function show() {
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter><Courses /></MemoryRouter></ToastProvider></QueryClientProvider>);
}

it("我的课程展示待审核申请，撤回后刷新且不能进入待审核课程", async () => {
  vi.mocked(studentApi.enrollment).mockResolvedValue(pending);
  vi.mocked(studentApi.withdrawEnrollment).mockImplementation(async () => {
    rows = [active];
    return { ...pending, status: "WITHDRAWN" };
  });
  show();
  expect(await screen.findByRole("link", { name: "进入课程 已加入课程" })).toHaveAttribute("href", "/courses/active-course");
  expect(await screen.findByText("待审核课程")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /进入课程 待审核课程/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "撤回申请" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "确认撤回" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "确认撤回" }));
  expect(await screen.findByText("暂无待审核申请")).toBeInTheDocument();
  expect(studentApi.withdrawEnrollment).toHaveBeenCalledWith("en-pending", "2");
  expect(studentApi.dropCheck).not.toHaveBeenCalled();
});

it("已加入课程允许学生自行退出并从课程列表移除", async () => {
  vi.mocked(studentApi.enrollment).mockResolvedValue({ ...active, row_version: "9" });
  vi.mocked(studentApi.dropCheck).mockResolvedValue({ allowed: true, blockers: [] });
  vi.mocked(studentApi.dropEnrollment).mockImplementation(async () => {
    rows = [pending];
    return { ...active, status: "DROPPED" };
  });
  show();
  fireEvent.click(await screen.findByRole("button", { name: "退出课程" }));
  fireEvent.change(await screen.findByLabelText("退出原因"), { target: { value: "选课调整" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "确认退出" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "确认退出" }));
  expect(await screen.findByText("暂无进行中的课程")).toBeInTheDocument();
  expect(studentApi.dropEnrollment).toHaveBeenCalledWith("en-active", { reason: "选课调整" }, "9");
  expect(screen.queryByRole("link", { name: "进入课程 已加入课程" })).not.toBeInTheDocument();
});
