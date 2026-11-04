import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { agentApi, meApi, studentApi, timetableApi } from "@edu/api-client";
import type { AgentMessage, Enrollment, TimetableImport } from "@edu/api-client";
import { ToastProvider } from "@edu/ui";
import { EnrollmentExit } from "./enrollment-exit";
import { LearningHistory } from "./learning-history";
import { StudentTimetable } from "./student-timetable";
import { CourseAgent } from "./course-agent";
import type { ReactNode } from "react";

vi.mock("@edu/api-client", () => ({
  studentApi: { enrollment: vi.fn(), dropCheck: vi.fn(), dropEnrollment: vi.fn(), withdrawEnrollment: vi.fn() },
  meApi: { learningHistory: vi.fn() },
  timetableApi: { retrieve: vi.fn(), imports: vi.fn(), importJob: vi.fn(), upload: vi.fn(), updateMapping: vi.fn(), confirm: vi.fn() },
  agentApi: { courseProfile: vi.fn(), createCourseSession: vi.fn(), createTaskSession: vi.fn(), session: vi.fn(), messages: vi.fn(), sendMessage: vi.fn(), feedback: vi.fn(), decideToolCall: vi.fn() },
  fileApi: { createDownloadGrant: vi.fn() },
}));

const enrollment = { public_id: "en-1", course_id: "course-1", course_title: "编程基础", status: "ACTIVE", row_version: "1" } as Enrollment;
const list = <T,>(rows: T[]) => ({ rows, page: 1, pageSize: 20, total: rows.length });
const message = (id: string, role: string, body: string): AgentMessage => ({ public_id: id, role, body, status: "COMPLETE", created_at: "2026-11-03T00:00:00Z", citations: [], tool_calls: [] });
const clients: QueryClient[] = [];
function show(content: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter>{content}</MemoryRouter></ToastProvider></QueryClientProvider>);
  return client;
}
beforeEach(() => vi.resetAllMocks());
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

describe("学生课程接口入口", () => {
  it("显示退出阻塞原因并禁止提交", async () => {
    vi.mocked(studentApi.enrollment).mockResolvedValue(enrollment);
    vi.mocked(studentApi.dropCheck).mockResolvedValue({ allowed: false, blockers: [{ type: "runtime", count: 1, refs: ["task-1"], message: "请先停止运行中的实验" }] });
    show(<EnrollmentExit enrollment={enrollment} />);
    fireEvent.click(screen.getByRole("button", { name: "退出课程" }));
    expect(await screen.findByText(/请先停止运行中的实验/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("退出原因"), { target: { value: "选课调整" } });
    expect(screen.getByRole("button", { name: "确认退出" })).toBeDisabled();
    expect(studentApi.dropEnrollment).not.toHaveBeenCalled();
  });

  it("说明有未完成任务也可退出，使用最新选课版本提交并刷新待办", async () => {
    vi.mocked(studentApi.enrollment).mockResolvedValue({ ...enrollment, row_version: "9" });
    vi.mocked(studentApi.dropCheck).mockResolvedValue({ allowed: true, blockers: [] });
    vi.mocked(studentApi.dropEnrollment).mockResolvedValue({ ...enrollment, status: "DROPPED" });
    const client = show(<EnrollmentExit enrollment={enrollment} />);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    fireEvent.click(screen.getByRole("button", { name: "退出课程" }));
    await screen.findByLabelText("退出原因");
    expect(screen.getByText(/有未完成任务也可以退出课程/)).toBeInTheDocument();
    expect(screen.getByText(/退课立即生效.*通知课程老师.*无需老师同意/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("退出原因"), { target: { value: "  选课调整  " } });
    await waitFor(() => expect(screen.getByRole("button", { name: "确认退出" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "确认退出" }));
    await waitFor(() => expect(studentApi.dropEnrollment).toHaveBeenCalledWith("en-1", { reason: "选课调整" }, "9"));
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["student"] }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["tasks"] });
    expect(await screen.findByText("已退出课程")).toBeInTheDocument();
  });

  it("待审核申请走撤回接口，不执行退课检查", async () => {
    const pending = { ...enrollment, status: "PENDING" as const, row_version: "3" };
    vi.mocked(studentApi.enrollment).mockResolvedValue(pending);
    vi.mocked(studentApi.withdrawEnrollment).mockResolvedValue({ ...pending, status: "WITHDRAWN" });
    show(<EnrollmentExit enrollment={pending} />);
    fireEvent.click(screen.getByRole("button", { name: "撤回申请" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "确认撤回" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "确认撤回" }));
    await waitFor(() => expect(studentApi.withdrawEnrollment).toHaveBeenCalledWith("en-1", "3"));
    expect(studentApi.dropCheck).not.toHaveBeenCalled();
  });

  it("学习历史按学期展示成绩与实验入口", async () => {
    vi.mocked(meApi.learningHistory).mockResolvedValue({ years: [{ university_year: 1, academic_year: "2026-2027", terms: [{ term_id: "term-1", code: "fall", name: "秋季学期", courses: [{
      course_id: "course-1", course_code: "CS101", course_title: "编程基础", class_type: "TEACHING", enrollment: { public_id: "en-1", cycle_no: 1, status: "ACTIVE", activated_at: null, ended_at: null },
      experiments: [{ task_id: "task-1", publication_id: "pub-1", title: "函数练习", status: "COMPLETED", progress: 100, completed_at: null, decision: "APPROVE", score: "98.00" }],
    }] }] }] });
    show(<LearningHistory />);
    expect(await screen.findByText("秋季学期")).toBeInTheDocument();
    expect(screen.getByText(/98.00 分/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "函数练习" })).toHaveAttribute("href", "/experiments/task-1");
  });
});

