import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { reportApi, taskApi, workspaceApi } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import { Workbench } from "./workbench";

vi.mock("@edu/api-client", () => ({
  reportApi: { draft: vi.fn(), saveDraft: vi.fn(), submitReport: vi.fn() },
  taskApi: { detail: vi.fn(), complete: vi.fn(), enter: vi.fn() },
  workspaceApi: { renewSession: vi.fn(), editorControl: vi.fn(), executionRun: vi.fn(), workbench: vi.fn(), checkpoints: vi.fn(), executionRuns: vi.fn(), captureSnapshot: vi.fn(), createExecutionRun: vi.fn(), createCheckpoint: vi.fn(), storageJob: vi.fn(), operation: vi.fn() },
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
  afterEach(() => vi.useRealTimers());
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(workspaceApi.editorControl).mockResolvedValue(undefined);
    vi.mocked(workspaceApi.captureSnapshot).mockResolvedValue({ status: "PASSED", result_snapshot_id: "snapshot-current" } as never);
    sessionStorage.setItem("edu.workspace.task-1", JSON.stringify({ session_id: "session-1", token: "token", capabilities: { webide: true } }));
    vi.mocked(taskApi.detail).mockResolvedValue({ public_id: "task-1", status: "REPORT_DRAFT", allowed_actions: [], blockers: [] } as never);
    vi.mocked(workspaceApi.workbench).mockResolvedValue({ chapters: [], tests: [], template_caps: { webide: true } } as never);
    vi.mocked(workspaceApi.checkpoints).mockResolvedValue({ rows: [] } as never);
    vi.mocked(workspaceApi.executionRuns).mockResolvedValue({ rows: [] } as never);
    vi.mocked(workspaceApi.storageJob).mockResolvedValue({ status: "PASSED", result_snapshot_id: "snapshot-switch" } as never);
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

  it("unblocks controls when initial storage finishes without requiring a reload", async () => {
    vi.useFakeTimers();
    vi.mocked(workspaceApi.workbench)
      .mockResolvedValueOnce({ workspace: { active_storage_job: { status: "RUNNING" } } } as never)
      .mockResolvedValue({ workspace: { active_storage_job: null } } as never);
    const client = mount();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    const save = screen.getByRole("button", { name: "保存代码" });
    expect(save).toBeDisabled();
    const editor = screen.getByTitle("实验文件编辑器");
    await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
    expect(save).toBeEnabled();
    expect(screen.getByTitle("实验文件编辑器")).toBe(editor);
    client.clear();
  });

  it("renews before expiry without remounting the editor or losing buffers", async () => {
    vi.useFakeTimers();
    const expires = new Date(Date.now() + 120_000).toISOString();
    sessionStorage.setItem("edu.workspace.task-1", JSON.stringify({ session_id: "session-1", token: "token", expires_at: expires, capabilities: { webide: true } }));
    vi.mocked(workspaceApi.renewSession).mockResolvedValue({ workspace_token: "renewed-token", expires_at: new Date(Date.now() + 900_000).toISOString() } as never);
    const client = mount();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    const editor = screen.getByTitle("实验文件编辑器");
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(workspaceApi.renewSession).toHaveBeenCalledWith("session-1", "token");
    expect(JSON.parse(sessionStorage.getItem("edu.workspace.task-1")!).token).toBe("renewed-token");
    expect(screen.getByTitle("实验文件编辑器")).toBe(editor);
    fireEvent.click(screen.getByRole("button", { name: "保存代码" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(workspaceApi.editorControl).toHaveBeenCalledWith("session-1", "save", "renewed-token");
    client.clear();
  });

  it("re-enters an expired session before mounting the editor with refreshed credentials", async () => {
    sessionStorage.setItem("edu.workspace.task-1", JSON.stringify({ session_id: "session-1", token: "expired", expires_at: new Date(Date.now() - 1000).toISOString(), capabilities: { webide: true } }));
    vi.mocked(taskApi.detail).mockResolvedValue({ public_id: "task-1", status: "IN_PROGRESS", allowed_actions: ["enter"], row_version: "4" } as never);
    let entered!: (value: never) => void;
    vi.mocked(taskApi.enter).mockImplementationOnce(() => new Promise(resolve => { entered = resolve; }));
    const client = mount();
    await waitFor(() => expect(taskApi.enter).toHaveBeenCalledWith("task-1", "4"));
    expect(screen.queryByTitle("实验文件编辑器")).not.toBeInTheDocument();
    await act(async () => entered({ session: { public_id: "session-1", workspace_token: "new-token", expires_at: new Date(Date.now() + 900_000).toISOString(), capabilities: { webide: true } } } as never));
    expect(await screen.findByTitle("实验文件编辑器")).toHaveAttribute("src", "/workspace/session-1/webide/");
    expect(JSON.parse(sessionStorage.getItem("edu.workspace.task-1")!).token).toBe("new-token");
    client.clear();
  });

  it("keeps the editor buffers and stops retrying when renewal fails", async () => {
    vi.useFakeTimers();
    sessionStorage.setItem("edu.workspace.task-1", JSON.stringify({ session_id: "session-1", token: "token", expires_at: new Date(Date.now() + 120_000).toISOString(), capabilities: { webide: true } }));
    vi.mocked(workspaceApi.renewSession).mockRejectedValue(new Error("unavailable"));
    const client = mount();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    const editor = screen.getByTitle("实验文件编辑器");
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(screen.getByText("工作区续期失败，请先在编辑器中保存文件，再重新进入工作台")).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(workspaceApi.renewSession).toHaveBeenCalledTimes(1);
    expect(screen.getByTitle("实验文件编辑器")).toBe(editor);
    expect(JSON.parse(sessionStorage.getItem("edu.workspace.task-1")!).token).toBe("token");
    client.clear();
  });

  it("does not describe a failed execution as never run", async () => {
    vi.mocked(workspaceApi.executionRuns).mockResolvedValue({ rows: [{ public_id: "run-1", status: "FAILED", error_code: "RUNTIME_ALGORITHM_FAILED" }] } as never);
    const client = mount();
    expect(await screen.findByText(/测试失败 · RUNTIME_ALGORITHM_FAILED/)).toBeInTheDocument();
    expect(screen.queryByText(/尚未运行/)).not.toBeInTheDocument();
    client.clear();
  });

  it.each([
    ["RUNTIME_COMPILE_FAILED", "编译失败"],
    ["RUNTIME_EXECUTION_FAILED", "运行失败"],
    ["RUNTIME_TIMEOUT", "运行超时"],
  ])("shows the execution failure stage for %s", async (errorCode, label) => {
    const run = {
      public_id: "run-1", status: "FAILED", error_code: errorCode,
    };
    vi.mocked(workspaceApi.executionRuns).mockResolvedValue({ rows: [run] } as never);
    vi.mocked(workspaceApi.executionRun).mockResolvedValue(run as never);
    const client = mount();
    expect(await screen.findByText(new RegExp(`${label} · ${errorCode}`))).toBeInTheDocument();
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

  it("shows a fixed language as read-only", async () => {
    vi.mocked(workspaceApi.workbench).mockResolvedValue({
      chapters: [], tests: [], workspace: {
        language: "python", language_policy: { mode: "FIXED", language: "python", allowed_languages: ["python"] }, toolchain_version: "3.14.0",
      },
    } as never);
    const client = mount();
    expect(await screen.findByLabelText("当前编程语言")).toHaveTextContent("Python · 3.14.0");
    expect(screen.queryByRole("combobox", { name: "编程语言" })).not.toBeInTheDocument();
    client.clear();
  });

  it("switches a student-selected language after capturing the current project", async () => {
    vi.mocked(workspaceApi.workbench).mockResolvedValue({
      chapters: [], tests: [], workspace: {
        language: "python", language_policy: { mode: "STUDENT_SELECT", allowed_languages: ["python", "c"], default_versions: { python: "3.14.0", c: "12.2.0" } }, toolchain_version: "3.14.0",
      },
    } as never);
    vi.mocked(workspaceApi.captureSnapshot).mockResolvedValue({ status: "PASSED", result_snapshot_id: "snapshot-current" } as never);
    vi.mocked(workspaceApi.checkpoints).mockResolvedValue({ rows: [], sessionRowVersion: 7 } as never);
    const client = mount();
    const select = await screen.findByRole("combobox", { name: "编程语言" });
    fireEvent.change(select, { target: { value: "c" } });
    await waitFor(() => expect(workspaceApi.storageJob).toHaveBeenCalledWith("task-1", { kind: "SWITCH", language: "c" }, 7, "token"));
    expect(vi.mocked(workspaceApi.captureSnapshot).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(workspaceApi.storageJob).mock.invocationCallOrder[0]!);
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

  it("refreshes the server submission gate when a formal run finishes", async () => {
    const data = { chapters: [], tests: [], submission: { can_submit: false, blocked_reason: { code: "TEST_NOT_PASSED" } } };
    vi.mocked(workspaceApi.workbench).mockResolvedValue(data as never);
    vi.mocked(workspaceApi.executionRuns).mockResolvedValue({ rows: [{ public_id: "run-1", status: "RUNNING" }] } as never);
    const client = mount();
    await waitFor(() => expect(workspaceApi.workbench).toHaveBeenCalled());
    vi.mocked(workspaceApi.workbench).mockClear().mockResolvedValue({ ...data, submission: { can_submit: true } } as never);
    await act(async () => {
      client.setQueryData([...keys.executionRuns("task-1"), "session-1"], {
        rows: [{ public_id: "run-1", status: "PASSED" }],
      });
    });
    await waitFor(() => expect(workspaceApi.workbench).toHaveBeenCalledTimes(1));
    expect(client.getQueryData(keys.workbench("task-1"))).toEqual({ ...data, submission: { can_submit: true } });
    client.clear();
  });

  it("blocks an empty report even when the empty draft is already saved", async () => {
    vi.mocked(reportApi.draft).mockResolvedValue({ ...draft, body_markdown: "" } as never);
    const client = mount();
    await waitFor(() => expect(screen.getByText("已保存")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "提交报告" }));
    expect(screen.getByText(/请先填写报告内容/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "请先完成检查" })).toBeDisabled();
    expect(reportApi.submitReport).not.toHaveBeenCalled();
    client.clear();
  });

  it("submits a non-report task only after capturing the current code", async () => {
    vi.mocked(taskApi.detail).mockResolvedValue({ public_id: "task-1", status: "IN_PROGRESS", report_required: false, row_version: "8", blockers: [] } as never);
    let captured!: (value: never) => void;
    vi.mocked(workspaceApi.captureSnapshot).mockImplementationOnce(() => new Promise(resolve => { captured = resolve; }));
    const client = mount();
    fireEvent.click(await screen.findByRole("button", { name: "完成实验" }));
    expect(screen.queryByRole("tab", { name: "实验报告" })).not.toBeInTheDocument();
    expect(reportApi.draft).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认完成" }));
    await waitFor(() => expect(workspaceApi.captureSnapshot).toHaveBeenCalled());
    expect(taskApi.complete).not.toHaveBeenCalled();
    await act(async () => captured({ status: "PASSED", result_snapshot_id: "saved" } as never));
    await waitFor(() => expect(taskApi.complete).toHaveBeenCalledWith("task-1", "8"));
    expect(reportApi.submitReport).not.toHaveBeenCalled();
    client.clear();
  });

  it("stops completion when the snapshot cannot be saved", async () => {
    vi.mocked(taskApi.detail).mockResolvedValue({ public_id: "task-1", status: "IN_PROGRESS", report_required: false, blockers: [] } as never);
    vi.mocked(workspaceApi.captureSnapshot).mockRejectedValueOnce(new Error("快照保存失败"));
    const client = mount();
    fireEvent.click(await screen.findByRole("button", { name: "完成实验" }));
    fireEvent.click(screen.getByRole("button", { name: "确认完成" }));
    expect(await screen.findByText("快照保存失败")).toBeInTheDocument();
    expect(taskApi.complete).not.toHaveBeenCalled();
    client.clear();
  });

  it.each([false, true])("hides reset without both capability and permission (webide=%s)", async (webide) => {
    sessionStorage.setItem("edu.workspace.task-1", JSON.stringify({ session_id: "session-1", token: "token", capabilities: { webide } }));
    vi.mocked(workspaceApi.workbench).mockResolvedValue({ chapters: [], task: { allowed_operations: webide ? [] : ["RESET_WORKSPACE"] } } as never);
    const client = mount();
    await screen.findByRole("button", { name: "保存代码" });
    expect(screen.queryByRole("button", { name: "重置工作区" })).not.toBeInTheDocument();
    client.clear();
  });

  it("confirms reset, saves the editor and snapshot, then reloads the editor", async () => {
    vi.mocked(workspaceApi.workbench).mockResolvedValue({ chapters: [], task: { allowed_operations: ["RESET_WORKSPACE"] } } as never);
    vi.mocked(workspaceApi.checkpoints).mockResolvedValue({ rows: [], sessionRowVersion: 9 } as never);
    const client = mount();
    fireEvent.click(await screen.findByRole("button", { name: "重置工作区" }));
    expect(workspaceApi.storageJob).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认重置" }));
    await waitFor(() => expect(workspaceApi.storageJob).toHaveBeenCalledWith("task-1", { kind: "RESET" }, 9, "token"));
    expect(vi.mocked(workspaceApi.editorControl).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(workspaceApi.captureSnapshot).mock.invocationCallOrder[0]!);
    expect(vi.mocked(workspaceApi.captureSnapshot).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(workspaceApi.storageJob).mock.invocationCallOrder[0]!);
    await waitFor(() => expect(workspaceApi.editorControl).toHaveBeenLastCalledWith("session-1", "reload", "token"));
    client.clear();
  });

  it("does not run or capture unsaved editor buffers after saveAll fails", async () => {
    vi.mocked(workspaceApi.workbench).mockResolvedValue({ chapters: [], tests_available: true } as never);
    vi.mocked(workspaceApi.editorControl).mockRejectedValueOnce(new Error("编辑器仍有未保存文件"));
    const client = mount();
    fireEvent.click(await screen.findByRole("button", { name: "运行测试" }));
    expect(await screen.findByText("编辑器仍有未保存文件")).toBeInTheDocument();
    expect(workspaceApi.captureSnapshot).not.toHaveBeenCalled();
    expect(workspaceApi.createExecutionRun).not.toHaveBeenCalled();
    client.clear();
  });

  it("keeps the same editor mounted while viewing test results", async () => {
    const client = mount();
    const editor = await screen.findByTitle("实验文件编辑器");
    fireEvent.click(screen.getByRole("tab", { name: "结果预览" }));
    expect(screen.getByTitle("实验文件编辑器")).toBe(editor);
    expect(editor.parentElement).toHaveAttribute("hidden");
    client.clear();
  });

  it("renders the manual safely and keeps self tests separate from formal results", async () => {
    vi.mocked(workspaceApi.workbench).mockResolvedValue({ chapters: [], tests_available: true,
      content: { manual: { format: "markdown", text: "# 指导书\n\n<script>alert(1)</script>" } },
      task: { allowed_operations: ["SELF_TEST"] } } as never);
    vi.mocked(workspaceApi.executionRuns).mockResolvedValue({ rows: [{ public_id: "debug-1", status: "PASSED", evaluation_mode: "SELF_TEST" }] } as never);
    vi.mocked(workspaceApi.executionRun).mockResolvedValue({ public_id: "debug-1", status: "PASSED", evaluation_mode: "SELF_TEST", test_cases: [{ status: "PASSED", stdout: "debug output" }] } as never);
    const client = mount();
    expect(await screen.findByRole("heading", { name: "指导书", level: 1 })).toBeInTheDocument();
    expect(document.querySelector(".workbench-manual script")).toBeNull();
    expect(await screen.findByText("debug output")).toBeInTheDocument();
    expect(screen.getByText(/尚未运行/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "提交报告" }));
    expect(screen.getByRole("button", { name: "请先完成检查" })).toBeDisabled();
    client.clear();
  });

  it("shows public failure output and only the status of hidden cases", async () => {
    vi.mocked(workspaceApi.executionRuns).mockResolvedValue({ rows: [{ public_id: "formal-1", status: "FAILED", evaluation_mode: "FORMAL" }] } as never);
    vi.mocked(workspaceApi.executionRun).mockResolvedValue({ public_id: "formal-1", status: "FAILED", evaluation_mode: "FORMAL", test_cases: [
      { status: "FAILED", input: "public input", expected: "public expected", stdout: "public actual" },
      { status: "FAILED", hidden: true, input: "secret input", expected: "secret expected", stdout: "secret actual" },
    ] } as never);
    const client = mount();
    fireEvent.click(await screen.findByRole("tab", { name: "结果预览" }));
    expect(await screen.findByText("实际输出：public actual")).toBeInTheDocument();
    expect(screen.getByText("隐藏用例")).toBeInTheDocument();
    expect(screen.queryByText(/secret/)).not.toBeInTheDocument();
    client.clear();
  });

  it("requires another formal run after the saved project changes", async () => {
    vi.mocked(workspaceApi.workbench).mockResolvedValue({ chapters: [], tests_available: true,
      workspace: { last_synchronized_snapshot_id: "snapshot-current" } } as never);
    vi.mocked(workspaceApi.executionRuns).mockResolvedValue({ rows: [{
      public_id: "formal-old", snapshot_id: "snapshot-old", status: "PASSED", evaluation_mode: "FORMAL",
    }] } as never);
    vi.mocked(workspaceApi.executionRun).mockResolvedValue({
      public_id: "formal-old", snapshot_id: "snapshot-old", status: "PASSED", evaluation_mode: "FORMAL",
    } as never);
    const client = mount();
    expect(await screen.findByText(/尚未运行/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "提交报告" }));
    expect(screen.getByRole("button", { name: "请先完成检查" })).toBeDisabled();
    client.clear();
  });

  it("does not show self-test output from a different language project", async () => {
    vi.mocked(workspaceApi.workbench).mockResolvedValue({ chapters: [], tests_available: true,
      task: { allowed_operations: ["SELF_TEST"] },
      workspace: { last_synchronized_snapshot_id: "snapshot-current" } } as never);
    vi.mocked(workspaceApi.executionRuns).mockResolvedValue({ rows: [{
      public_id: "self-old", snapshot_id: "snapshot-old", status: "PASSED", evaluation_mode: "SELF_TEST",
    }] } as never);
    vi.mocked(workspaceApi.executionRun).mockResolvedValue({
      public_id: "self-old", snapshot_id: "snapshot-old", status: "PASSED", evaluation_mode: "SELF_TEST",
      test_cases: [{ status: "PASSED", stdout: "old language output" }],
    } as never);
    const client = mount();
    await waitFor(() => expect(workspaceApi.executionRun).toHaveBeenCalledWith("task-1", "self-old", "token"));
    expect(screen.queryByLabelText("自测结果")).not.toBeInTheDocument();
    expect(screen.queryByText("old language output")).not.toBeInTheDocument();
    expect(screen.getByText(/尚未运行/)).toBeInTheDocument();
    client.clear();
  });
});
