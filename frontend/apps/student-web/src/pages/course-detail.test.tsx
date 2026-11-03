import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { studentApi, taskApi } from "@edu/api-client";
import type { Course, Enrollment } from "@edu/api-client";
import { ApiError } from "@edu/auth-client";
import { keys } from "@edu/query-keys";
import { ToastProvider } from "@edu/ui";
import { CourseDetail } from "./course-detail";

vi.mock("@edu/api-client", () => ({
  studentApi: { courseDetail: vi.fn(), myEnrollments: vi.fn(), courseChapters: vi.fn(), courseMaterials: vi.fn(),
    courseAnnouncements: vi.fn(), courseCalendarEvents: vi.fn(), enrollment: vi.fn(), dropCheck: vi.fn(), dropEnrollment: vi.fn() },
  taskApi: { list: vi.fn() }, fileApi: { createDownloadGrant: vi.fn() },
}));
vi.mock("@/components/course-discussion", () => ({ CourseDiscussion: () => null }));
vi.mock("@/components/course-agent", () => ({ CourseAgent: () => null }));

const course: Course = { public_id: "course-1", code: "CS101", title: "编程基础", status: "PUBLISHED",
  enrollment_mode: "OPEN", capacity: 30, active_enrollment_count: 1, row_version: "1" };
const enrollment = { public_id: "en-1", course_id: "course-1", course_title: "编程基础", status: "ACTIVE", row_version: "1" } as Enrollment;
const empty = { rows: [], page: 1, pageSize: 100, total: 0 };
let client: QueryClient;
beforeEach(() => {
  vi.resetAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  vi.mocked(studentApi.myEnrollments).mockResolvedValue({ ...empty, rows: [enrollment], total: 1 });
  vi.mocked(studentApi.courseChapters).mockResolvedValue(empty);
  vi.mocked(studentApi.courseMaterials).mockResolvedValue(empty);
  vi.mocked(studentApi.courseAnnouncements).mockResolvedValue(empty);
  vi.mocked(studentApi.courseCalendarEvents).mockResolvedValue(empty);
  vi.mocked(taskApi.list).mockResolvedValue(empty);
});
afterEach(() => { cleanup(); client.clear(); });
function show() {
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/course-1"]}>
    <Routes><Route path="/courses/:courseId" element={<CourseDetail />} /><Route path="/courses" element={<p>我的课程列表</p>} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);
}

it("待审核或退出后手动访问课程时阻止加载内容，即使本地曾缓存课程", async () => {
  client.setQueryData(keys.course("course-1"), course);
  vi.mocked(studentApi.courseDetail).mockRejectedValue(new ApiError({ status: 403, url: "/courses/course-1", method: "GET",
    kind: "forbidden", payload: { code: "ACTIVE_ENROLLMENT_REQUIRED", message: "需要有效选课" } }));
  show();
  expect(screen.queryByRole("heading", { name: "课程信息" })).not.toBeInTheDocument();
  expect(await screen.findByText("暂时无法进入课程")).toBeInTheDocument();
  expect(studentApi.courseChapters).not.toHaveBeenCalled();
  expect(studentApi.courseMaterials).not.toHaveBeenCalled();
  expect(studentApi.courseAnnouncements).not.toHaveBeenCalled();
  expect(studentApi.courseCalendarEvents).not.toHaveBeenCalled();
  expect(taskApi.list).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("link", { name: "返回我的课程" }));
  expect(await screen.findByText("我的课程列表")).toBeInTheDocument();
});

it("课程详情中确认退出后返回课程列表", async () => {
  vi.mocked(studentApi.courseDetail).mockResolvedValue(course);
  vi.mocked(studentApi.enrollment).mockResolvedValue({ ...enrollment, row_version: "4" });
  vi.mocked(studentApi.dropCheck).mockResolvedValue({ allowed: true, blockers: [] });
  vi.mocked(studentApi.dropEnrollment).mockResolvedValue({ ...enrollment, status: "DROPPED" });
  show();
  fireEvent.click(await screen.findByRole("button", { name: "退出课程" }));
  fireEvent.change(await screen.findByLabelText("退出原因"), { target: { value: "选课调整" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "确认退出" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "确认退出" }));
  expect(await screen.findByText("我的课程列表")).toBeInTheDocument();
  expect(studentApi.dropEnrollment).toHaveBeenCalledWith("en-1", { reason: "选课调整" }, "4");
});
