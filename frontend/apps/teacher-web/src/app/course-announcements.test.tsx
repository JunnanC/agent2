import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { teachingApi } from "@edu/api-client";
import { ToastProvider } from "@edu/ui";

import { CourseAnnouncements } from "./course-layout";

vi.mock("@edu/api-client", () => ({
  teachingApi: {
    courseResource: vi.fn(),
    createAnnouncement: vi.fn(),
    publishAnnouncement: vi.fn(),
  },
}));

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(teachingApi.courseResource).mockResolvedValue({
    rows: [], page: 1, pageSize: 20, total: 0,
  } as never);
  vi.mocked(teachingApi.createAnnouncement).mockResolvedValue({
    public_id: "ann-1", title: "随堂练习截止", body: "请在 11 月 19 日前提交", row_version: "3",
  } as never);
  vi.mocked(teachingApi.publishAnnouncement).mockResolvedValue({} as never);
});

it("创建公告后立即发布，并清空表单", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter>
    <CourseAnnouncements courseId="course-1" />
  </MemoryRouter></ToastProvider></QueryClientProvider>);

  expect(await screen.findByText(/还没有公告/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("公告标题"), { target: { value: "随堂练习截止" } });
  fireEvent.change(screen.getByLabelText("公告正文"), { target: { value: "请在 11 月 19 日前提交" } });
  fireEvent.click(screen.getByRole("button", { name: "发布公告" }));

  await waitFor(() => expect(teachingApi.createAnnouncement).toHaveBeenCalledWith("course-1", {
    title: "随堂练习截止", body: "请在 11 月 19 日前提交", pinned: false,
  }));
  await waitFor(() => expect(teachingApi.publishAnnouncement).toHaveBeenCalledWith("course-1", "ann-1", "3"));
  await waitFor(() => expect(screen.getByLabelText("公告标题")).toHaveValue(""));
});
