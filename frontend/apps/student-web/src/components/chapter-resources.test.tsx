import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { ToastProvider } from "@edu/ui";
import { ChapterResources } from "./chapter-resources";

vi.mock("@edu/api-client", () => ({
  studentApi: { courseMaterials: vi.fn(async () => ({ rows: [
    {public_id:"m1", chapter_id:"ch1", kind:"TEXT", title:"本章指南", text_content:"学习步骤"},
    {public_id:"m2", chapter_id:"ch2", kind:"TEXT", title:"其他章节材料"},
    {public_id:"m3", chapter_id:"ch1", kind:"LINK", title:"安全链接", link_url:"https://example.edu/guide"},
    {public_id:"m4", chapter_id:"ch1", kind:"LINK", title:"不安全链接", link_url:"javascript:alert(1)"},
  ] })) },
  taskApi: { list: vi.fn(async () => ({ rows: [
    {public_id:"t1", course_chapter_id:"ch1", title:"本章实验", assessment_available:true},
    {public_id:"t2", course_chapter_id:"ch2", title:"其他章节实验"},
  ], total:2 })) },
  fileApi: {createDownloadGrant:vi.fn()},
}));
afterEach(cleanup);
it("only displays the selected chapter's materials and assigned experiments", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry:false } } });
  render(<QueryClientProvider client={client}><ToastProvider><MemoryRouter><ChapterResources courseId="c1" chapterId="ch1" /></MemoryRouter></ToastProvider></QueryClientProvider>);
  expect(await screen.findByText("本章指南")).toBeInTheDocument();
  expect(await screen.findByRole("link", {name:"本章实验"})).toHaveAttribute("href", "/experiments/t1");
  expect(screen.getByRole("link", {name:"进入实验答题"})).toHaveAttribute("href", "/experiments/t1/assessment");
  expect(screen.queryByText("其他章节材料")).not.toBeInTheDocument();
  expect(screen.queryByText("其他章节实验")).not.toBeInTheDocument();
  expect(screen.getByRole("link", {name:"安全链接"})).toHaveAttribute("href", "https://example.edu/guide");
  expect(screen.getByText("不安全链接")).toBeInTheDocument();
  expect(screen.queryByRole("link", {name:"不安全链接"})).not.toBeInTheDocument();
  client.clear();
});
