import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { assessmentTeachingApi, teachingApi } from "@edu/api-client";
import { AssessmentQuestions } from "./assessment-questions";

vi.mock("@edu/api-client", () => ({
  teachingApi: { createTemplateChapter: vi.fn() },
  assessmentTeachingApi: { storeTests: vi.fn(), saveQuestion: vi.fn() },
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("starts a programming question from an empty version and creates its default group", async () => {
  vi.mocked(teachingApi.createTemplateChapter).mockResolvedValue({
    public_id: "chapter-1", title: "题目", sort_order: 1, status: "DRAFT", tasks: [],
  } as never);
  vi.mocked(assessmentTeachingApi.storeTests).mockResolvedValue({ asset_id: "tests-1", row_version: 6 } as never);
  const refresh = vi.fn(async () => undefined);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><AssessmentQuestions
    courseId="course" templateId="template"
    version={{ public_id: "version", status: "DRAFT", row_version: 5, chapters: [] } as never}
    refresh={refresh}
  /></ToastProvider></QueryClientProvider>);

  expect(screen.queryByText("导入课程章节")).toBeNull();
  expect(screen.queryByText("新增章节")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "新增编程题" }));
  expect(await screen.findByText("公开示例")).toBeInTheDocument();
  expect(screen.getByText("隐藏测试组（学生不可见）")).toBeInTheDocument();
  expect(screen.getByLabelText("参考解代码")).toBeInTheDocument();
  expect(screen.queryByLabelText("正确选项 1")).toBeNull();
  expect(teachingApi.createTemplateChapter).toHaveBeenCalledWith("course", "version", { title: "题目" }, 5);
  expect(screen.getByText("题型：编程题")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "新增编程题" })).toHaveLength(1);

  fireEvent.change(screen.getByLabelText("标题"), { target: { value: "求和" } });
  fireEvent.click(screen.getByRole("button", { name: "保存题目" }));
  await waitFor(() => expect(assessmentTeachingApi.saveQuestion).toHaveBeenCalledWith(
    "course", "chapter-1", null,
    expect.objectContaining({ task_type: "PROGRAMMING", title: "求和" }),
    6,
  ));
  client.clear();
});

it.each([true, false])("saves a Java-only question (Java selected first: %s)", async (javaFirst) => {
  vi.mocked(assessmentTeachingApi.storeTests).mockResolvedValue({ asset_id: "tests-1", row_version: 6 });
  render(<ToastProvider><AssessmentQuestions
    courseId="course" templateId="template"
    version={{
      public_id: "version", status: "DRAFT", row_version: 5,
      chapters: [{ public_id: "chapter-1", title: "题目", tasks: [] }],
    } as never}
    refresh={async () => undefined}
  /></ToastProvider>);

  fireEvent.click(screen.getByRole("button", { name: "新增编程题" }));
  fireEvent.change(screen.getByLabelText("标题"), { target: { value: "Java 求和" } });
  const python = screen.getByRole("checkbox", { name: "python" });
  const java = screen.getByRole("checkbox", { name: "java" });
  if (javaFirst) {
    fireEvent.click(java);
    fireEvent.click(python);
  } else {
    fireEvent.click(python);
    fireEvent.click(screen.getByRole("button", { name: "保存题目" }));
    expect(await screen.findByText("请至少选择一种允许语言")).toBeInTheDocument();
    expect(assessmentTeachingApi.storeTests).not.toHaveBeenCalled();
    fireEvent.click(java);
  }

  const language = screen.getByLabelText("参考解语言");
  expect(language).toHaveValue("java");
  fireEvent.click(python);
  expect(language).toHaveValue("java");
  fireEvent.click(python);

  const reference = "public class Main {}";
  fireEvent.change(screen.getByLabelText("参考解代码"), { target: { value: reference } });
  fireEvent.click(screen.getByRole("button", { name: "保存题目" }));
  await waitFor(() => expect(assessmentTeachingApi.saveQuestion).toHaveBeenCalledWith(
    "course", "chapter-1", null,
    expect.objectContaining({
      question_spec: expect.objectContaining({ allowed_languages: ["java"] }),
      marking_spec: expect.objectContaining({ reference_solutions: { java: { "Main.java": reference } } }),
    }),
    6,
  ));
});
