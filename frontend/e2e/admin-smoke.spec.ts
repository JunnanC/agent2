import { expect, test } from "@playwright/test";

const ADMIN_ID = process.env.E2E_ADMIN_ID;
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD;

test.use({ baseURL: process.env.E2E_ADMIN_URL ?? "http://admin.localhost:8080" });

test("平台管理未登录显示登录页", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/平台管理/);
  await expect(page.locator("#root")).not.toBeEmpty();
});

test("平台管理员登录后展示治理导航", async ({ page }) => {
  test.skip(!ADMIN_ID || !ADMIN_PASSWORD, "需要 E2E_ADMIN_ID / E2E_ADMIN_PASSWORD");
  await page.goto("/");
  await page.fill("#a-identifier", ADMIN_ID!);
  await page.fill("#a-password", ADMIN_PASSWORD!);
  await page.click("button[type=submit]");
  await expect(page.getByRole("navigation", { name: "一级导航" })).toBeVisible();
  await expect(page.getByText("平台概览")).toBeVisible();
});
