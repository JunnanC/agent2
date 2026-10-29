import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import type { Mock } from "vitest";

vi.mock("@edu/api-client", () => ({
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

import { taskApi } from "@edu/api-client";
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
  });

  it("正常渲染任务标题、进度与操作区", async () => {
    renderTaskDetail();
    expect(await screen.findByText("Linux 网络故障排查", { selector: "b" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "进入实验工作台" })).toBeInTheDocument();
    expect(screen.getAllByText("进行中").length).toBeGreaterThan(0);
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
