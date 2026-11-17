import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { request } from "@edu/auth-client";
import { ToastProvider } from "@edu/ui";
import { CourseMaterials } from "./course-materials";

type Chapter = { public_id: string; title: string; status: string; position: number; content: string; row_version: number };
type Material = { public_id: string; title: string; chapter_id: string; kind: string; current_version_id: string; version_status: string; object_asset_id: string; asset_name: string; size_bytes: number };
const state = vi.hoisted(() => ({ chapters: [] as Chapter[], materials: [] as Material[], failure: "" }));
vi.mock("@edu/api-client", () => ({ teachingApi: {
  courseResource: vi.fn(async (_courseId: string, resource: string) => ({ rows: resource === "chapters" ? [...state.chapters] : [...state.materials] })),
}, fileApi: { createDownloadGrant: vi.fn() } }));
vi.mock("@edu/auth-client", async original => ({
  ...await original<typeof import("@edu/auth-client")>(),
  request: vi.fn(async (path: string, options?: { method?: string; body?: Record<string, unknown> }) => {
    if (state.failure) throw new Error(state.failure);
    if (path.endsWith("chapter-drafts/generate")) return { data: { content: "AI 草稿内容，需教师确认" } };
    if (path.endsWith("/versions")) return { data: [{ public_id: "mv1", row_version: 3, status: "DRAFT" }] };
    if (path.endsWith("/chapters")) {
      const chapter = { public_id: "ch4", status: "DRAFT", row_version: 1, ...options?.body } as Chapter;
      state.chapters.push(chapter); return { data: chapter };
    }
    const chapterMatch = path.match(/\/chapters\/(ch\d+)(?:\/(published|withdrawn))?$/);
    if (chapterMatch) {
      const index = state.chapters.findIndex(row => row.public_id === chapterMatch[1]);
      const chapter = { ...state.chapters[index], ...options?.body,
        ...(chapterMatch[2] ? { status: chapterMatch[2] === "published" ? "PUBLISHED" : "WITHDRAWN" } : {}),
        row_version: (state.chapters[index]?.row_version ?? 0) + 1 } as Chapter;
      state.chapters[index] = chapter; return { data: chapter };
    }
    return { data: { public_id: "uploaded" } };
  }),
}));
const clients: QueryClient[] = [];
beforeEach(() => {
  state.chapters = [
    { public_id: "ch1", title: "第一章 环境准备", status: "DRAFT", position: 1, content: "第一章说明", row_version: 1 },
    { public_id: "ch2", title: "第二章 命令练习", status: "PUBLISHED", position: 2, content: "第二章说明", row_version: 2 },
    { public_id: "ch3", title: "第三章 课程实验", status: "DRAFT", position: 3, content: "第三章说明", row_version: 1 },
  ];
  state.materials = [{ public_id: "m1", title: "实验指导", chapter_id: "ch1", kind: "FILE", current_version_id: "mv1", version_status: "DRAFT", object_asset_id: "asset1", asset_name: "实验指导.pdf", size_bytes: 1024 }];
  state.failure = ""; vi.clearAllMocks();
});
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); });
async function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  render(<QueryClientProvider client={client}><ToastProvider><CourseMaterials courseId="c1" /></ToastProvider></QueryClientProvider>);
  await screen.findByRole("button", { name: "第一章 环境准备" });
  await waitFor(() => expect(screen.getByLabelText("章节名称")).toHaveValue("环境准备"));
}

it("renders independent chapter/material modules and only two material inputs", async () => {
  await show();
  const chapters = screen.getByRole("heading", { name: "课程章节" }).closest("section")!;
  const materials = screen.getByRole("heading", { name: "学习材料" }).closest("section")!;
  expect(chapters).not.toContainElement(materials);
  expect(chapters.parentElement).toBe(materials.parentElement);
  expect(within(screen.getByRole("form", { name: "添加学习材料" })).getAllByRole("textbox")).toHaveLength(1);
  expect(screen.getByRole("form", { name: "添加学习材料" }).querySelectorAll("input")).toHaveLength(2);
});

