import fs from "node:fs";
import { expect, test } from "@playwright/test";

const manifestPath = process.env.ASSESSMENT_E2E_MANIFEST;
const manifest = manifestPath ? JSON.parse(fs.readFileSync(manifestPath, "utf8")) : null;
const password = process.env.E2E_TEACHER_PASSWORD;
test.use({ baseURL: process.env.E2E_TEACHER_URL ?? "http://teacher.localhost:8080" });
test.beforeEach(async ({ page }) => {
  test.skip(!manifest || !password || !process.env.E2E_TEACHER_ID, "Requires assessment manifest and teacher credentials");
  await page.goto("/login");
  await page.locator("#t-identifier").fill(process.env.E2E_TEACHER_ID!);
  await page.locator("#t-password").fill(password!);
  await page.locator("button[type=submit]").click();
  await expect(page.getByRole("navigation", { name: "一级导航" })).toBeVisible();
});

test("teacher edits, prechecks and publishes a choice template without runtime JSON", async ({ page }) => {
  await page.goto(`/courses/${manifest.course_id}/templates`);
  await page.getByRole("button", { name: "新建实验模板", exact: true }).first().click();
  await page.locator("#tpl-name").fill(`浏览器验收-${Date.now()}`);
  await page.getByRole("dialog").getByRole("button", { name: /创建/ }).click();
  await expect(page.getByRole("heading", { name: "实验题目与发布版本" })).toBeVisible();
  if (await page.getByRole("heading", { name: "选择题与编程题" }).count() === 0) {
    await page.getByRole("button", { name: "新建草稿版本", exact: true }).click();
  }
  await page.getByLabel("章节名称", { exact: true }).fill("基础选择");
  await page.getByRole("button", { name: "新增章节", exact: true }).click();
  await expect(page.locator("select option").filter({ hasText: "基础选择" })).toHaveCount(1);
  await page.getByLabel("标题", { exact: true }).fill("栈的顺序");
  await page.getByLabel("题干", { exact: true }).fill("栈遵循哪一种顺序？");
  await page.getByLabel("选项 1", { exact: true }).fill("先进先出");
  await page.getByLabel("选项 2", { exact: true }).fill("后进先出");
  await page.getByRole("radio", { name: "正确选项 2", exact: true }).check();
  await page.getByRole("button", { name: "保存题目", exact: true }).click();
  await expect(page.getByText("栈的顺序", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "执行预检", exact: true }).click();
  await expect(page.getByRole("button", { name: "发布模板版本", exact: true })).toBeEnabled({ timeout: 60_000 });
  await page.getByRole("button", { name: "发布模板版本", exact: true }).click();
  await expect(page.getByRole("combobox").first()).toContainText("PUBLISHED");
  await expect(page.locator("iframe")).toHaveCount(0);
});

test("teacher grades fixed report then returns only the programming section", async ({ page }) => {
  const fixture = manifest.fixtures.find((row: { kind: string }) => row.kind === "MIXED");
  test.skip(!fixture, "Requires a mixed assessment submitted by the student journey");
  await page.goto(`/courses/${manifest.course_id}/publishing/${fixture.publication_id}/reviews`);
  const select = page.getByRole("combobox");
  await expect(select.locator("option")).toHaveCount(2);
  await select.selectOption({ index: 1 });
  await expect(page.getByText("读取整数求和。复杂度 O(1)，包含负数边界。", { exact: true })).toBeVisible();
  await page.getByRole("spinbutton").fill("9");
  await page.getByLabel("评语", { exact: true }).fill("浏览器验收报告评分");
  await page.getByRole("button", { name: "保存报告评分", exact: true }).click();
  await expect(page.getByText("报告评分已保存", { exact: true })).toBeVisible();
  await page.getByLabel("退回后的重交截止时间", { exact: true }).fill(
    new Date(Date.now() + 86400000).toISOString().slice(0, 16),
  );
  await page.getByRole("button", { name: "退回编程与报告卷", exact: true }).click();
  await expect(page.getByText("编程卷已退回，选择题提交保持有效", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "保存报告评分", exact: true })).toBeDisabled();
});
