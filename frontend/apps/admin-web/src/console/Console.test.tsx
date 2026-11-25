import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { request } from "@edu/auth-client";
import Console from "./Console";

vi.mock("../app/session", () => ({ useSession: () => ({ me: { display_name: "管理" } }) }));
vi.mock("../lib/recent-auth", () => ({ useRecentAuthGuard: () => ({ intercept: () => false }) }));
vi.mock("@edu/auth-client", async (original) => {
  const actual = await original<typeof import("@edu/auth-client")>();
  return { ...actual, request: vi.fn(async (path: string) => {
    let data: unknown = [];
    if (path === "/platform/users") data = [{ public_id: "student-1", display_name: "学生甲", account_status: "ACTIVE" }];
    if (path === "/platform/courses") data = [
      { public_id: "course-1", title: "数据结构", code: "CS-A", status: "CLOSED" },
      { public_id: "course-2", title: "高级语言程序设计", code: "CS-B", status: "PUBLISHED" },
      { public_id: "course-3", title: "操作系统", code: "CS-C", status: "DRAFT" },
      ...["体育1", "大学物理实验", "高等数学1-1", "线性代数", "大学英语(一)"].map((title, index) => ({
        public_id: `general-${index}`, title, code: `GE-${index}`, status: "CLOSED",
      })),
    ];
    if (path === "/platform/administrative-classes") data = [{ public_id: "class-1", name: "班级甲", code: "CLASS-A", status: "ACTIVE" }];
    if (path === "/platform/resource-profiles") data = [{ public_id: "profile-1", code: "STD-512M", name: "标准 0.5 核 / 512 MB", runtime_type: "CONTAINER", status: "ACTIVE", cpu_millicores: 500, memory_mb: 512, disk_gb: 2, network_mode: "DENY_ALL", row_version: 3 }];
    if (path.endsWith("/members")) data = { class: { name: "班级甲" }, members: [{ public_id: "m-1", student_id: "student-1", student_name: "学生甲" }] };
    if (path.endsWith("/overview")) data = { runtime: { status: "HEALTHY" } };
    return { data, meta: { total: Array.isArray(data) ? data.length : 0 } };
  }) };
});
afterEach(cleanup);
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = vi.fn();
  HTMLDialogElement.prototype.close = vi.fn();
});
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
  expect(screen.getByRole("button", { name: "资源占用" })).toHaveClass("active");
  expect(screen.queryByText(/学生编辑不创建常驻实例/)).not.toBeInTheDocument();
  client.clear();
});
it("shows classes first then the selected class members", async () => {
  const client = show("/students");
  expect(await screen.findByText("班级甲")).toBeInTheDocument();
  expect(screen.queryByText("学生甲")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("班级甲").closest("tr")!.querySelector("button")!);
  expect(await screen.findByText("学生甲")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "返回班级列表" }));
  expect(await screen.findByText("数据结构")).toBeInTheDocument();
  expect(screen.getByText("高级语言程序设计")).toBeInTheDocument();
  for (const title of ["体育1", "大学物理实验", "高等数学1-1", "线性代数", "大学英语(一)", "操作系统"]) {
    expect(screen.queryByText(title)).not.toBeInTheDocument();
  }
  client.clear();
});

it("lets an administrator add and retire judge resource profiles", async () => {
  const client = show("/profiles");
  expect(await screen.findByText("标准 0.5 核 / 512 MB")).toBeInTheDocument();
  expect(screen.getByText("0.5 核 / 512 MB")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "新增规格" }));
  fireEvent.change(screen.getByLabelText("规格名称"), { target: { value: "加强 1 核 / 1 GB" } });
  fireEvent.change(screen.getByLabelText("规格编码"), { target: { value: "LARGE-1G" } });
  fireEvent.change(screen.getByLabelText("CPU（核）"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("内存（MB）"), { target: { value: "1024" } });
  fireEvent.change(screen.getByLabelText("磁盘（GB）"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("变更原因"), { target: { value: "补充大作业档位" } });
  fireEvent.click(screen.getByText("保存规格"));
  await waitFor(() =>
    expect(vi.mocked(request)).toHaveBeenCalledWith("/platform/resource-profiles", expect.objectContaining({
      method: "POST",
      body: expect.objectContaining({ code: "LARGE-1G", cpu_millicores: 1000, memory_mb: 1024, network_mode: "DENY_ALL" }),
    })),
  );

  fireEvent.click(screen.getByRole("button", { name: "停用" }));
  fireEvent.change(screen.getByLabelText("变更原因"), { target: { value: "下线该档位" } });
  fireEvent.click(screen.getByText("停用规格"));
  await waitFor(() =>
    expect(vi.mocked(request)).toHaveBeenCalledWith("/platform/resource-profiles/profile-1/retire", expect.objectContaining({
      method: "POST",
      ifMatch: 3,
      body: { reason: "下线该档位" },
    })),
  );
  client.clear();
});

it("折叠后只通过品牌按钮展开，不保留独立箭头", async () => {
  const client = show("/");
  for (let cycle = 0; cycle < 2; cycle++) {
    fireEvent.click(screen.getByRole("button", { name: "收起导航" }));
    expect(document.querySelector(".side-nav-shell")).toHaveClass("nav-collapsed");
    const brand = screen.getByRole("button", { name: "展开导航" });
    expect(brand).toHaveClass("brand-expand");
    expect(brand.querySelector("svg")).toBeInTheDocument();
    expect(brand).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(brand);
    expect(document.querySelector(".side-nav-shell")).not.toHaveClass("nav-collapsed");
    expect(screen.queryByRole("button", { name: "展开导航" })).not.toBeInTheDocument();
  }
  client.clear();
});