it("automatically creates chapter four while the teacher enters only its name", async () => {
  await show();
  fireEvent.click(screen.getByRole("button", { name: "新建章节" }));
  expect(screen.getByTestId("chapter-prefix")).toHaveTextContent("第四章");
  fireEvent.change(screen.getByLabelText("章节名称"), { target: { value: "云教学实验" } });
  fireEvent.change(screen.getByLabelText(/章节说明/), { target: { value: "本章实验介绍" } });
  fireEvent.click(screen.getByRole("button", { name: "保存章节草稿" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/teaching/courses/c1/chapters", expect.objectContaining({ method: "POST", body: { title: "第四章 云教学实验", content: "本章实验介绍", summary: "本章实验介绍", position: 4 } })));
  expect(screen.getByLabelText("章节名称")).toHaveValue("云教学实验");
  expect(vi.mocked(request).mock.calls.some(([path]) => path.endsWith("/published"))).toBe(false);
});

it("uses the maximum existing position and keeps original ordinals when editing", async () => {
  state.chapters = state.chapters.filter(row => row.position !== 2);
  await show();
  fireEvent.click(screen.getByRole("button", { name: "新建章节" }));
  expect(screen.getByTestId("chapter-prefix")).toHaveTextContent("第四章");
  fireEvent.click(screen.getByRole("button", { name: "第三章 课程实验" }));
  expect(screen.getByLabelText("章节名称")).toHaveValue("课程实验");
  expect(screen.getByTestId("chapter-prefix")).toHaveTextContent("第三章");
  fireEvent.change(screen.getByLabelText("章节名称"), { target: { value: "云教学实验" } });
  fireEvent.click(screen.getByRole("button", { name: "保存章节草稿" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/teaching/courses/c1/chapters/ch3", expect.objectContaining({ method: "PATCH", ifMatch: 1, body: expect.objectContaining({ title: "第三章 云教学实验" }) })));
});

it("switches the material scope independently and uploads to the selected chapter", async () => {
  await show();
  fireEvent.change(screen.getByLabelText("学习材料所在章节"), { target: { value: "ch2" } });
  expect(screen.getByLabelText("章节名称")).toHaveValue("环境准备");
  fireEvent.change(screen.getByLabelText("材料名称"), { target: { value: "课程说明" } });
  fireEvent.change(screen.getByLabelText("附件"), { target: { files: [new File(["guide"], "guide.txt", { type: "text/plain" })] } });
  fireEvent.click(screen.getByRole("button", { name: "保存材料草稿" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/teaching/courses/c1/chapters/ch2/materials/upload", expect.objectContaining({ body: expect.any(FormData) })));
  const body = vi.mocked(request).mock.calls.find(([path]) => path.endsWith("/materials/upload"))?.[1]?.body as FormData;
  expect(body.get("title")).toBe("课程说明");
  expect((body.get("file") as File).name).toBe("guide.txt");
});

it("publishes chapter content separately and material publishing uses its version", async () => {
  await show();
  expect(screen.getByRole("button", { name: "发布材料 实验指导" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/章节说明/), { target: { value: "修改后的说明" } });
  fireEvent.click(screen.getByRole("button", { name: "发布章节" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/teaching/courses/c1/chapters/ch1/published", expect.objectContaining({ ifMatch: 2 })));
  await waitFor(() => expect(screen.getByRole("button", { name: "发布材料 实验指导" })).toBeEnabled());
  expect(vi.mocked(request).mock.calls.some(([path]) => path.includes("material-versions"))).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "发布材料 实验指导" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/teaching/courses/c1/material-versions/mv1/published", expect.objectContaining({ ifMatch: 3, idempotencyKey: expect.any(String) })));
});

it("keeps teacher text until an AI draft is explicitly adopted", async () => {
  await show();
  fireEvent.click(screen.getByRole("button", { name: "AI 生成草稿" }));
  const draft = await screen.findByLabelText("AI 章节草稿");
  expect(screen.getByLabelText(/章节说明/)).toHaveValue("第一章说明");
  fireEvent.change(draft, { target: { value: "教师评审后的内容" } });
  fireEvent.click(screen.getByRole("button", { name: "采纳并替换章节说明" }));
  expect(screen.getByLabelText(/章节说明/)).toHaveValue("教师评审后的内容");
  expect(vi.mocked(request).mock.calls.some(([path]) => path.endsWith("/published"))).toBe(false);
});

it("preserves the material form after an upload error", async () => {
  await show();
  fireEvent.change(screen.getByLabelText("材料名称"), { target: { value: "保留输入" } });
  fireEvent.change(screen.getByLabelText("附件"), { target: { files: [new File(["guide"], "guide.txt")] } });
  state.failure = "扫描暂不可用";
  fireEvent.click(screen.getByRole("button", { name: "保存材料草稿" }));
  expect(await screen.findByText("扫描暂不可用")).toBeInTheDocument();
  expect(screen.getByLabelText("材料名称")).toHaveValue("保留输入");
  expect(screen.getByText("guide.txt")).toBeInTheDocument();
});
