import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { apiRequestWithMetadata } from "./legacy/api-client";
import { UsersPage } from "./apiPages";

vi.mock("./legacy/api-client", () => ({
  ApiError: class extends Error {},
  RequestIntent: class { key = "test-key"; },
  apiRequestWithMetadata: vi.fn(),
}));

it("refreshes the user list after an asynchronous successful create", async () => {
  let created = false;
  vi.mocked(apiRequestWithMetadata).mockImplementation(async (_path, init) => {
    if (init?.method === "POST") { await Promise.resolve(); created = true; }
    return { payload: { data: created ? [{ public_id: "new-user", email: "qa@example.edu", display_name: "QA", username: "qa", account_status: "ACTIVE", row_version: 1 }] : [] } } as never;
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><UsersPage /></QueryClientProvider>);
  fireEvent.click(await screen.findByText("新建账号"));
  fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "qa@example.edu" } });
  fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "qa" } });
  fireEvent.change(screen.getByLabelText("展示名称"), { target: { value: "QA" } });
  fireEvent.change(screen.getByLabelText("初始密码"), { target: { value: "ValidPassword!234" } });
  fireEvent.click(screen.getByRole("button", { name: "创建" }));
  await waitFor(() => expect(screen.getByText("qa@example.edu")).toBeInTheDocument());
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "创建" })).not.toBeInTheDocument();
  client.clear();
});
