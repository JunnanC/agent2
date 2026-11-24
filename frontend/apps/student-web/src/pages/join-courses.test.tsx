import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { studentApi } from "@edu/api-client";
import type { Course, Enrollment } from "@edu/api-client";
import { ToastProvider } from "@edu/ui";
import { JoinCourses } from "./join-courses";

vi.mock("@edu/api-client", () => ({ studentApi: {
  courses: vi.fn(), myEnrollments: vi.fn(), joinCourse: vi.fn(), resolveInvitation: vi.fn(),
  enrollment: vi.fn(), withdrawEnrollment: vi.fn(), dropCheck: vi.fn(), dropEnrollment: vi.fn(),
} }));

const course: Course = {
  public_id: "course-1", code: "CS101", title: "编程基础", status: "PUBLISHED",
  enrollment_mode: "OPEN", capacity: 30, active_enrollment_count: 0, row_version: "1",
};
const enrollment = (status: "ACTIVE" | "PENDING") => ({
  public_id: "en-1", course_id: course.public_id, course_title: course.title,
  student_id: "student-1", student_name: "学生", status, row_version: "1",
}) satisfies Enrollment;
const clients: QueryClient[] = [];
function CoursePage() { return <p>课程页面 {useParams().courseId}</p>; }
function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter initialEntries={["/courses/join"]}>
    <Routes><Route path="/courses/join" element={<JoinCourses />} /><Route path="/courses/:courseId" element={<CoursePage />} /></Routes>
  </MemoryRouter></ToastProvider></QueryClientProvider>);
  return client;
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(studentApi.courses).mockResolvedValue({ rows: [course], total: 1, page: 1, pageSize: 100 });
  vi.mocked(studentApi.myEnrollments).mockResolvedValue({ rows: [], total: 0, page: 1, pageSize: 100 });
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

describe("课程加入策略", () => {
  it("无邀请码不能提交申请", async () => {
    show();
    fireEvent.click(await screen.findByRole("button", {name: "申请加入"}));
    expect(screen.getByRole("button", {name: "提交加入申请"})).toBeDisabled();
    expect(studentApi.joinCourse).not.toHaveBeenCalled();
  });

  it("弹窗填写邀请码后等待审核并刷新缓存", async () => {
    vi.mocked(studentApi.joinCourse).mockResolvedValue(enrollment("PENDING"));
    const client = show();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    fireEvent.click(await screen.findByRole("button", { name: "申请加入" }));
    fireEvent.change(screen.getByLabelText(/课程邀请码/), { target: { value: "  valid-code  " } });
    fireEvent.click(screen.getAllByRole("button", { name: "提交邀请码申请" }).at(-1)!);
    expect(await screen.findByText("申请已提交，等待教师审核")).toBeInTheDocument();
    expect(studentApi.joinCourse).toHaveBeenCalledWith("course-1", { invitation_code: "valid-code", application_message: undefined });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["student-enrollments"] });
  });

  it("凭课程码查到教学班后需明确确认才申请", async () => {
    vi.mocked(studentApi.courses).mockResolvedValue({ rows: [], total: 0, page: 1, pageSize: 100 });
    vi.mocked(studentApi.resolveInvitation).mockResolvedValue({ ...course, public_id: "invited-course" });
    vi.mocked(studentApi.joinCourse).mockResolvedValue({ ...enrollment("PENDING"), course_id: "invited-course" });
    show();
    fireEvent.change(await screen.findByLabelText("课程码"), { target: { value: "invite-code" } });
    fireEvent.click(screen.getByRole("button", { name: "查找教学班" }));
    const confirm = await screen.findByRole("button", { name: "确认申请加入" });
    expect(studentApi.joinCourse).not.toHaveBeenCalled();
    fireEvent.click(confirm);
    expect(await screen.findByText("申请已提交，等待教师审核")).toBeInTheDocument();
    expect(studentApi.resolveInvitation).toHaveBeenCalledWith("invite-code");
    expect(studentApi.joinCourse).toHaveBeenCalledWith("invited-course", { invitation_code: "invite-code" });
  });

  it("无效邀请码不发送加入申请", async () => {
    vi.mocked(studentApi.resolveInvitation).mockRejectedValue(new Error("invalid"));
    show();
    fireEvent.change(await screen.findByLabelText("课程码"), { target: { value: "wrong-code" } });
    fireEvent.click(screen.getByRole("button", { name: "查找教学班" }));
    await waitFor(() => expect(screen.getByText("邀请码无效或已失效")).toBeInTheDocument());
    expect(studentApi.joinCourse).not.toHaveBeenCalled();
  });

  it("我的申请可撤回待审核记录，并使用当前选课周期", async () => {
    const pending = enrollment("PENDING");
    const history = { ...pending, public_id: "old-enrollment", status: "WITHDRAWN" as const };
    vi.mocked(studentApi.myEnrollments).mockResolvedValue({ rows: [pending, history], total: 2, page: 1, pageSize: 100 });
    vi.mocked(studentApi.enrollment).mockResolvedValue({ ...pending, row_version: "7" });
    vi.mocked(studentApi.withdrawEnrollment).mockImplementation(async () => {
      vi.mocked(studentApi.myEnrollments).mockResolvedValue({ rows: [], total: 0, page: 1, pageSize: 100 });
      return { ...pending, status: "WITHDRAWN" };
    });
    show();
    fireEvent.click(screen.getByRole("tab", { name: /我的申请/ }));
    fireEvent.click(await screen.findByRole("button", { name: "撤回申请" }));
    expect(screen.queryByRole("button", { name: "进入课程" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "确认撤回" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "确认撤回" }));
    expect(await screen.findByText("暂无申请记录")).toBeInTheDocument();
    expect(studentApi.withdrawEnrollment).toHaveBeenCalledWith("en-1", "7");
  });

  it("我的申请不再显示已加入的课程", async () => {
    vi.mocked(studentApi.myEnrollments).mockResolvedValue({ rows: [enrollment("ACTIVE")], total: 1, page: 1, pageSize: 100 });
    show();
    fireEvent.click(screen.getByRole("tab", { name: /我的申请/ }));
    expect(await screen.findByText("暂无申请记录")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "退出课程" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "进入课程" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /我的申请/ })).toHaveTextContent("我的申请 0");
  });
});
