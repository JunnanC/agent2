import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AppShell } from "./navigation";

afterEach(() => { cleanup(); localStorage.clear(); });
const props = { domainLabel: "student.localhost", nav: [{ label: "概览", path: "/", icon: "layers" as const }, { label: "我的课程", path: "/courses", icon: "book" as const }], activePath: "/", onNavigate: vi.fn(), avatar: { name: "学生", role: "学生" } };
it("折叠后保留导航与个人菜单，并记住状态", () => {
 const { container, unmount } = render(<AppShell {...props} navigationPosition="side" collapsible collapseStorageKey="test-sidebar">内容</AppShell>);
 fireEvent.click(screen.getByRole("button", { name: "收起导航" }));
 expect(container.querySelector(".nav-collapsed")).toBeInTheDocument();
 expect(screen.getByRole("button", { name: "展开导航" })).toHaveAttribute("aria-expanded", "false");
 expect(localStorage.getItem("test-sidebar")).toBe("true");
 expect(container.querySelector(".sidebar-toggle")).not.toBeInTheDocument();
 expect(screen.getByRole("button", { name: "展开导航" })).toHaveClass("brand-mark");
 expect(screen.getByRole("button", { name: "展开导航" }).querySelector("svg")).toBeInTheDocument();
 fireEvent.click(screen.getByRole("button", { name: "我的课程" }));
 expect(props.onNavigate).toHaveBeenCalledWith("/courses");
 fireEvent.click(screen.getByRole("button", { name: "打开个人菜单" }));
 expect(screen.getByRole("menu")).toBeInTheDocument();
 unmount();
 render(<AppShell {...props} navigationPosition="side" collapsible collapseStorageKey="test-sidebar">内容</AppShell>);
 fireEvent.click(screen.getByRole("button", { name: "展开导航" }));
 expect(localStorage.getItem("test-sidebar")).toBe("false");
});
it("默认导航不显示折叠按钮", () => {
 render(<AppShell {...props}>内容</AppShell>);
 expect(screen.queryByRole("button", { name: "收起导航" })).not.toBeInTheDocument();
});
