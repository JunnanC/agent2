import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { timetableApi, type TimetableData } from "@edu/api-client";
import { StudentTimetable } from "./student-timetable";

vi.mock("@edu/api-client", () => ({ timetableApi: { retrieve: vi.fn() } }));
const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
afterEach(() => { cleanup(); client.clear(); });

it("按学期显示同名教学班的独立链接及单双周", async () => {
  const terms = [{ public_id: "now", code: "NOW", name: "当前学期" }, { public_id: "past", code: "PAST", name: "往期学期" }];
  const classes = ["DS-01", "DS-02"].map((code) => ({ course_id: code, course_code: code, course_title: "数据结构", instructor_name: "周老师" }));
  const current: TimetableData = {
    term: terms[0]!, terms, classes,
    schedules: [{ ...classes[0]!, source: "PLATFORM", class_type: "TEACHING", term_id: "now", weekday: 3,
      start_period: 3, end_period: 4, week_start: 2, week_end: 16, week_parity: "EVEN", classroom: "B202" }],
  };
  vi.mocked(timetableApi.retrieve).mockImplementation(async (query) => query?.term_id === "past"
    ? { ...current, term: terms[1]!, classes: [{ ...classes[0]!, course_id: "old-class" }], schedules: [] } : current);
  render(<MemoryRouter><QueryClientProvider client={client}><StudentTimetable /></QueryClientProvider></MemoryRouter>);
  expect((await screen.findAllByRole("link", { name: "数据结构" })).map((link) => link.getAttribute("href")))
    .toEqual(["/courses/DS-01", "/courses/DS-02"]);
  expect(screen.getByText(/双周.*B202/)).toBeInTheDocument();
  expect(screen.queryByLabelText(/导入个人课表/)).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("学期"), { target: { value: "past" } });
  await waitFor(() => expect(screen.getByRole("link", { name: "数据结构" })).toHaveAttribute("href", "/courses/old-class"));
  expect(screen.getByText("暂无排课")).toBeInTheDocument();
});
