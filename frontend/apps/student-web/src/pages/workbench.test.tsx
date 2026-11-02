import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { reportApi, taskApi, workspaceApi } from "@edu/api-client";
import { Workbench } from "./workbench";

vi.mock("@edu/api-client", () => ({
  reportApi: { draft: vi.fn(), saveDraft: vi.fn(), submitReport: vi.fn() },
  taskApi: { detail: vi.fn() },
  workspaceApi: { workbench: vi.fn(), checkpoints: vi.fn(), executionRuns: vi.fn(), captureSnapshot: vi.fn(), createExecutionRun: vi.fn(), createCheckpoint: vi.fn() },
}));

const draft = { public_id: "draft-1", task_id: "task-1", body_markdown: "original", row_version: "1" };

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/experiments/task-1/workbench"]}>
    <Routes><Route path="/experiments/:taskId/workbench" element={<Workbench />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);
  return client;
}

describe("workbench regression", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.setItem("edu.workspace.task-1", JSON.stringify({ session_id: "session-1", token: "token", capabilities: { webide: true } }));
    vi.mocked(taskApi.detail).mockResolvedValue({ public_id: "task-1", status: "REPORT_DRAFT", allowed_actions: [], blockers: [] } as never);
    vi.mocked(workspaceApi.workbench).mockResolvedValue({ chapters: [], tests: [], template_caps: { webide: true } } as never);
    vi.mocked(workspaceApi.checkpoints).mockResolvedValue({ rows: [] } as never);
    vi.mocked(workspaceApi.executionRuns).mockResolvedValue({ rows: [] } as never);
    vi.mocked(reportApi.draft).mockResolvedValue(draft as never);
    vi.mocked(reportApi.saveDraft).mockResolvedValue({ data: { ...draft, row_version: "2" } } as never);
  });

  it("queues overlapping saves and uses the version returned by the first save", async () => {
    let resolveFirst!: (value: never) => void;
    vi.mocked(reportApi.saveDraft)
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve; }))
      .mockResolvedValue({ data: { ...draft, row_version: "3" } } as never);
    const client = mount();
    fireEvent.click(await screen.findByRole("tab", { name: "实验报告" }));
    const editor = screen.getByRole("textbox", { name: "实验报告编辑器" });
    await waitFor(() => expect(editor).toHaveTextContent("original"));
    editor.innerHTML = "<p>first</p>";
    fireEvent.input(editor);
    fireEvent.click(screen.getByRole("button", { name: "保存报告" }));
    await waitFor(() => expect(reportApi.saveDraft).toHaveBeenCalledTimes(1));
    editor.innerHTML = "<p>second</p>";
    fireEvent.input(editor);
    fireEvent.click(screen.getByRole("button", { name: "保存报告" }));
    expect(reportApi.saveDraft).toHaveBeenCalledTimes(1);
    await act(async () => resolveFirst({ data: { ...draft, row_version: "2" } } as never));
    await waitFor(() => expect(reportApi.saveDraft).toHaveBeenCalledTimes(2));
    expect(vi.mocked(reportApi.saveDraft).mock.calls.map(call => call[2])).toEqual(["1", "2"]);
    expect(vi.mocked(reportApi.saveDraft).mock.calls[1]?.[1].body_markdown).toBe("second");
    client.clear();
  });

  it("opens the real workspace editor instead of a mock resolver file", async () => {
    const client = mount();
    fireEvent.click(await screen.findByRole("tab", { name: "文件编辑" }));
    expect(screen.getByTitle("实验文件编辑器")).toHaveAttribute("src", "/workspace/session-1/webide/");
    expect(screen.queryByText("/etc/resolv.conf")).not.toBeInTheDocument();
    client.clear();
  });

  it("does not describe a failed execution as never run", async () => {
    vi.mocked(workspaceApi.executionRuns).mockResolvedValue({ rows: [{ public_id: "run-1", status: "FAILED", error_code: "RUNTIME_ALGORITHM_FAILED" }] } as never);
    const client = mount();
    expect(await screen.findByText(/测试失败 · RUNTIME_ALGORITHM_FAILED/)).toBeInTheDocument();
    expect(screen.queryByText(/尚未运行/)).not.toBeInTheDocument();
    client.clear();
  });

  it("waits for the editor snapshot and judges that exact snapshot", async () => {
    vi.mocked(workspaceApi.workbench).mockResolvedValue({ chapters: [], tests: [], tests_available: true } as never);
    let captured!: (value: never) => void;
    vi.mocked(workspaceApi.captureSnapshot).mockImplementationOnce(() => new Promise(resolve => { captured = resolve; }));
    vi.mocked(workspaceApi.createExecutionRun).mockResolvedValue({ public_id: "run-new", status: "QUEUED" } as never);
    const client = mount();
    const run = await screen.findByRole("button", { name: "运行测试" });
    await waitFor(() => expect(run).toBeEnabled());
    fireEvent.click(run);
    await waitFor(() => expect(workspaceApi.captureSnapshot).toHaveBeenCalledWith("task-1", "token"));
    expect(workspaceApi.createExecutionRun).not.toHaveBeenCalled();
    await act(async () => captured({ public_id: "job-new", status: "PASSED", result_snapshot_id: "snapshot-new" } as never));
    await waitFor(() => expect(workspaceApi.createExecutionRun).toHaveBeenCalledWith("task-1", { snapshot_id: "snapshot-new", test_keys: undefined }, "token"));
    client.clear();
  });

  it("does not judge an older snapshot when capture fails", async () => {
    vi.mocked(workspaceApi.workbench).mockResolvedValue({ chapters: [], tests: [{ name: "输入输出检查" }] } as never);
    vi.mocked(workspaceApi.captureSnapshot).mockRejectedValueOnce(new Error("快照捕获失败"));
    const client = mount();
    fireEvent.click(await screen.findByRole("button", { name: "运行测试" }));
    expect(await screen.findByText("快照捕获失败")).toBeInTheDocument();
    expect(workspaceApi.createExecutionRun).not.toHaveBeenCalled();
    client.clear();
  });

  it("captures the edited code before saving a named checkpoint", async () => {
    vi.mocked(workspaceApi.captureSnapshot).mockResolvedValueOnce({ status: "PASSED", result_snapshot_id: "snapshot-new" } as never);
    vi.mocked(workspaceApi.createCheckpoint).mockResolvedValueOnce({ public_id: "cp-new", label: "修正后" } as never);
    const client = mount();
    fireEvent.click(await screen.findByRole("button", { name: "保存检查点" }));
    fireEvent.change(screen.getByLabelText("检查点名称"), { target: { value: "修正后" } });
    fireEvent.click(screen.getAllByRole("button", { name: "保存检查点" })[1]!);
    await waitFor(() => expect(workspaceApi.captureSnapshot).toHaveBeenCalled());
    await waitFor(() => expect(workspaceApi.createCheckpoint).toHaveBeenCalled());
    expect(vi.mocked(workspaceApi.captureSnapshot).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(workspaceApi.createCheckpoint).mock.invocationCallOrder[0]!);
    client.clear();
  });

  it("saves the report against the latest snapshot before submitting", async () => {
    let saved!: (value: never) => void;
    vi.mocked(reportApi.submitReport).mockResolvedValueOnce({} as never);
    const client = mount();
    await waitFor(() => expect(screen.getByRole("textbox", { name: "实验报告编辑器", hidden: true })).toHaveTextContent("original"));
    fireEvent.click(screen.getByRole("button", { name: "提交报告" }));
    const confirm = await screen.findByRole("button", { name: "确认提交" }, { timeout: 4000 });
    vi.mocked(reportApi.saveDraft).mockClear().mockImplementationOnce(() => new Promise(resolve => { saved = resolve; }));
    fireEvent.click(confirm);
    await waitFor(() => expect(reportApi.saveDraft).toHaveBeenCalled());
    expect(reportApi.submitReport).not.toHaveBeenCalled();
    await act(async () => saved({ data: { ...draft, row_version: "2" } } as never));
    await waitFor(() => expect(reportApi.submitReport).toHaveBeenCalled());
    client.clear();
  });
});
