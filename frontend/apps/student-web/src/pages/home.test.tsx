import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { studentApi, taskApi } from "@edu/api-client";
import type { Task } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Home } from "./home";

vi.mock("@edu/api-client", () => ({
  taskApi: { list: vi.fn() },
  studentApi: { myEnrollments: vi.fn(), dashboard: vi.fn() },
  assessmentApi: { get: vi.fn() },
}));

const now = new Date();
const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
const list = (rows: Task[]) => ({ rows, page: 1, pageSize: 50, total: rows.length });
function tasks(count: number, day = "10"): Task[] {
  return Array.from({ length: count }, (_, index) => ({
    public_id: `task-${day}-${index + 1}`, course_id: "course-1", publication_id: "pub-1",
    title: `${day}日任务${index + 1}`, status: "ASSIGNED", progress: 0,
    window_start: `${month}-${day}T12:00:00`, effective_deadline: `${month}-${day}T18:00:00`,
    allowed_actions: index === 8 ? ["enter"] : [], blockers: [], row_version: "1",
  }));
}

let client: QueryClient;
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(studentApi.myEnrollments).mockResolvedValue({ rows: [], page: 1, pageSize: 100, total: 0 });
  vi.mocked(studentApi.dashboard).mockResolvedValue({});
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});
afterEach(() => { cleanup(); client.clear(); });

function show(rows: Task[]) {
  vi.mocked(taskApi.list).mockResolvedValue(list(rows));
  render(<QueryClientProvider client={client}><MemoryRouter><Routes>
    <Route path="/" element={<Home />} />
    <Route path="/experiments/:id" element={<div>任务详情页面</div>} />
    <Route path="/experiments/:id/assessment" element={<div>轻量答题页面</div>} />
  </Routes></MemoryRouter></QueryClientProvider>);
}

const taskButtons = () => screen.getAllByRole("button", { name: /10日任务/ });

it("新实验从日历进入轻量答题，不进入旧工作台", async () => {
  show(tasks(1).map(task => ({ ...task, assessment_available: true, allowed_actions: ["enter"] })));
  fireEvent.click(await screen.findByRole("button", { name: /10日任务1/ }));
  expect(await screen.findByText("轻量答题页面")).toBeInTheDocument();
});

it("7 项任务分为 3、3、1 项，保留总数并禁用首尾翻页", async () => {
  show(tasks(7));
  await screen.findByRole("navigation", { name: "待完成任务分页" });
  expect(taskButtons()).toHaveLength(3);
  expect(screen.getByText(/7 项待办$/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "下一页" }));
  expect(taskButtons()).toHaveLength(3);
  expect(screen.getByRole("button", { name: /10日任务5/ })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /10日任务1\D/ })).not.toBeInTheDocument();
  expect(screen.getByText("第 2 / 3 页")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "下一页" }));
  expect(taskButtons()).toHaveLength(1);
  expect(screen.getByText("第 3 / 3 页")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "上一页" }));
  expect(screen.getByText("第 2 / 3 页")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /10日任务5/ }));
  expect(screen.getByText("任务详情页面")).toBeInTheDocument();
});

it("旧格式任务仍可查看详情但不再进入工作台", async () => {
  show(tasks(9));
  const next = await screen.findByRole("button", { name: "下一页" });
  fireEvent.click(next);
  fireEvent.click(next);
  fireEvent.click(screen.getByRole("button", { name: /10日任务9/ }));
  expect(screen.getByText("任务详情页面")).toBeInTheDocument();
});

it("日历跳过已完成任务，优先定位到最近的未完成日期", async () => {
  show([
    ...tasks(1, "10").map((task) => ({ ...task, status: "COMPLETED" as const, progress: 100 })),
    ...tasks(1, "11"),
  ]);
  expect(await screen.findByRole("button", { name: /11日任务1/ })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /10日任务1/ })).not.toBeInTheDocument();
});

it("切换日期及返回原日期均回到第一页，空日期显示空状态", async () => {
  show([...tasks(9), ...tasks(5, "11")]);
  fireEvent.click(await screen.findByRole("button", { name: "下一页" }));
  fireEvent.click(screen.getByRole("button", { name: /11 日.*5 项待办任务/ }));
  expect(screen.getByText("第 1 / 2 页")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /11日任务1/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /10 日.*9 项待办任务/ }));
  expect(screen.getByText("第 1 / 3 页")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /12 日.*无待办任务/ }));
  expect(screen.getByText("当天没有待办")).toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "待完成任务分页" })).not.toBeInTheDocument();
});

it("刷新后任务减少时回落到有效末页", async () => {
  show(tasks(9));
  const next = await screen.findByRole("button", { name: "下一页" });
  fireEvent.click(next);
  fireEvent.click(next);
  act(() => { client.setQueryData(keys.tasks({ scope: "my" }), list(tasks(4))); });
  await waitFor(() => expect(screen.getByText("第 2 / 2 页")).toBeInTheDocument());
  expect(taskButtons()).toHaveLength(1);
  expect(screen.getByRole("button", { name: /10日任务4/ })).toBeInTheDocument();
  act(() => { client.setQueryData(keys.tasks({ scope: "my" }), list(tasks(3))); });
  await waitFor(() => expect(taskButtons()).toHaveLength(3));
  expect(screen.queryByRole("navigation", { name: "待完成任务分页" })).not.toBeInTheDocument();
});

it.each([0, 1, 3])("%i 项任务不显示分页导航", async (count) => {
  show(tasks(count));
  if (count) await screen.findByRole("button", { name: /10日任务1/ });
  else await screen.findByText("暂无待办任务");
  expect(screen.queryByRole("navigation", { name: "待完成任务分页" })).not.toBeInTheDocument();
});