describe("课表导入", () => {
  it("显示具体错误行并阻止带错误的课表确认", async () => {
    const job = { public_id: "job-error", status: "READY", filename: "invalid.xlsx", fields: [], headers: [], mapping: {}, summary: { total: 1, errors: 1 }, row_errors: [{ row_no: 3, code: "weekday_required" }] } as unknown as TimetableImport;
    vi.mocked(timetableApi.retrieve).mockResolvedValue({ term: { public_id: "term-1", code: "fall", name: "秋季学期" }, schedules: [] });
    vi.mocked(timetableApi.imports).mockResolvedValue(list([job]));
    vi.mocked(timetableApi.importJob).mockResolvedValue(job);
    show(<StudentTimetable />);
    const imports = await screen.findByLabelText("最近的导入");
    fireEvent.change(imports, { target: { value: "job-error" } });
    expect(await screen.findByText("第 3 行：无法识别星期")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认导入" })).toBeDisabled();
  });

  it("修改映射后先保存再确认，异步完成后刷新课表", async () => {
    const job: TimetableImport = { public_id: "job-1", kind: "STUDENT", status: "READY", filename: "schedule.xlsx", term_id: "term-1", row_version: 1,
      fields: [{ key: "course_title", label: "课程名称" }, { key: "weekday", label: "星期" }, { key: "start_period", label: "开始节次" }, { key: "end_period", label: "结束节次" }],
      headers: ["课程", "名称", "星期", "开始", "结束"], mapping: { course_title: "课程", weekday: "星期", start_period: "开始", end_period: "结束" }, summary: { total: 1, valid: 1, errors: 0 }, row_errors: [],
    };
    vi.mocked(timetableApi.retrieve).mockResolvedValue({ term: { public_id: "term-1", code: "fall", name: "秋季学期" }, schedules: [] });
    vi.mocked(timetableApi.imports).mockResolvedValue(list([job]));
    vi.mocked(timetableApi.upload).mockResolvedValue(job);
    vi.mocked(timetableApi.importJob).mockResolvedValue(job);
    vi.mocked(timetableApi.updateMapping).mockResolvedValue({ ...job, mapping: { ...job.mapping, course_title: "名称" } });
    vi.mocked(timetableApi.confirm).mockResolvedValue({ ...job, status: "RUNNING" });
    const client = show(<StudentTimetable />);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    await screen.findByText("秋季学期");
    const workbook = new File(["xlsx"], "schedule.xlsx");
    fireEvent.change(screen.getByLabelText(/导入个人课表/), { target: { files: [workbook] } });
    fireEvent.click(screen.getByRole("button", { name: "上传课表" }));
    await waitFor(() => expect(timetableApi.upload).toHaveBeenCalledWith(workbook, "term-1"));
    await screen.findByLabelText("课程名称 *");
    fireEvent.change(screen.getByLabelText("课程名称 *"), { target: { value: "名称" } });
    expect(screen.getByRole("button", { name: "确认导入" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "保存并检查" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "确认导入" })).toBeEnabled());
    expect(timetableApi.updateMapping).toHaveBeenCalledWith("job-1", { ...job.mapping, course_title: "名称" });
    // The worker completes on the next polling read.
    vi.mocked(timetableApi.importJob).mockResolvedValue({ ...job, status: "COMPLETED" });
    fireEvent.click(screen.getByRole("button", { name: "确认导入" }));
    expect(await screen.findByText("正在导入，完成后课表会自动更新。")).toBeInTheDocument();
    expect(await screen.findByText("课表已导入。", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["student", "timetable", "current"] });
  });
});

