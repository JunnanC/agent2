import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { request } from "@edu/auth-client";
import { ToastProvider } from "@edu/ui";
import { CourseMaterials } from "./course-materials";

vi.mock("@edu/api-client", () => ({ teachingApi: {
  courseResource: vi.fn(async (_courseId: string, resource: string) => ({ rows: resource === "chapters" ? [{ public_id: "ch1", title: "第一章", status: "PUBLISHED", position: 1 }] : [{ public_id: "m1", title: "实验指导", chapter_id: "ch1", current_version_id: "mv1", version_status: "DRAFT" }] })),
} }));
vi.mock("@edu/auth-client", async (original) => ({ ...await original<typeof import("@edu/auth-client")>(), request: vi.fn(async (path: string) => ({ data: path.endsWith("/versions") ? [{ public_id: "mv1", row_version: 3 }] : { public_id: "m2" } })) }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
it("saves course material with its chapter then publishes the current version with If-Match", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ToastProvider><CourseMaterials courseId="c1" /></ToastProvider></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "第一章" }));
  fireEvent.change(screen.getByLabelText("材料名称"), { target: { value: "课程说明" } });
  fireEvent.change(screen.getByLabelText("附件"), { target: { files: [new File(["guide"], "guide.txt", {type:"text/plain"})] } });
  fireEvent.click(screen.getByRole("button", { name: "保存材料草稿" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/teaching/courses/c1/chapters/ch1/materials/upload", expect.objectContaining({ body: expect.any(FormData) })));
  fireEvent.click(screen.getByRole("button", { name: "发布材料 实验指导" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/teaching/courses/c1/material-versions/mv1/published", expect.objectContaining({ ifMatch: 3, idempotencyKey: expect.any(String) })));
  client.clear();
});

it("saves chapter explanation as a draft without automatically publishing", async () => {
  const client = new QueryClient({defaultOptions:{queries:{retry:false}}});
  render(<QueryClientProvider client={client}><ToastProvider><CourseMaterials courseId="c1" /></ToastProvider></QueryClientProvider>);
  await screen.findByRole("button", {name:"第一章"});
  fireEvent.change(screen.getByLabelText("章节名称"), {target:{value:"环境准备"}});
  fireEvent.change(screen.getByLabelText("章节说明"), {target:{value:"检查环境，熟悉平台"}});
  fireEvent.click(screen.getByRole("button", {name:"保存章节草稿"}));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/teaching/courses/c1/chapters", expect.objectContaining({method:"POST",body:expect.objectContaining({title:"环境准备",content:"检查环境，熟悉平台"})})));
  expect(vi.mocked(request).mock.calls.some(([path]) => path.endsWith("/published"))).toBe(false);
  expect(screen.queryByLabelText("所属章节")).not.toBeInTheDocument();
  client.clear();
});
