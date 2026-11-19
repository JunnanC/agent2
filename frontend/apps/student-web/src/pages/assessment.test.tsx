import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { assessmentApi } from "@edu/api-client";
import { ToastProvider } from "@edu/ui";
import { AssessmentWorkbench } from "./assessment";

vi.mock("@edu/ui", async original => ({
  ...await original<typeof import("@edu/ui")>(),
  CodeEditor: ({ value, onChange, ariaLabel }: { value: string; onChange: (value: string) => void; ariaLabel: string }) =>
    <textarea aria-label={ariaLabel} value={value} onChange={event => onChange(event.target.value)} />,
}));

vi.mock("@edu/api-client", () => ({ assessmentApi: {
  get: vi.fn(async () => ({
    task_id: "task", questions: [{ id: "q", title: "栈", description: "访问顺序", instructions: "", task_type: "SINGLE_CHOICE", max_score: "5", options: [{ id: "a", text: "先进先出" }, { id: "b", text: "后进先出" }] }],
    sections: [{ kind: "CHOICE", status: "NOT_SUBMITTED", grading_status: "NOT_SUBMITTED", score: null, deadline: "2099-01-01T00:00:00Z" }],
    server_time: new Date().toISOString(), all_submitted: false, choice_answers_visible: false,
  })),
  choiceDraft: vi.fn(async () => ({ selected_option_ids: [], row_version: 1 })),
  history: vi.fn(async () => []),
  saveChoice: vi.fn(async () => ({ selected_option_ids: ["b"], row_version: 2 })),
  submitChoices: vi.fn(async () => ({ version_no: 1 })),
  codeDraft: vi.fn(async () => ({ files: {}, row_version: 1, language: "python" })),
  saveCode: vi.fn(async () => ({ files: {}, row_version: 1, language: "python" })),
  reportDraft: vi.fn(async () => ({ body_markdown: "", row_version: 1, attachments: [] })),
  saveReport: vi.fn(async () => ({ body_markdown: "", row_version: 1 })),
  submitProgramming: vi.fn(async () => ({ version_no: 1 })),
  run: vi.fn(),
  runResult: vi.fn(),
  enterWorkspace: vi.fn(),
  workspace: vi.fn(),
  attempt: vi.fn(),
  attemptResult: vi.fn(),
} }));

afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("saves the current code before switching questions and restores each question's draft", async () => {
  vi.mocked(assessmentApi.get).mockResolvedValueOnce({
    task_id: "task", server_time: new Date().toISOString(),
    questions: ["depth", "insert"].map(id => ({
      id, title: id === "depth" ? "二叉树的最大深度" : "二分查找插入点",
      description: id, instructions: "", task_type: "PROGRAMMING", max_score: "10",
      allowed_languages: ["python", "c"], selected_language: "python", samples: [],
      starter_files: {}, limits: {},
    })),
    sections: [{ kind: "PROGRAMMING", status: "NOT_SUBMITTED", grading_status: "NOT_SUBMITTED",
      score: null, deadline: "2099-01-01T00:00:00Z", editable: true }],
  } as never);
  vi.mocked(assessmentApi.codeDraft)
    .mockResolvedValueOnce({ files: { "main.py": "depth draft" }, row_version: 1, language: "python" })
    .mockResolvedValueOnce({ files: { "main.py": "insert draft" }, row_version: 1, language: "python" })
    .mockResolvedValueOnce({ files: { "main.py": "depth edited" }, row_version: 2, language: "python" })
    .mockResolvedValueOnce({ files: { "main.c": "C draft" }, row_version: 1, language: "c" });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/experiments/task/assessment"]}>
    <Routes><Route path="/experiments/:taskId/assessment" element={<AssessmentWorkbench />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);

  const editor = await screen.findByRole("textbox", { name: "代码 main.py" });
  expect(editor).toHaveValue("depth draft");
  fireEvent.change(editor, { target: { value: "depth edited" } });
  fireEvent.click(screen.getByRole("button", { name: "2. 二分查找插入点" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "2. 二分查找插入点" })).toHaveAttribute("aria-pressed", "true"));
  expect(assessmentApi.saveCode).toHaveBeenCalledWith("task", "depth", "python", { "main.py": "depth edited" }, expect.any(Number));
  await waitFor(() => expect(screen.getByRole("textbox", { name: "代码 main.py" })).toHaveValue("insert draft"));

  fireEvent.click(screen.getByRole("button", { name: "1. 二叉树的最大深度" }));
  await waitFor(() => expect(screen.getByRole("textbox", { name: "代码 main.py" })).toHaveValue("depth edited"));
  fireEvent.change(screen.getByRole("combobox", { name: "语言" }), { target: { value: "c" } });
  await waitFor(() => expect(screen.getByRole("textbox", { name: "代码 main.c" })).toHaveValue("C draft"));
  expect(screen.getByRole("combobox", { name: "语言" })).toHaveValue("c");
  await waitFor(() => expect(assessmentApi.saveCode).toHaveBeenCalledWith("task", "depth", "c", { "main.c": "C draft" }, 1));
  vi.mocked(assessmentApi.saveCode).mockRejectedValueOnce(new Error("offline"));
  fireEvent.change(screen.getByRole("textbox", { name: "代码 main.c" }), { target: { value: "C unsaved" } });
  fireEvent.click(screen.getByRole("button", { name: "2. 二分查找插入点" }));
  expect(await screen.findByText("请先处理未保存内容或版本冲突")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "1. 二叉树的最大深度" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("textbox", { name: "代码 main.c" })).toHaveValue("C unsaved");
  client.clear();
});

