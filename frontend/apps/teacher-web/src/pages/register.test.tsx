import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { authFlow } from "@edu/auth-client";
import { Register } from "./register";

vi.mock("@edu/auth-client", () => ({
  authFlow: { register: vi.fn(), verifyEmail: vi.fn() },
}));

it("verifies a teacher email and explains the review state", async () => {
  vi.mocked(authFlow.verifyEmail).mockResolvedValue();
  render(<MemoryRouter initialEntries={["/verify-email?token=sample-token"]}><Register /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "完成验证" }));
  await waitFor(() => expect(authFlow.verifyEmail).toHaveBeenCalledWith("sample-token"));
  expect(await screen.findByText(/教师资格待管理员审核/)).toBeInTheDocument();
});
