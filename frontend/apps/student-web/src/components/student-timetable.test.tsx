import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { StudentTimetable } from "./student-timetable";

vi.mock("@edu/api-client", () => ({
  studentApi: { myEnrollments: vi.fn(async () => ({ rows: [
    { public_id: "en-1", course_id: "course-1", course_title: "未排课的课程", status: "ACTIVE" },
    { public_id: "en-2", course_id: "course-2", course_title: "已有排课的课程", status: "ACTIVE" },
  ] })) },
  timetableApi: {
    retrieve: vi.fn(async () => ({ term: { name: "当前学期" }, schedules: [{ source: "PLATFORM", course_id: "course-2", course_title: "已有排课的课程", weekday: 1, start_period: 1, end_period: 2 }] })),
    imports: vi.fn(async () => ({ rows: [] })),
  },
}));
afterEach(cleanup);
it("shows joined courses without scheduled times and does not duplicate scheduled courses", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><StudentTimetable /></ToastProvider></QueryClientProvider>);
  expect(await screen.findByText("未排课的课程")).toBeInTheDocument();
  expect(screen.getByText("待排课")).toBeInTheDocument();
  expect(screen.getAllByText("已有排课的课程")).toHaveLength(1);
  expect(screen.getByText(/周一 第 1—2 节/)).toBeInTheDocument();
  client.clear();
});
