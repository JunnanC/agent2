import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { meApi } from "@edu/api-client";
import type { NotificationItem } from "@edu/api-client";
import { ToastProvider } from "@edu/ui";
import { Notifications } from "./notifications";

vi.mock("@edu/api-client", () => ({ meApi: { notifications: vi.fn(), markNotificationRead: vi.fn() } }));
const notification = {
  id: "notice-1", public_id: "notice-1", title: "课程申请已通过", body: "教师已同意你加入编程基础课程。", read: false,
  kind: "enrollment.activated", row_version: 1, created_at: "2026-11-03T00:00:00Z",
  links: [{ course_id: "course-1" }],
} satisfies NotificationItem;
let client: QueryClient;
beforeEach(() => {
  vi.resetAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
});
afterEach(() => { cleanup(); client.clear(); });
function CurrentPage() { return <output aria-label="当前页面">{useLocation().pathname}</output>; }
function show(item: NotificationItem) {
  let current = { ...item, links: item.links ?? [] };
  vi.mocked(meApi.notifications).mockImplementation(async () => ({ rows: [current], page: 1, pageSize: 50, total: 1 }));
  vi.mocked(meApi.markNotificationRead).mockImplementation(async () => {
    current = { ...current, read: true, row_version: (current.row_version ?? 0) + 1 };
    return current;
  });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/notifications"]}>
    <Notifications /><CurrentPage />
  </MemoryRouter></ToastProvider></QueryClientProvider>);
}

it("查看课程通知详情先显示正文，留在通知页面", async () => {
  show(notification);
  fireEvent.click(await screen.findByRole("button", { name: "查看详情" }));
  const dialog = screen.getByRole("dialog", { name: "课程申请已通过" });
  expect(within(dialog).getByText(notification.body)).toBeInTheDocument();
  expect(screen.getByLabelText("当前页面")).toHaveTextContent("/notifications");
  expect(within(dialog).getByRole("link", { name: "查看课程" })).toHaveAttribute("href", "/courses/course-1");
  fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByLabelText("当前页面")).toHaveTextContent("/notifications");
});

it("实验通知详情提供明确的实验任务入口", async () => {
  show({ ...notification, title: "实验评审完成", body: "你的实验报告已完成评审。", links: [{ task_id: "task-1", course_id: "course-1" }] });
  fireEvent.click(await screen.findByRole("button", { name: "查看详情" }));
  const dialog = screen.getByRole("dialog", { name: "实验评审完成" });
  expect(within(dialog).getByText("你的实验报告已完成评审。")).toBeInTheDocument();
  expect(within(dialog).getByRole("link", { name: "查看实验任务" })).toHaveAttribute("href", "/experiments/task-1");
  expect(within(dialog).queryByRole("link", { name: "查看课程" })).not.toBeInTheDocument();
});

it("没有关联课程的系统通知也能查看完整正文", async () => {
  show({ ...notification, title: "平台维护通知", body: "今晚 22:00 起进行维护。\n请提前保存实验内容。", links: [] });
  fireEvent.click(await screen.findByRole("button", { name: "查看详情" }));
  const dialog = screen.getByRole("dialog", { name: "平台维护通知" });
  expect(within(dialog).getByText(/今晚 22:00 起进行维护/)).toHaveTextContent("请提前保存实验内容。");
  expect(within(dialog).queryByRole("link")).not.toBeInTheDocument();
});

it("查看未读通知自动已读，未读筛选中仍保留详情，重复打开不再请求", async () => {
  show(notification);
  await screen.findByRole("button", { name: "查看详情" });
  fireEvent.click(screen.getByRole("button", { name: "未读" }));
  fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
  await screen.findByText("全部已读");
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText(notification.body)).toBeInTheDocument();
  expect(meApi.markNotificationRead).toHaveBeenCalledWith("notice-1", 1);
  fireEvent.click(within(dialog).getByRole("button", { name: "关闭" }));
  fireEvent.click(screen.getByRole("button", { name: "全部" }));
  fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
  expect(meApi.markNotificationRead).toHaveBeenCalledTimes(1);
});

it("已读通知可以查看正文而不重复标记", async () => {
  show({ ...notification, read: true });
  fireEvent.click(await screen.findByRole("button", { name: "查看详情" }));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(meApi.markNotificationRead).not.toHaveBeenCalled();
});

it("自动标记失败仍可阅读正文并在详情重试", async () => {
  show(notification);
  vi.mocked(meApi.markNotificationRead).mockRejectedValueOnce(new Error("网络中断"));
  fireEvent.click(await screen.findByRole("button", { name: "查看详情" }));
  await screen.findByText("自动标记已读失败，请点击标记已读重试");
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText(notification.body)).toBeInTheDocument();
  const retry = within(dialog).getByRole("button", { name: "标记已读" });
  await waitFor(() => expect(retry).toBeEnabled());
  fireEvent.click(retry);
  await screen.findByText("全部已读");
  expect(meApi.markNotificationRead).toHaveBeenCalledTimes(2);
});
