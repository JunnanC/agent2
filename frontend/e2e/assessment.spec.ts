import fs from "node:fs";
import { expect, test } from "@playwright/test";

const fixturePath = process.env.ASSESSMENT_E2E_MANIFEST;
const password = process.env.E2E_STUDENT_PASSWORD;
type Fixture = {
  kind: "CHOICE" | "PROGRAMMING" | "MIXED";
  tasks: Array<{ task_id: string; student: string }>;
};
const fixtures: Fixture[] = fixturePath
  ? JSON.parse(fs.readFileSync(fixturePath, "utf8")).fixtures
  : [];

test.use({ baseURL: process.env.E2E_STUDENT_URL ?? "http://student.localhost:8080" });

for (const kind of ["CHOICE", "PROGRAMMING", "MIXED"] as const) {
  test(`assessment ${kind}: save, run, submit and reload`, async ({ page }) => {
    test.setTimeout(120_000);
    test.skip(!fixturePath || !password, "Requires seeded ASSESSMENT_E2E_MANIFEST and student password");
    const task = fixtures.find((item) => item.kind === kind)?.tasks.find((item) =>
      !process.env.E2E_STUDENT_ID || item.student === process.env.E2E_STUDENT_ID);
    expect(task, "Seed all three assessment forms first").toBeDefined();
    await page.goto("/login");
    await page.locator("#login-identifier").fill(task!.student);
    await page.locator("#login-password").fill(password!);
    await page.locator("button[type=submit]").click();
    await expect(page.getByRole("heading", { name: "学习日程", exact: true })).toBeVisible();
    await page.goto(`/experiments/${task!.task_id}/assessment`);
    await expect(page.getByRole("link", { name: "返回实验详情", exact: true })).toHaveAttribute("href", `/experiments/${task!.task_id}`);
    await expect(page.locator("iframe")).toHaveCount(0);

    if (kind !== "PROGRAMMING") {
      await page.getByRole("radio", { name: "后进先出", exact: true }).check();
      await page.getByRole("checkbox", { name: "数组", exact: true }).check();
      await page.getByRole("checkbox", { name: "链表", exact: true }).check();
      await page.getByRole("button", { name: "提交选择题卷", exact: true }).click();
      await page.getByRole("button", { name: "确认交卷", exact: true }).click();
      await expect(page.getByText(/^(选择题已提交|交卷成功，已固定本次提交版本)$/)).toBeVisible();
      await expect(page.getByText(/正确选项：/)).toHaveCount(0);
    }
    if (kind !== "CHOICE") {
      if (kind === "MIXED") await page.getByRole("button", { name: "编程与报告", exact: true }).click();
      const code = page.locator(".cm-content");
      await expect(code).toBeVisible();
      await code.fill("a,b=map(int,input().split());print(a+b)\n");
      await page.getByRole("textbox", { name: "自定义输入" }).fill("3 5\n");
      await page.getByRole("button", { name: "运行代码", exact: true }).click();
      const output = page.getByRole("region", { name: "运行结果" });
      await expect(output.getByRole("heading", { name: "运行成功" })).toBeVisible({ timeout: 60_000 });
      await expect(output.locator("pre").first()).toHaveText("8\n");
      await page.getByRole("textbox", { name: "报告正文" }).fill("读取整数求和。复杂度 O(1)，包含负数边界。");
      await page.getByRole("button", { name: "提交编程与报告卷", exact: true }).click();
      await page.getByRole("button", { name: "确认交卷", exact: true }).click();
      await expect(page.getByText("交卷成功，已固定本次提交版本", { exact: true })).toBeVisible();
    }
    const submittedChoice = page.getByRole("button", { name: "已提交选择题", exact: true });
    const submittedAll = page.getByText("本实验各部分已交齐。", { exact: true });
    if (kind === "CHOICE") {
      await expect(submittedChoice.or(submittedAll)).toBeVisible();
      if (await submittedChoice.isVisible()) {
        await page.reload();
        await expect(submittedChoice).toBeDisabled();
        await expect(page.getByRole("radio", { name: "后进先出", exact: true })).toBeChecked();
        return;
      }
    }
    await expect(submittedAll).toBeVisible();
    await page.reload();
    await expect(submittedAll).toBeVisible();
    await page.getByText("交卷历史", { exact: true }).click();
    await expect(page.getByText(/当前有效/).first()).toBeVisible();
  });
}
