import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import Console from "./Console";

vi.mock("../app/session", () => ({ useSession: () => ({ me: { display_name: "管理" } }) }));
vi.mock("../lib/recent-auth", () => ({ useRecentAuthGuard: () => ({ intercept: () => false }) }));
vi.mock("@edu/auth-client", async (original) => {
  const actual = await original<typeof import("@edu/auth-client")>();
  return { ...actual, request: vi.fn(async (path: string) => {
    let data: unknown = [];
    if (path === "/platform/users") data = [{ public_id: "student-1", display_name: "学生甲", account_status: "ACTIVE" }];
    if (path === "/platform/courses") data = [{ public_id: "course-1", title: "已开设教学班", code: "TEACH-A", status: "PUBLISHED" }];
    if (path === "/platform/administrative-classes") data = [{ public_id: "class-1", name: "班级甲", code: "CLASS-A", status: "ACTIVE" }];
    if (path.endsWith("/members")) data = { class: { name: "班级甲" }, members: [{ public_id: "m-1", student_id: "student-1", student_name: "学生甲" }] };
    if (path.endsWith("/overview")) data = { runtime: { status: "HEALTHY" } };
    return { data, meta: { total: Array.isArray(data) ? data.length : 0 } };
  }) };
});
afterEach(cleanup);
function show(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Console /></MemoryRouter></QueryClientProvider>);
  return client;
}
it("opens health and usage tabs from overview and supports the browser URL", async () => {
  const client = show("/");
  fireEvent.click(await screen.findByRole("button", { name: "全部 →" }));
  expect(await screen.findByRole("button", { name: "健康状态" })).toHaveClass("active");
  fireEvent.click(screen.getByRole("button", { name: "资源占用" }));
  expect(await screen.findByRole("heading", { name: "实验实例 · 0 个" })).toBeInTheDocument();
  client.clear();
});
it("shows classes first then the selected class members", async () => {
  const client = show("/students");
  expect(await screen.findByText("班级甲")).toBeInTheDocument();
  expect(screen.queryByText("学生甲")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("班级甲").closest("tr")!.querySelector("button")!);
  expect(await screen.findByText("学生甲")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "返回班级列表" }));
  expect(await screen.findByText("已开设教学班")).toBeInTheDocument();
  client.clear();
});
