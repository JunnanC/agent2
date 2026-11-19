import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { StudentTimetable } from "./student-timetable";

vi.mock("@edu/api-client", () => ({
  timetableApi: {
    retrieve: vi.fn(async () => ({
      term: { name: "Legacy Current Term" },
      schedules: [
        { source: "PLATFORM", course_id: "course-1", course_title: "数据结构与算法", weekday: 1, start_period: 1, end_period: 2, week_start: 1, week_end: 16, classroom: "东二 305", instructor_name: "张明远" },
        { source: "PLATFORM", course_id: "course-1", course_title: "数据结构与算法", weekday: 3, start_period: 3, end_period: 4, week_start: 1, week_end: 16, classroom: "东二 305", instructor_name: "张明远" },
      ],
    })),
    imports: vi.fn(async () => ({ rows: [] })),
  },
}));
afterEach(cleanup);

it("同一门课的多个上课时段合并为一行，并隐藏旧学期英文名", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><StudentTimetable /></ToastProvider></QueryClientProvider>);
  expect(await screen.findByText("数据结构与算法")).toBeInTheDocument();
  expect(screen.getAllByText("数据结构与算法")).toHaveLength(1);
  expect(screen.getByText(/周一 第 1—2 节/)).toBeInTheDocument();
  expect(screen.getByText(/周三 第 3—4 节/)).toBeInTheDocument();
  expect(screen.getByText("当前学期")).toBeInTheDocument();
  expect(screen.queryByText("Legacy Current Term")).not.toBeInTheDocument();
  client.clear();
});
