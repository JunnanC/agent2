import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { authFlow } from "@edu/auth-client";
import { Register } from "./register";

vi.mock("@edu/auth-client", () => ({
  authFlow: { register: vi.fn(), verifyEmail: vi.fn() },
}));

it("submits student registration and shows the email step", async () => {
  vi.mocked(authFlow.register).mockResolvedValue();
  render(<MemoryRouter initialEntries={["/register"]}><Register /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "student@example.edu" } });
  fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "student" } });
  fireEvent.change(screen.getByLabelText("姓名"), { target: { value: "Student" } });
  fireEvent.change(screen.getByLabelText("密码"), { target: { value: "ValidPassword!234" } });
  fireEvent.click(screen.getByRole("button", { name: "发送验证邮件" }));
  await waitFor(() => expect(authFlow.register).toHaveBeenCalledWith({
    email: "student@example.edu",
    username: "student",
    display_name: "Student",
    password: "ValidPassword!234",
  }));
  expect(await screen.findByText(/验证邮件已发送/)).toBeInTheDocument();
});
