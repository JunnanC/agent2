import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { ApiError } from "@edu/auth-client";
import type { Mock } from "vitest";

vi.mock("@edu/api-client", () => ({
  reportApi: { reviewResult: vi.fn() },
  taskApi: {
    detail: vi.fn(),
    start: vi.fn(),
    enter: vi.fn(),
    retry: vi.fn(),
    complete: vi.fn(),
    provisioningJob: vi.fn(async () => null),
    requestExtension: vi.fn(),
    extensions: vi.fn(async () => ({ rows: [], page: 1, pageSize: 20, total: 0 })),
  },
}));

const taskFixture = {
  public_id: "task-1",
  course_id: "course-1",
  publication_id: "pub-1",
  title: "Linux 网络故障排查",
  status: "IN_PROGRESS",
  progress: 40,
  allowed_actions: ["enter", "extension"],
  blockers: [],
  row_version: "v-1",
};

import { reportApi, taskApi } from "@edu/api-client";
import { TaskDetail } from "./task-detail";

function renderTaskDetail(): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  void render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/experiments/task-1"]}>
          <Routes>
            <Route path="/experiments/:taskId" element={<TaskDetail />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("TaskDetail 渲染", () => {
  beforeEach(() => {
    sessionStorage.clear();
    (taskApi.detail as unknown as Mock).mockReset();
    (taskApi.detail as unknown as Mock).mockResolvedValue(taskFixture);
    (reportApi.reviewResult as unknown as Mock).mockReset().mockResolvedValue({ rounds: [], allowed_actions: [] });
  });

  it("正常渲染任务标题、进度与操作区", async () => {
    renderTaskDetail();
    expect(await screen.findByText("Linux 网络故障排查", { selector: "b" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "进入实验工作台" })).toBeInTheDocument();
    expect(screen.getAllByText("进行中").length).toBeGreaterThan(0);
  });

  it("新实验只提供轻量入口，不请求旧评审或提供容器启动操作", async () => {
    (taskApi.detail as unknown as Mock).mockResolvedValue({
      ...taskFixture, assessment_available: true, allowed_actions: ["start", "enter", "retry"],
    });
    renderTaskDetail();
    expect(await screen.findByRole("link", { name: "进入实验答题" }))
      .toHaveAttribute("href", "/experiments/task-1/assessment");
    expect(screen.queryByRole("button", { name: "进入实验工作台" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重试任务" })).not.toBeInTheDocument();
    expect(reportApi.reviewResult).not.toHaveBeenCalled();
    expect(taskApi.provisioningJob).not.toHaveBeenCalled();
  });

  it("进行中且无评审记录时不显示正在评审", async () => {
    (reportApi.reviewResult as unknown as Mock).mockRejectedValue(new ApiError({
      status: 404, url: "/review-result", method: "GET", kind: "validation",
      payload: { code: "RESOURCE_NOT_FOUND", message: "not found" },
    }));
    renderTaskDetail();
    expect(await screen.findByText("Linux 网络故障排查", { selector: "b" })).toBeInTheDocument();
    await waitFor(() => expect(reportApi.reviewResult).toHaveBeenCalled());
    expect(screen.queryByText("教师正在评审，评分与批注将在评审完成后显示。")).not.toBeInTheDocument();
  });

  it("已提交但尚无评审结果时显示等待提示", async () => {
    (taskApi.detail as unknown as Mock).mockResolvedValue({ ...taskFixture, status: "SUBMITTED" });
    renderTaskDetail();
    expect(await screen.findByText("教师正在评审，评分与批注将在评审完成后显示。")).toBeInTheDocument();
  });

  it("已完成任务展示真实成绩、分项评分和教师批注", async () => {
    (taskApi.detail as unknown as Mock).mockResolvedValue({ ...taskFixture, status: "COMPLETED", allowed_actions: [] });
    (reportApi.reviewResult as unknown as Mock).mockResolvedValue({
      score: 98,
      rounds: [{ review_id: "review-1", round_no: 1, status: "DECIDED", decision: { decision: "APPROVE", score: 98, feedback: "完成得很好" },
        scores: { criteria: [{ public_id: "criterion-1", title: "功能正确性", score: 60, max_score: 60 }] },
        annotations: [{ public_id: "annotation-1", body: "请补充边界条件说明" }] }],
    });
    renderTaskDetail();
    expect(await screen.findByText("98 分")).toBeInTheDocument();
    expect(screen.getByText("60 / 60")).toBeInTheDocument();
    expect(screen.getByText("请补充边界条件说明")).toBeInTheDocument();
    expect(screen.getByText("完成得很好")).toBeInTheDocument();
  });

  it("报告被退回到草稿状态后仍展示评审意见和修改入口", async () => {
    (taskApi.detail as unknown as Mock).mockResolvedValue({ ...taskFixture, status: "REPORT_DRAFT" });
    (reportApi.reviewResult as unknown as Mock).mockResolvedValue({
      score: 42.5, allowed_actions: ["REVISE_AND_RESUBMIT"],
      rounds: [{ review_id: "review-1", round_no: 1, status: "DECIDED", decision: { decision: "REJECT", score: 42.5, feedback: "请补充实验分析" }, scores: null, annotations: [] }],
    });
    renderTaskDetail();
    expect(await screen.findByText("请补充实验分析")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "修改报告并重新提交" })).toHaveAttribute("href", "/experiments/task-1/workbench");
  });

  it("服务端 blockers 时展示阻塞说明且不显示进入工作台按钮", async () => {
    (taskApi.detail as unknown as Mock).mockResolvedValue({
      ...taskFixture,
      status: "ASSIGNED",
      blockers: [{ reason: "先修实验尚未完成" }],
      allowed_actions: [],
    });
    renderTaskDetail();
    expect(await screen.findByText("先修实验尚未完成")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "进入实验工作台" })).not.toBeInTheDocument();
  });

  it("进入工作台会携带 row_version 作 If-Match 并写入本地会话", async () => {
    (taskApi.enter as unknown as Mock).mockReset().mockResolvedValue({
      task: { ...taskFixture, status: "IN_PROGRESS" },
      session: { public_id: "sess-1", workspace_token: "tok-1", expires_at: "2026-10-21T12:00:00Z", status: "ACTIVE" },
    });
    renderTaskDetail();
    (await screen.findByRole("button", { name: "进入实验工作台" })).click();
    await waitFor(() => expect(taskApi.enter).toHaveBeenCalled());
    expect(taskApi.enter).toHaveBeenCalledWith("task-1", "v-1", "task-enter-task-1-v-1");
    const stored = sessionStorage.getItem("edu.workspace.task-1");
    expect(stored).toBeTruthy();
    expect(JSON.parse(stored as string)).toMatchObject({ session_id: "sess-1", token: "tok-1" });
  });

  it("开始任务同样携带 row_version 作 If-Match", async () => {
    (taskApi.detail as unknown as Mock).mockResolvedValue({
      ...taskFixture,
      status: "ASSIGNED",
      allowed_actions: ["enter", "start"],
    });
    (taskApi.start as unknown as Mock).mockReset().mockResolvedValue({ ...taskFixture, status: "PROVISIONING" });
    renderTaskDetail();
    (await screen.findByRole("button", { name: "进入实验工作台" })).click();
    await waitFor(() => expect(taskApi.start).toHaveBeenCalled());
    expect(taskApi.start).toHaveBeenCalledWith("task-1", "v-1", "task-start-task-1-v-1");
  });

  it("重试任务使用带行版本的幂等键", async () => {
    (taskApi.detail as unknown as Mock).mockReset().mockResolvedValue({
      ...taskFixture,
      status: "FAILED",
      allowed_actions: ["retry", "extension"],
      current_failure: { code: "IMAGE_PREPARE_FAILED", message: "镜像准备失败", retryable: true },
    });
    (taskApi.retry as unknown as Mock).mockReset().mockResolvedValue({ ...taskFixture, status: "PROVISIONING" });
    renderTaskDetail();
    (await screen.findByRole("button", { name: "重试任务" })).click();
    (await screen.findByRole("button", { name: "确认" })).click();
    await waitFor(() => expect(taskApi.retry).toHaveBeenCalled());
    expect(taskApi.retry).toHaveBeenCalledWith("task-1", "v-1", "task-retry-task-1-v-1");
  });

  it("重试已受理但任务未进入准备状态时收起启动弹窗", async () => {
    const failedFixture = {
      ...taskFixture,
      status: "FAILED",
      allowed_actions: ["retry", "extension"],
      current_failure: { code: "IMAGE_PREPARE_FAILED", message: "镜像准备失败", retryable: true },
    };
    /* 挂起重试后的任务详情刷新,模拟详情仍返回 FAILED 的重放/未迁移动作 */
    let release!: (value: typeof failedFixture) => void;
    const pendingDetail = new Promise<typeof failedFixture>((resolve) => { release = resolve; });
    (taskApi.detail as unknown as Mock).mockReset()
      .mockResolvedValueOnce(failedFixture)
      .mockImplementation(() => pendingDetail);
    (taskApi.retry as unknown as Mock).mockReset().mockResolvedValue({ ...failedFixture, status: "PROVISIONING" });
    renderTaskDetail();
    (await screen.findByRole("button", { name: "重试任务" })).click();
    (await screen.findByRole("button", { name: "确认" })).click();
    expect(await screen.findByText("正在提交开通请求…")).toBeInTheDocument();
    release(failedFixture);
    /* 任务详情仍为 FAILED 且无装载进度,弹窗应自动收起而不是无限等待 */
    await waitFor(() => expect(screen.queryByText("正在提交开通请求…")).not.toBeInTheDocument());
  });
});
