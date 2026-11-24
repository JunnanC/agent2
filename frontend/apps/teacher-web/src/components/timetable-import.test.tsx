import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { timetableApi, type TimetableImport as Job } from "@edu/api-client";
import { ToastProvider } from "@edu/ui";
import { TimetableImport } from "./timetable-import";

vi.mock("@edu/api-client", () => ({ timetableApi: {
  imports: vi.fn(), importJob: vi.fn(), upload: vi.fn(), updateMapping: vi.fn(), confirm: vi.fn(),
} }));
const clients: QueryClient[] = [];
function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><ToastProvider><TimetableImport termId="term-1" /></ToastProvider></QueryClientProvider>);
  return client;
}
beforeEach(() => vi.resetAllMocks());
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });
const list = (rows: Job[]) => ({ rows, total: rows.length, page: 1, pageSize: 20 });

describe("课表导入", () => {
  it("显示具体错误行并阻止带错误的课表确认", async () => {
    const job = { public_id: "job-error", status: "READY", filename: "invalid.xlsx", fields: [], headers: [], mapping: {}, summary: { total: 1, errors: 1 }, row_errors: [{ row_no: 3, code: "weekday_required" }] } as unknown as Job;
    vi.mocked(timetableApi.imports).mockResolvedValue(list([job]));
    vi.mocked(timetableApi.importJob).mockResolvedValue(job);
    show();
    const imports = await screen.findByLabelText("最近的导入");
    fireEvent.change(imports, { target: { value: "job-error" } });
    expect(await screen.findByText("第 3 行：无法识别星期")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认导入" })).toBeDisabled();
  });

  it("修改映射后先保存再确认，异步完成后刷新课表", async () => {
    const job: Job = { public_id: "job-1", kind: "TEACHER", status: "READY", filename: "schedule.xlsx", term_id: "term-1", row_version: 1,
      fields: [{ key: "course_title", label: "课程名称" }, { key: "weekday", label: "星期" }, { key: "start_period", label: "开始节次" }, { key: "end_period", label: "结束节次" }],
      headers: ["课程", "名称", "星期", "开始", "结束"], mapping: { course_code: "课程", course_title: "课程", weekday: "星期", start_period: "开始", end_period: "结束" }, summary: { total: 1, valid: 1, errors: 0 }, row_errors: [],
    };
    vi.mocked(timetableApi.imports).mockResolvedValue(list([job]));
    vi.mocked(timetableApi.upload).mockResolvedValue(job);
    vi.mocked(timetableApi.importJob).mockResolvedValue(job);
    vi.mocked(timetableApi.updateMapping).mockResolvedValue({ ...job, mapping: { ...job.mapping, course_title: "名称" } });
    vi.mocked(timetableApi.confirm).mockResolvedValue({ ...job, status: "RUNNING" });
    const client = show();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const workbook = new File(["xlsx"], "schedule.xlsx");
    fireEvent.change(screen.getByLabelText(/导入教学班课表/), { target: { files: [workbook] } });
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
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["teaching", "timetable"] });
  });
});
