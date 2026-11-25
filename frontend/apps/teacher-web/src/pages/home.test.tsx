import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { assessmentPartsApi, labAssessmentApi, teachingApi, timetableApi } from "@edu/api-client";
import { Home } from "./home";
import { TeachingAgenda } from "@/components/teaching-agenda";

vi.mock("@edu/api-client", () => ({
  teachingApi: { courses: vi.fn(), publications: vi.fn() },
  assessmentPartsApi: { reports: vi.fn() },
  labAssessmentApi: { releaseStatus: vi.fn() },
  timetableApi: { teaching: vi.fn() },
}));

vi.mock("@/lib/teaching-agenda", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/teaching-agenda")>(),
  schoolToday: () => "2026-11-24",
}));

const autumn = { public_id: "fall", code: "FALL", name: "秋季学期", calendar: { starts_on: "2026-09-07", ends_on: "2026-12-27" } };
const spring = { public_id: "spring", code: "SPRING", name: "春季学期", calendar: { starts_on: "2026-03-04", ends_on: "2026-06-18" } };
const list = <T,>(rows: T[]) => ({ rows, page: 1, pageSize: 20, total: rows.length });

function Location() {
  return <output>{useLocation().search}</output>;
}

it("shows the authorized term's report and new enrollment todos and keeps the term in the URL", async () => {
  vi.mocked(timetableApi.teaching).mockImplementation(async (filter) => ({
    term: filter?.term_id === "spring" ? spring : autumn, terms: [autumn, spring], schedules: [], classes: [],
  }));
  vi.mocked(teachingApi.courses).mockResolvedValue(list([
    { public_id: "ds01", title: "数据结构", term_id: "fall", active_enrollment_count: 8, pending_enrollments: 2 },
    { public_id: "old", title: "往期课程", term_id: "spring", active_enrollment_count: 3, pending_enrollments: 0 },
  ]) as never);
  vi.mocked(teachingApi.publications).mockImplementation(async (courseId) => list(courseId === "ds01" ? [
    { public_id: "lab2", status: "PUBLISHED", title: "栈与队列", direct_assessment: true },
    { public_id: "lab1", status: "PUBLISHED", title: "线性表", template_version_id: "legacy" },
  ] : []) as never);
  vi.mocked(labAssessmentApi.releaseStatus).mockResolvedValue({
    grades_published_at: null, deadline: "2020-01-01", pending_reports: 3, pending_runs: 0, open_redos: 0,
  });
  vi.mocked(assessmentPartsApi.reports).mockResolvedValue([
    { status: "RETURNED" }, { status: "GRADED" }, { status: "SUBMITTED", review_status: "READY" },
  ] as never);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><Home /><Location /></MemoryRouter></QueryClientProvider>);
  expect(await screen.findByRole("heading", { name: "教学日程" })).toBeInTheDocument();
  expect(await screen.findByRole("link", { name: /批阅实验报告.*栈与队列.*3 份/ }))
    .toHaveAttribute("href", "/courses/ds01/publishing/lab2/reviews?tab=reports");
  expect(screen.getByRole("link", { name: /审核入班申请.*2 人/ })).toHaveAttribute("href", "/courses/ds01/enrollments");
  expect(screen.queryByText("数据结构 · 线性表")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "周课表" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("第 12 周")).toBeInTheDocument();
  expect(screen.getByText("11/24").parentElement).toHaveAttribute("aria-current", "date");
  fireEvent.change(screen.getByRole("combobox", { name: "学期" }), { target: { value: "spring" } });
  expect(await screen.findByText("?term=spring")).toBeInTheDocument();
  expect(await screen.findByRole("link", { name: /往期课程/ })).toBeInTheDocument();
  expect(screen.getByText("第 16 周")).toBeInTheDocument();
  expect(screen.queryByText("批阅实验报告")).not.toBeInTheDocument();
  client.clear();
});

it("restores the viewed week per term and distinguishes selected day from today in the grid", () => {
  const first = { id: "fall", label: "秋季", calendar: autumn.calendar };
  const second = { id: "spring", label: "春季", calendar: spring.calendar };
  const course = { id: "ds01", title: "数据结构 · 01 班" };
  const noop = () => {};
  const view = (term: typeof first | typeof second) => <MemoryRouter><TeachingAgenda term={term} terms={[first, second]}
    classes={[course]} today="2026-11-24" todos={[]} onTerm={noop} onImport={noop} onEnvironments={noop}
    slots={[{ id: "1", course, weekday: 1, start: 3, end: 4, classroom: "A103", weekStart: 1, weekEnd: 16, parity: "EVEN" }]} /></MemoryRouter>;
  const { rerender } = render(view(first));
  expect(screen.getByRole("button", { name: "本周" })).toBeDisabled();
  const month = screen.getByRole("region", { name: "按日期查看授课" });
  fireEvent.click(within(month).getByRole("button", { name: "2026-11-25" }));
  expect(screen.getByRole("button", { name: "周课表" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("11/25").parentElement).toHaveClass("selected");
  expect(screen.getByText("11/24").parentElement).toHaveAttribute("aria-current", "date");
  fireEvent.click(screen.getByRole("button", { name: "日程" }));
  fireEvent.click(within(month).getByRole("button", { name: "2026-11-28" }));
  expect(screen.getByText("这一天没有排课。")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "周课表" }));
  fireEvent.click(screen.getByRole("button", { name: "上一周" }));
  expect(screen.getByText("第 11 周")).toBeInTheDocument();
  expect(screen.getByText("所选教学周没有排课。")).toBeInTheDocument();
  rerender(view(second));
  expect(screen.getByRole("button", { name: "下一周" })).toBeDisabled();
  expect(screen.getByText("6/18").parentElement).toHaveClass("selected");
  expect(screen.queryByRole("button", { name: "本周" })).not.toBeInTheDocument();
  rerender(view(first));
  expect(screen.getByText("第 11 周")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "本周" }));
  expect(screen.getByText("第 12 周")).toBeInTheDocument();
});

it("keeps the month and dated week available for legacy courses with recurring slots", () => {
  const term = { id: "legacy", label: "旧学期" };
  const course = { id: "ds01", title: "数据结构" };
  const noop = () => {};
  render(<MemoryRouter><TeachingAgenda term={term} terms={[term]} classes={[course]} todos={[]} today="2026-11-24"
    onTerm={noop} onImport={noop} onEnvironments={noop}
    slots={[{ id: "1", course, weekday: 1, start: 3, end: 4, classroom: "A103", weekStart: 1, weekEnd: 16, parity: "EVEN" }]} /></MemoryRouter>);
  const month = screen.getByRole("region", { name: "按日期查看授课" });
  expect(within(month).getByRole("button", { name: "2026-11-24" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(within(month).getByRole("button", { name: "下月" }));
  fireEvent.click(within(month).getByRole("button", { name: "2026-12-01" }));
  expect(screen.getByText("12/1").parentElement).toHaveClass("selected");
  expect(screen.getByRole("link", { name: /双周/ })).toHaveAttribute("href", "/courses/ds01");
  fireEvent.click(screen.getByRole("button", { name: "本周" }));
  expect(screen.getByText("11/24").parentElement).toHaveAttribute("aria-current", "date");
});