it("shows the submitted answer sheet and per-question score after the deadline", async () => {
  vi.mocked(assessmentApi.get).mockResolvedValueOnce({
    task_id: "task",
    questions: [{
      id: "q", title: "栈", description: "访问顺序", instructions: "", task_type: "SINGLE_CHOICE",
      max_score: "5", options: [{ id: "a", text: "先进先出" }, { id: "b", text: "后进先出" }],
      correct_option_ids: ["b"], explanation: "",
    }],
    sections: [{
      kind: "CHOICE", status: "SUBMITTED", grading_status: "COMPLETED", score: "5",
      max_score: "5", deadline: "2020-01-01T00:00:00Z", editable: false, submission_version: 1,
      questions: [{ id: "q", score: "5", max_score: "5", language: "" }],
    }],
    server_time: new Date().toISOString(), all_submitted: true, choice_answers_visible: true,
  } as never);
  vi.mocked(assessmentApi.history).mockResolvedValueOnce([{
    kind: "CHOICE", version_no: 1, submitted_at: "2026-01-01T00:00:00Z", is_current: true,
    answers: [{ question_id: "q", selected_option_ids: ["b"], language: "", snapshot_digest: null }],
    report: null,
  }]);

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/experiments/task/assessment"]}>
    <Routes><Route path="/experiments/:taskId/assessment" element={<AssessmentWorkbench />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);

  await waitFor(() => expect(screen.getByRole("radio", { name: "后进先出" })).toBeChecked());
  expect(screen.getByRole("radio", { name: "先进先出" })).not.toBeChecked();
  expect(screen.getByText("本题得分：5 / 5 · 正确")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "查看答卷" }));
  expect(await screen.findByText("第 1 次提交答卷")).toBeTruthy();
  client.clear();
});

it("saves answers and flushes before submitting only the choice section", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/experiments/task/assessment"]}>
    <Routes><Route path="/experiments/:taskId/assessment" element={<AssessmentWorkbench />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("radio", { name: "后进先出" }));
  await waitFor(() => expect(assessmentApi.saveChoice).toHaveBeenCalledWith("task", "q", ["b"], 1));
  expect(screen.queryByText(/正确选项/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "提交选择题卷" }));
  fireEvent.click(await screen.findByRole("button", { name: "确认交卷" }));
  await waitFor(() => expect(assessmentApi.submitChoices).toHaveBeenCalled());
  expect(assessmentApi.submitChoices).toHaveBeenCalledWith("task", { q: 1 }, expect.any(String));
  client.clear();
});

it("downloads the current submitted report version, not the editable draft", async () => {
  vi.mocked(assessmentApi.get).mockResolvedValueOnce({
    task_id: "task",
    questions: [{
      id: "p", title: "编程", description: "", instructions: "", task_type: "PROGRAMMING",
      max_score: "10", allowed_languages: ["python"], selected_language: "python",
      samples: [], starter_files: {}, limits: {},
    }],
    sections: [{
      kind: "PROGRAMMING", status: "SUBMITTED", grading_status: "COMPLETED", score: "10",
      deadline: "2020-01-01T00:00:00Z", submission_version: 1, editable: false,
    }],
    server_time: new Date().toISOString(), all_submitted: true, choice_answers_visible: false,
  } as never);
  vi.mocked(assessmentApi.history).mockResolvedValueOnce([{
    kind: "PROGRAMMING", version_no: 2, submitted_at: "2026-01-01T00:00:00Z",
    is_current: true, report: "# 已提交报告", answers: [],
  }]);
  const blobs: Blob[] = [];
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true, value: vi.fn((blob: Blob) => { blobs.push(blob); return "blob:report"; }),
  });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/experiments/task/assessment"]}>
    <Routes><Route path="/experiments/:taskId/assessment" element={<AssessmentWorkbench />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);

  fireEvent.click(await screen.findByRole("button", { name: "下载已提交报告" }));
  await waitFor(() => expect(blobs).toHaveLength(1));
  const text = await new Promise<string>((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(blobs[0]!);
  });
  expect(text).toContain("- 提交版本：第 2 次");
  expect(text).toContain("- 提交时间：");
  expect(text).toContain("- 本部分得分：");
  expect(text).toContain("# 已提交报告");
  expect(click).toHaveBeenCalled();
  click.mockRestore();
  client.clear();
});

