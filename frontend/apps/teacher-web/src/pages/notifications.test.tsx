import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { meApi } from "@edu/api-client";
import type { NotificationItem } from "@edu/api-client";
import { ToastProvider } from "@edu/ui";
import { Notifications } from "./notifications";

vi.mock("@edu/api-client", () => ({ meApi: { notifications: vi.fn(), markNotificationRead: vi.fn() } }));
const notice: NotificationItem = {
  id: "drop-1", public_id: "drop-1", title: "学生退课通知", kind: "enrollment.student_dropped",
  body: "学生：张同学。\n已退出课程：《程序设计》。\n退课原因：课程安排冲突。\n退课已生效，无需教师审批。",
  read: false, row_version: 3, created_at: "2026-11-04T00:00:00Z",
  links: [{ url: "/courses/course-1/enrollments", course_id: "course-1" }],
};
let client: QueryClient;
beforeEach(() => {
  vi.resetAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
});
afterEach(() => { cleanup(); client.clear(); });
function show(rows: NotificationItem[]) {
  vi.mocked(meApi.notifications).mockResolvedValue({ rows: rows.map((item) => ({ ...item, links: item.links ?? [] })), total: rows.length, page: 1, pageSize: 50 });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter>
    <Notifications />
  </MemoryRouter></ToastProvider></QueryClientProvider>);
}

it("展示学生退课正文、无需审批及选课管理入口", async () => {
  show([notice]);
  await screen.findByText("学生退课通知");
  expect(screen.getByText(/学生：张同学/)).toHaveTextContent("退课已生效，无需教师审批");
  expect(screen.getByText("1 条未读")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "查看选课管理" })).toHaveAttribute("href", "/courses/course-1/enrollments");
  expect(screen.queryByRole("button", { name: /同意|拒绝/ })).not.toBeInTheDocument();
});

it("实验通知使用发布页面入口", async () => {
  show([{ ...notice, id: "experiment-1", public_id: "experiment-1", title: "实验已结束",
    links: [{ url: "/courses/course-1/publishing", course_id: "course-1" }] }]);
  expect(await screen.findByRole("link", { name: "查看实验发布" })).toHaveAttribute("href", "/courses/course-1/publishing");
});

it("读取通知仅标记已读并刷新计数", async () => {
  show([notice]);
  vi.mocked(meApi.markNotificationRead).mockResolvedValue({});
  await screen.findByRole("button", { name: "标记已读" });
  vi.mocked(meApi.notifications).mockResolvedValue({ rows: [{ ...notice, links: notice.links ?? [], read: true, row_version: 4 }], total: 1, page: 1, pageSize: 50 });
  fireEvent.click(screen.getByRole("button", { name: "标记已读" }));
  await waitFor(() => expect(meApi.markNotificationRead).toHaveBeenCalledWith("drop-1", 3));
  expect(await screen.findByText("0 条未读")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "标记已读" })).not.toBeInTheDocument();
});

it("已读失败保留通知并提示错误", async () => {
  show([notice]);
  vi.mocked(meApi.markNotificationRead).mockRejectedValue(new Error("网络错误"));
  fireEvent.click(await screen.findByRole("button", { name: "标记已读" }));
  expect(await screen.findByText("网络错误")).toBeInTheDocument();
  expect(screen.getByText("1 条未读")).toBeInTheDocument();
  expect(screen.getByText("学生退课通知")).toBeInTheDocument();
});

it("无通知时显示空状态", async () => {
  show([]);
  expect(await screen.findByText("暂无通知")).toBeInTheDocument();
});
