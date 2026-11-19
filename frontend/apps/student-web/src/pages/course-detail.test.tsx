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
vi.mock("@/components/course-discussion", () => ({ CourseDiscussion: ({ courseId }: { courseId: string }) => <h2>课程问答内容 {courseId}</h2> }));
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
afterEach(() => { cleanup(); client.clear(); vi.restoreAllMocks(); Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView"); });
function show(path = "/courses/course-1") {
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={[path]}>
    <Routes><Route path="/courses/:courseId/chapters/:chapterId" element={<CourseDetail />} /><Route path="/courses/:courseId" element={<CourseDetail />} /><Route path="/courses/:courseId/questions" element={<CourseDetail discussionPage />} /><Route path="/courses" element={<p>我的课程列表</p>} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);
}

it("右侧滚动到章节时同步左侧高亮，向上滚动时也恢复对应章节", async () => {
  vi.mocked(studentApi.courseDetail).mockResolvedValue(course);
  vi.mocked(studentApi.courseChapters).mockResolvedValue({ ...empty, total: 3, rows:
    [1, 2, 3].map((index) => ({ public_id: `chapter-${index}`, course_id: "course-1", title: `第${index}章`, description: null, sort_order: index, status: "PUBLISHED", row_version: "1" })) });
  let scroll = 0;
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    const index = Number(this.id.match(/^course-chapter-chapter-(\d)$/)?.[1]);
    return { top: index ? 200 + (index - 1) * 400 - scroll : 0, bottom: 0, left: 0, right: 0,
      width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}) };
  });
  show();
  const first = await screen.findByRole("button", { name: /第1章/ });
  await waitFor(() => expect(first).toHaveAttribute("aria-current", "location"));
  scroll = 610;
  fireEvent.scroll(window);
  await waitFor(() => expect(screen.getByRole("button", { name: /第2章/ })).toHaveAttribute("aria-current", "location"));
  scroll = 1010;
  fireEvent.scroll(window);
  await waitFor(() => expect(screen.getByRole("button", { name: /第3章/ })).toHaveAttribute("aria-current", "location"));
  scroll = 210;
  fireEvent.scroll(window);
  await waitFor(() => expect(first).toHaveAttribute("aria-current", "location"));
});

it("三个章节后追加第四项问答入口，问答独立展示并能进入章节独立页", async () => {
  vi.mocked(studentApi.courseDetail).mockResolvedValue(course);
  vi.mocked(studentApi.courseChapters).mockResolvedValue({ ...empty, total: 3, rows:
    [1, 2, 3].map((index) => ({ public_id: `chapter-${index}`, course_id: "course-1", title: `第${index}章`, description: null, sort_order: index, status: "PUBLISHED", row_version: "1" })) });
  const scrollIntoView = vi.fn();
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scrollIntoView });
  show();
  const entry = await screen.findByRole("link", { name: /4.*课程问答/ });
  expect(screen.queryByRole("heading", { name: /课程问答内容/ })).not.toBeInTheDocument();
  fireEvent.click(entry);
  expect(await screen.findByRole("heading", { name: "课程问答内容 course-1" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /4.*课程问答/ })).toHaveAttribute("aria-current", "page");
  expect(screen.queryByRole("heading", { name: "课程日历" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /第3章/ }));
  expect(await screen.findByRole("heading", { name: "第3章" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "课程日历" })).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "第1章" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "返回课程介绍" })).toHaveAttribute("href", "/courses/course-1");
});

it.each(["auto", "visible"])("切换章节时回到新章节的开头（overflow-y: %s）", async (overflowY) => {
  vi.mocked(studentApi.courseDetail).mockResolvedValue(course);
  vi.mocked(studentApi.courseChapters).mockResolvedValue({ ...empty, total: 2, rows:
    [1, 2].map((index) => ({ public_id: `chapter-${index}`, course_id: "course-1", title: `第${index}章`, description: null, sort_order: index, status: "PUBLISHED", row_version: "1" })) });
  const scrollIntoView = vi.fn();
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scrollIntoView });

  show("/courses/course-1/chapters/chapter-1");
  await screen.findByRole("heading", { name: "第1章" });
  const content = screen.getByRole("region", { name: "课程内容" });
  content.style.overflowY = overflowY;
  content.scrollTop = 750;
  scrollIntoView.mockClear();

  fireEvent.click(screen.getByRole("button", { name: /第2章/ }));
  expect(await screen.findByRole("heading", { name: "第2章" })).toBeInTheDocument();
  if (overflowY === "auto") {
    expect(content.scrollTop).toBe(0);
    expect(scrollIntoView).not.toHaveBeenCalled();
  } else {
    expect(scrollIntoView).toHaveBeenCalledExactlyOnceWith({ behavior: "instant", block: "start" });
    expect(scrollIntoView.mock.contexts[0]).toBe(content);
  }
});

it("零章节时问答可直接返回课程介绍，进入问答不加载日历", async () => {
  vi.mocked(studentApi.courseDetail).mockResolvedValue(course);
  show("/courses/course-1/questions");
  expect(await screen.findByRole("link", { name: /1.*课程问答/ })).toHaveAttribute("aria-current", "page");
  expect(await screen.findByRole("heading", { name: "课程问答内容 course-1" })).toBeInTheDocument();
  expect(studentApi.courseCalendarEvents).not.toHaveBeenCalled();
  const back = screen.getByRole("link", { name: "返回课程介绍" });
  expect(back).toHaveAttribute("href", "/courses/course-1");
  fireEvent.click(back);
  expect(await screen.findByRole("heading", { name: "课程信息" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "课程问答内容 course-1" })).not.toBeInTheDocument();
});

it("无课程权限时问答页面不挂载问答内容", async () => {
  vi.mocked(studentApi.courseDetail).mockRejectedValue(new ApiError({ status: 403, url: "/courses/course-1", method: "GET",
    kind: "forbidden", payload: { code: "ACTIVE_ENROLLMENT_REQUIRED", message: "需要有效选课" } }));
  show("/courses/course-1/questions");
  expect(await screen.findByText("暂时无法进入课程")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: /课程问答内容/ })).not.toBeInTheDocument();
});

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

it("在自然页面滚动时使用视口追踪活动章节", async () => {
  vi.mocked(studentApi.courseDetail).mockResolvedValue(course);
  vi.mocked(studentApi.courseChapters).mockResolvedValue({ ...empty, total: 3, rows:
    [1, 2, 3].map((index) => ({ public_id: `chapter-${index}`, course_id: "course-1", title: `第${index}章`, description: null, sort_order: index, status: "PUBLISHED", row_version: "1" })) });
  show();
  await screen.findByRole("heading", { name: "第2章" });
  const content = screen.getByRole("region", { name: "课程内容" });
  content.style.overflowY = "visible";
  vi.spyOn(content, "getBoundingClientRect").mockReturnValue({ top: -1500 } as DOMRect);
  for (const [index, top] of [[1, -1200], [2, -20], [3, 700]]) {
    vi.spyOn(document.getElementById(`course-chapter-chapter-${index}`)!, "getBoundingClientRect").mockReturnValue({ top } as DOMRect);
  }
  fireEvent.scroll(window);
  await waitFor(() => expect(screen.getByRole("button", { name: /第2章/ })).toHaveAttribute("aria-current", "location"));
});