it("switches programming questions through the list and shows attachment-only reports and samples", async () => {
  const question = { id: "p1", title: "求和", description: "", instructions: "", task_type: "PROGRAMMING",
    max_score: "10", allowed_languages: ["python"], selected_language: "python",
    samples: [{ input: "1 2", output: "3" }, { input: "3 4", output: "7" }], starter_files: {}, limits: {} };
  vi.mocked(assessmentApi.get).mockResolvedValueOnce({ task_id: "task", report_required: true,
    questions: [question, { ...question, id: "p2", title: "排序" }],
    sections: [{ kind: "PROGRAMMING", status: "NOT_SUBMITTED", deadline: "2099-01-01T00:00:00Z" }],
    server_time: new Date().toISOString(), all_submitted: false } as never);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/experiments/task/assessment"]}>
    <Routes><Route path="/experiments/:taskId/assessment" element={<AssessmentWorkbench />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);
  expect(await screen.findByRole("navigation", { name: "编程题列表" })).toBeInTheDocument();
  expect(screen.queryByLabelText("报告正文")).not.toBeInTheDocument();
  expect(screen.getByLabelText("报告附件")).toBeInTheDocument();
  expect(screen.getByText("示例 1").parentElement).toHaveAttribute("open");
  expect(screen.getByText("示例 2").parentElement).toHaveAttribute("open");
  await waitFor(() => expect(assessmentApi.saveCode).toHaveBeenCalled());
  fireEvent.click(screen.getByRole("button", { name: "2. 排序" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "2. 排序" })).toHaveAttribute("aria-pressed", "true"));
  expect(assessmentApi.codeDraft).toHaveBeenCalledWith("task", "p2", "python");
  client.clear();
});

it("displays hidden case verdicts and advances after a passing final run", async () => {
  const deadline = "2099-01-01T00:00:00Z";
  const question = {
    id: "first", title: "求和", description: "", instructions: "", sort_order: 1, task_type: "PROGRAMMING",
    max_score: "10", allowed_languages: ["python"], selected_language: "python",
    samples: [{ input: "1 2", output: "3" }], starter_files: {}, limits: {}, case_count: 5,
  };
  let completed = false;
  vi.mocked(assessmentApi.get).mockImplementation(async () => ({
    task_id: "task", report_required: false, workspace_available: true, workspace_flow: true,
    current_question_id: completed ? "next" : "first",
    questions: [{ ...question, submitted: completed }, { ...question, id: "next", title: "排序" }],
    sections: [{ kind: "PROGRAMMING", status: "NOT_SUBMITTED", editable: true, deadline }],
    server_time: new Date().toISOString(), all_submitted: false,
  }) as never);
  const workspace = { status: "RUNNING" as const, expires_at: deadline };
  vi.mocked(assessmentApi.enterWorkspace).mockResolvedValue(workspace);
  vi.mocked(assessmentApi.workspace).mockResolvedValue(workspace);
  vi.mocked(assessmentApi.codeDraft).mockResolvedValue({
    files: { "main.py": "print(input())" }, row_version: 1, language: "python",
  });
  vi.mocked(assessmentApi.saveCode).mockImplementation(async (_taskId, _questionId, language, files, version) =>
    ({ files, row_version: version + 1, language }));
  vi.mocked(assessmentApi.attempt).mockResolvedValueOnce({ id: 101 } as never)
    .mockResolvedValueOnce({ id: 102 } as never);
  vi.mocked(assessmentApi.attemptResult).mockImplementation(async (_taskId, _questionId, id) => {
    completed = id === 102;
    return {
      id, status: "COMPLETED", result_status: completed ? "PASSED" : "FAILED",
      submitted: completed, next_question_id: completed ? "next" : null,
      case_results: [
        { number: 1, passed: true, input: "1 2", expected_output: "3", actual_output: "3" },
        ...[2, 3, 4, 5].map(number => ({ number, passed: completed || number < 5 })),
      ],
    } as never;
  });

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/experiments/task/assessment"]}>
    <Routes><Route path="/experiments/:taskId/assessment" element={<AssessmentWorkbench />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);
  const finalRun = await screen.findByRole("button", { name: "最终运行" });
  await waitFor(() => expect(finalRun).toBeEnabled());
  fireEvent.click(finalRun);
  expect(await screen.findByText("✗ 未通过")).toBeInTheDocument();
  expect(screen.getAllByText("· 无权查看")).toHaveLength(3);
  expect(screen.getByRole("button", { name: "1. 求和" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(finalRun);
  await waitFor(() => expect(screen.getByRole("button", { name: "2. 排序" })).toHaveAttribute("aria-pressed", "true"));
  expect(screen.getByRole("button", { name: "1. 求和 · 已通过" })).toBeInTheDocument();
  client.clear();
});
