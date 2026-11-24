import { expect, test } from "@playwright/test";

const TEACHER_ID = process.env.E2E_TEACHER_ID;
const TEACHER_PASSWORD = process.env.E2E_TEACHER_PASSWORD;

test.use({ baseURL: process.env.E2E_TEACHER_URL ?? "http://teacher.localhost:8080" });

test("教师门户未登录显示登录页", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "登录教师门户" })).toBeVisible();
  await expect(page.locator("#t-identifier")).toBeVisible();
});

test("教师登录后打开教学日程", async ({ page }) => {
  test.skip(!TEACHER_ID || !TEACHER_PASSWORD, "需要 E2E_TEACHER_ID / E2E_TEACHER_PASSWORD");
  await page.goto("/");
  await page.fill("#t-identifier", TEACHER_ID!);
  await page.fill("#t-password", TEACHER_PASSWORD!);
  await page.click("button[type=submit]");
  await expect(page.getByRole("heading", { name: "教学日程" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "我的教学班" })).toBeVisible();
});
