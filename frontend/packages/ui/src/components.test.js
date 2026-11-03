import { jsx as _jsx } from "react/jsx-runtime";
import { act, render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ToastProvider, useToast } from "./toast";
import { Button } from "./controls";
import { Icon } from "./icons";
import { EmptyState, ErrorState, LoadingState, RequestStateView } from "./states";
import { Metric, Panel, StatusBadge } from "./primitives";
function ToastProbe() {
    const toast = useToast();
    return _jsx(Button, { onClick: () => toast.notify("已保存"), children: "\u4FDD\u5B58" });
}
describe("ui 组件", () => {
    it("ToastProvider 显示并隐藏提示", () => {
        vi.useFakeTimers();
        render(_jsx(ToastProvider, { children: _jsx(ToastProbe, {}) }));
        fireEvent.click(screen.getByRole("button", { name: "保存" }));
        expect(screen.getByText("已保存")).toBeInTheDocument();
        act(() => { vi.advanceTimersByTime(3000); });
        expect(screen.queryByText("已保存")).not.toBeInTheDocument();
        vi.useRealTimers();
    });
    it("StatusBadge 始终携带文本", () => {
        render(_jsx(StatusBadge, { tone: "good", children: "\u8FDB\u884C\u4E2D" }));
        expect(screen.getByText("进行中")).toBeInTheDocument();
    });
    it("Metric 渲染数值与说明", () => {
        render(_jsx(Metric, { label: "\u5F85\u8BC4\u5BA1", value: "28", sub: "\u8F83\u6628\u65E5\u51CF\u5C11 6 \u4EFD", icon: "file-check" }));
        expect(screen.getByText("待评审")).toBeInTheDocument();
        expect(screen.getByText("28")).toBeInTheDocument();
        expect(screen.getByText("较昨日减少 6 份")).toBeInTheDocument();
    });
    it("Panel 展示标题与操作", () => {
        render(_jsx(Panel, { title: _jsx("h2", { children: "\u4EFB\u52A1\u65E5\u5386" }), actions: _jsx("button", { type: "button", children: "\u5BFC\u51FA" }), children: "\u5185\u5BB9" }));
        expect(screen.getByText("任务日历")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "导出" })).toBeInTheDocument();
    });
    it("RequestStateView 按加载-错误-空-内容切换", () => {
        const { rerender } = render(_jsx(RequestStateView, { loading: true, error: null, empty: false, emptyState: _jsx("span", { children: "\u7A7A\u6570\u636E" }), children: _jsx("span", { children: "\u6B63\u6587" }) }));
        expect(screen.getByRole("status")).toBeInTheDocument();
        rerender(_jsx(RequestStateView, { loading: false, error: { code: "X", message: "加载失败" }, empty: false, emptyState: null, onRetry: () => undefined, children: _jsx("span", { children: "\u6B63\u6587" }) }));
        expect(screen.getByRole("alert")).toHaveTextContent("加载失败");
        expect(screen.getAllByRole("button", { name: "重试" }).length).toBeGreaterThan(0);
        rerender(_jsx(RequestStateView, { loading: false, error: null, empty: true, emptyState: _jsx("span", { children: "\u7A7A\u6570\u636E" }), children: _jsx("span", { children: "\u6B63\u6587" }) }));
        expect(screen.getByText("空数据")).toBeInTheDocument();
        rerender(_jsx(RequestStateView, { loading: false, error: null, empty: false, emptyState: null, children: _jsx("span", { children: "\u6B63\u6587" }) }));
        expect(screen.getByText("正文")).toBeInTheDocument();
    });
    it("ErrorState 展示错误码与 trace", () => {
        render(_jsx(ErrorState, { error: { code: "ROW_VERSION_CONFLICT", message: "已被他人修改", trace_id: "abc123" } }));
        expect(screen.getByText("错误码 ROW_VERSION_CONFLICT")).toBeInTheDocument();
        expect(screen.getByText(/abc123/)).toBeInTheDocument();
    });
    it("EmptyState 提供下一步动作", () => {
        render(_jsx(EmptyState, { title: "\u8FD8\u6CA1\u6709\u68C0\u67E5\u70B9", hint: "\u8FD0\u884C\u540E\u4FDD\u5B58\u7B2C\u4E00\u4E2A\u68C0\u67E5\u70B9", action: _jsx("button", { type: "button", children: "\u4FDD\u5B58\u68C0\u67E5\u70B9" }) }));
        expect(screen.getByRole("button", { name: "保存检查点" })).toBeInTheDocument();
    });
    it("LoadingState 带 role=status", () => {
        render(_jsx(LoadingState, { label: "\u52A0\u8F7D\u8BFE\u7A0B" }));
        expect(screen.getByRole("status")).toHaveAttribute("aria-label", "加载课程");
    });
    it("Icon 渲染 SVG", () => {
        const { container } = render(_jsx(Icon, { name: "layers" }));
        expect(container.querySelector("svg")).not.toBeNull();
    });
});
