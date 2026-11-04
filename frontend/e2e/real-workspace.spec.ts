import { expect, test } from "@playwright/test";

const studentId = process.env.E2E_STUDENT_ID ?? "student.integration@example.edu";
const password = process.env.E2E_SEED_PASSWORD ?? process.env.E2E_STUDENT_PASSWORD;
const taskTitle = process.env.REAL_WORKSPACE_E2E_TASK_TITLE;
const taskId = process.env.REAL_WORKSPACE_E2E_TASK_ID;

test.use({ baseURL: process.env.STUDENT_WEB_URL ?? "http://student.localhost:8080" });

test("real workspace student journey", async ({ page }) => {
  test.setTimeout(180_000);
  if (!password || !taskTitle) {
    throw new Error("需要一次性真实工作区种子和学生凭据");
  }

  await page.goto("/");
  await page.fill("#login-identifier", studentId!);
  await page.fill("#login-password", password!);
  await page.click("button[type=submit]");
  await expect(page.getByRole("navigation", { name: "一级导航" })).toBeVisible();

  if (taskId) {
    await page.goto(`/experiments/${taskId}`);
  } else {
    await page.goto("/experiments");
    await page.getByText(taskTitle!, { exact: true }).click();
  }
  const enter = page.getByRole("button", { name: /开始任务|进入实验工作台/ });
  await enter.click();

  await expect(page.getByText("工作区已就绪")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("正在打开工作台", { exact: true })).toBeHidden({ timeout: 60_000 });
  await page.getByRole("button", { name: "运行测试" }).click();
  await expect(page.getByText("全部通过")).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "完成实验" }).click();
  await page.getByRole("button", { name: "确认完成" }).click();
  await expect(page.getByText("等待教师评审")).toBeVisible({ timeout: 60_000 });
});
