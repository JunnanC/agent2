import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { platformApi } from "@edu/api-client";
import { StudentImport } from "./StudentImport";
vi.mock("@edu/api-client", () => ({ platformApi: { importStudents: vi.fn() } }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
it("retries the same batch key after a lost response and displays per-row outcomes without credentials", async () => {
  const done = vi.fn();
  const csv = "student_number,email,display_name,password\n2026001,s@example.edu,学生,Secret-2026!abc";
  const file = new File([csv], "students.csv", { type: "text/csv" });
  Object.defineProperty(file, "text", { value: async () => csv });
  vi.mocked(platformApi.importStudents).mockRejectedValueOnce(new Error("连接中断"));
  vi.mocked(platformApi.importStudents).mockResolvedValueOnce({ rows: [
    { row_number: 2, student_number: "2026001", status: "CREATED", user_id: "student" },
    { row_number: 3, student_number: "2026001", status: "FAILED", error: "duplicate_identifier" },
  ] });
  render(<StudentImport onComplete={done} />);
  fireEvent.click(screen.getByText("批量创建学生账号"));
  fireEvent.change(screen.getByLabelText("学生账号 CSV"), { target: { files: [file] } });
  await screen.findByText(/已读取/);
  fireEvent.click(screen.getByRole("button", { name: "创建学生账号" }));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "创建学生账号" }));
  await waitFor(() => expect(done).toHaveBeenCalledOnce());
  expect(platformApi.importStudents).toHaveBeenNthCalledWith(2, csv, vi.mocked(platformApi.importStudents).mock.calls[0]?.[1]);
  expect(screen.getByText((_content, element) => element?.tagName === "P" && (element.textContent ?? "").includes("已创建 1 个账号"))).toBeInTheDocument();
  expect(screen.getByText("学号或用户名已存在")).toBeInTheDocument();
  expect(screen.queryByText(/Secret-2026/)).not.toBeInTheDocument();
});