describe("课程与实验助手", () => {
  beforeEach(() => {
    vi.mocked(agentApi.courseProfile).mockResolvedValue({ course_id: "course-1", enrollment_id: "en-1", profile: { public_id: "profile-1", modes: ["KNOWLEDGE_QA"], status: "ACTIVE", version_no: 1, row_version: 1 }, capabilities: { modes: ["KNOWLEDGE_QA"], tool_risk: null } });
    const session = { public_id: "session-1", course_id: "course-1", enrollment_id: "en-1", task_id: null, mode: "KNOWLEDGE_QA" as const, status: "ACTIVE", profile_id: "profile-1", profile_version: 1, row_version: 1 };
    vi.mocked(agentApi.createCourseSession).mockResolvedValue(session);
    vi.mocked(agentApi.createTaskSession).mockResolvedValue({ ...session, task_id: "task-1" });
    vi.mocked(agentApi.session).mockResolvedValue(session);
    vi.mocked(agentApi.messages).mockResolvedValue(list([]));
  });

  it("USER COMPLETE 不视为回复完成，等待 ASSISTANT 后再允许继续提问", async () => {
    const user = message("user-1", "USER", "什么是函数？");
    const reply = message("reply-1", "ASSISTANT", "函数是可复用的代码单元。");
    vi.mocked(agentApi.sendMessage).mockResolvedValue(user);
    vi.mocked(agentApi.feedback).mockResolvedValue({ public_id: "feedback-1", status: "OPEN" });
    show(<CourseAgent courseId="course-1" />);
    fireEvent.click(screen.getByRole("button", { name: "打开助手" }));
    fireEvent.click(await screen.findByRole("button", { name: "开始对话" }));
    const input = await screen.findByLabelText("向助手提问");
    fireEvent.change(input, { target: { value: "什么是函数？" } });
    vi.mocked(agentApi.messages).mockResolvedValue(list([user]));
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByText("助手正在回复，完成后会自动更新。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
    vi.mocked(agentApi.messages).mockResolvedValue(list([user, reply]));
    expect(await screen.findByText(reply.body, {}, { timeout: 4000 })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "有帮助" }));
    await waitFor(() => expect(agentApi.feedback).toHaveBeenCalledWith("reply-1", { rating: "USEFUL" }));
    expect(agentApi.sendMessage).toHaveBeenCalledTimes(1);
  });

  it("实验助手建立任务范围会话，工具决定携带工具状态版本", async () => {
    const reply = message("reply-1", "ASSISTANT", "请确认工具调用");
    reply.tool_calls = [{ public_id: "tool-1", session_id: "session-1", tool_name: "workspace.inspect", risk: "MEDIUM", state: { public_id: "state-1", status: "PENDING_APPROVAL", row_version: 7, output: null, error_code: "" } }];
    vi.mocked(agentApi.messages).mockResolvedValue(list([reply]));
    vi.mocked(agentApi.decideToolCall).mockResolvedValue({ public_id: "state-1", status: "REJECTED", row_version: 8 });
    show(<CourseAgent courseId="course-1" taskId="task-1" />);
    fireEvent.click(screen.getByRole("button", { name: "打开助手" }));
    fireEvent.click(await screen.findByRole("button", { name: "开始对话" }));
    fireEvent.click(await screen.findByRole("button", { name: "拒绝执行" }));
    await waitFor(() => expect(agentApi.decideToolCall).toHaveBeenCalledWith("tool-1", { decision: "REJECTED" }, 7));
    expect(agentApi.createTaskSession).toHaveBeenCalledWith("task-1", "KNOWLEDGE_QA");
    expect(agentApi.createCourseSession).not.toHaveBeenCalled();
  });
});
