import { act, render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ToastProvider, useToast } from "./toast";
import { Button } from "./controls";
import { Icon } from "./icons";
import { EmptyState, ErrorState, LoadingState, RequestStateView } from "./states";
import { Metric, Panel, StatusBadge } from "./primitives";

function ToastProbe() {
  const toast = useToast();
  return <Button onClick={() => toast.notify("已保存")}>保存</Button>;
}

describe("ui 组件", () => {
  it("ToastProvider 显示并隐藏提示", () => {
    vi.useFakeTimers();
    render(<ToastProvider><ToastProbe /></ToastProvider>);
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(screen.getByText("已保存")).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.queryByText("已保存")).not.toBeInTheDocument();
    vi.useRealTimers();
  });

  it("StatusBadge 始终携带文本", () => {
    render(<StatusBadge tone="good">进行中</StatusBadge>);
    expect(screen.getByText("进行中")).toBeInTheDocument();
  });

  it("Metric 渲染数值与说明", () => {
    render(<Metric label="待评审" value="28" sub="较昨日减少 6 份" icon="file-check" />);
    expect(screen.getByText("待评审")).toBeInTheDocument();
    expect(screen.getByText("28")).toBeInTheDocument();
    expect(screen.getByText("较昨日减少 6 份")).toBeInTheDocument();
  });

  it("Panel 展示标题与操作", () => {
    render(<Panel title={<h2>任务日历</h2>} actions={<button type="button">导出</button>}>内容</Panel>);
    expect(screen.getByText("任务日历")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "导出" })).toBeInTheDocument();
  });

  it("RequestStateView 按加载-错误-空-内容切换", () => {
    const { rerender } = render(
      <RequestStateView loading error={null} empty={false} emptyState={<span>空数据</span>}>
        <span>正文</span>
      </RequestStateView>,
    );
    expect(screen.getByRole("status")).toBeInTheDocument();

    rerender(
      <RequestStateView loading={false} error={{ code: "X", message: "加载失败" }} empty={false} emptyState={null} onRetry={() => undefined}>
        <span>正文</span>
      </RequestStateView>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("加载失败");
    expect(screen.getAllByRole("button", { name: "重试" }).length).toBeGreaterThan(0);

    rerender(
      <RequestStateView loading={false} error={null} empty emptyState={<span>空数据</span>}>
        <span>正文</span>
      </RequestStateView>,
    );
    expect(screen.getByText("空数据")).toBeInTheDocument();

    rerender(
      <RequestStateView loading={false} error={null} empty={false} emptyState={null}>
        <span>正文</span>
      </RequestStateView>,
    );
    expect(screen.getByText("正文")).toBeInTheDocument();
  });

  it("ErrorState 展示错误码与 trace", () => {
    render(<ErrorState error={{ code: "ROW_VERSION_CONFLICT", message: "已被他人修改", trace_id: "abc123" }} />);
    expect(screen.getByText("错误码 ROW_VERSION_CONFLICT")).toBeInTheDocument();
    expect(screen.getByText(/abc123/)).toBeInTheDocument();
  });

  it("EmptyState 提供下一步动作", () => {
    render(<EmptyState title="还没有检查点" hint="运行后保存第一个检查点" action={<button type="button">保存检查点</button>} />);
    expect(screen.getByRole("button", { name: "保存检查点" })).toBeInTheDocument();
  });

  it("LoadingState 带 role=status", () => {
    render(<LoadingState label="加载课程" />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", "加载课程");
  });

  it("Icon 渲染 SVG", () => {
    const { container } = render(<Icon name="layers" />);
    expect(container.querySelector("svg")).not.toBeNull();
  });
});
