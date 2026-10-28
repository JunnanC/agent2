import { expect, test } from "@playwright/test";

/**
 * 学生端冒烟：登录页可用 + 登录后壳层导航出现。
 * 依赖 docker-compose.dev 起的后端（student.localhost:8080 经 Host 注入 USER 门户）；
 * 凭据通过环境变量提供，不在代码中保存。
 */
const STUDENT_ID = process.env.E2E_STUDENT_ID;
const STUDENT_PASSWORD = process.env.E2E_STUDENT_PASSWORD;

test.use({ baseURL: process.env.E2E_STUDENT_URL ?? "http://student.localhost:8080" });

test("学生门户未登录显示登录页", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/学生门户/);
  await expect(page.locator("#root")).not.toBeEmpty();
});

test("学生登录后进入首页并展示导航", async ({ page }) => {
  test.skip(!STUDENT_ID || !STUDENT_PASSWORD, "需要 E2E_STUDENT_ID / E2E_STUDENT_PASSWORD 才能执行登录回归");
  await page.goto("/");
  await page.fill("#login-identifier", STUDENT_ID!);
  await page.fill("#login-password", STUDENT_PASSWORD!);
  await page.click("button[type=submit]");
  await expect(page.getByRole("navigation", { name: "一级导航" })).toBeVisible();
  await expect(page.getByText("任务日历")).toBeVisible();

  // 进入实验列表 → 任务详情
  await page.getByRole("button", { name: "我的实验" }).click();
  await expect(page).toHaveURL(/\/experiments/);
});

/** 工作台核心交互（不依赖真实工作区时也应渲染到基础布局） */
test("工作台页面结构", async ({ page }) => {
  test.skip(!STUDENT_ID || !STUDENT_PASSWORD, "需要登录态");
  await page.goto("/");
  await page.fill("#login-identifier", STUDENT_ID!);
  await page.fill("#login-password", STUDENT_PASSWORD!);
  await page.click("button[type=submit]");
  await expect(page.getByRole("navigation", { name: "一级导航" })).toBeVisible();
  // 未进行真实 enter 时，最多验证实验列表加载；工作台需要 session 就绪
  await page.goto("/experiments");
  await expect(page.getByText("实验任务").first()).toBeVisible();
});
