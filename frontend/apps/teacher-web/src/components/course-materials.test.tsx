import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { request } from "@edu/auth-client";
import { ToastProvider } from "@edu/ui";
import { CourseMaterials } from "./course-materials";

vi.mock("@edu/api-client", () => ({ teachingApi: {
  courseResource: vi.fn(async (_courseId: string, resource: string) => ({ rows: resource === "chapters" ? [{ public_id: "ch1", title: "第一章", status: "PUBLISHED", position: 1 }] : [{ public_id: "m1", title: "实验指导", current_version_id: "mv1", version_status: "DRAFT" }] })),
} }));
vi.mock("@edu/auth-client", async (original) => ({ ...await original<typeof import("@edu/auth-client")>(), request: vi.fn(async (path: string) => ({ data: path.endsWith("/versions") ? [{ public_id: "mv1", row_version: 3 }] : { public_id: "m2" } })) }));
afterEach(cleanup);
it("saves course material with its chapter then publishes the current version with If-Match", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><CourseMaterials courseId="c1" /></ToastProvider></QueryClientProvider>);
  await screen.findByRole("option", { name: "第一章" });
  fireEvent.change(screen.getByLabelText("所属章节"), { target: { value: "ch1" } });
  fireEvent.change(screen.getByLabelText("材料标题"), { target: { value: "课程说明" } });
  fireEvent.change(screen.getByLabelText("材料正文"), { target: { value: "实验报告要求" } });
  fireEvent.click(screen.getByRole("button", { name: "保存材料草稿" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/teaching/courses/c1/materials", expect.objectContaining({ body: { title: "课程说明", chapter_id: "ch1", kind: "TEXT", text_content: "实验报告要求" } })));
  fireEvent.click(screen.getByRole("button", { name: "发布材料 实验指导" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/teaching/courses/c1/material-versions/mv1/published", expect.objectContaining({ ifMatch: 3, idempotencyKey: expect.any(String) })));
  client.clear();
});
