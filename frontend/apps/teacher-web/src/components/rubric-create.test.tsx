import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { request } from "@edu/auth-client";
import { ToastProvider } from "@edu/ui";
import { RubricCreate } from "./rubric-create";

vi.mock("@edu/auth-client", async (original) => ({ ...await original<typeof import("@edu/auth-client")>(), request: vi.fn(async (path: string) => ({ data: path.endsWith("/rubrics") ? { public_id: "r1" } : { public_id: "v1", row_version: 2 } })) }));
afterEach(cleanup);
it("creates a rubric version with criteria and publishes it for experiment selection", async () => {
  const onCreated = vi.fn();
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><ToastProvider><RubricCreate courseId="c1" onCreated={onCreated} /></ToastProvider></QueryClientProvider>);
  fireEvent.click(screen.getByRole("button", { name: "新建评分表" }));
  fireEvent.change(screen.getByLabelText("评分表名称"), { target: { value: "实验评分" } });
  fireEvent.click(screen.getByRole("button", { name: "创建并发布评分表" }));
  await waitFor(() => expect(onCreated).toHaveBeenCalledOnce());
  expect(request).toHaveBeenCalledWith("/teaching/courses/c1/rubrics/r1/versions", expect.objectContaining({ body: expect.objectContaining({ total_score: 100, criteria: [{ title: "实验完成情况", max_score: 100, position: 1, weight_basis_points: 10000 }] }) }));
  expect(request).toHaveBeenCalledWith("/teaching/courses/c1/rubric-versions/v1/publish", expect.objectContaining({ ifMatch: 2 }));
  client.clear();
});
