import { defineConfig, devices } from "@playwright/test";

// 学生/教师/平台三端冒烟：构建产物由 dist/<app> 提供（登录页与核心导航），
// 与 scripts/verify-p1x-*.ps1 的真机联调模式兼容（浏览器持有 session cookie）。
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  projects: [
    { name: "student-web", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 920 } } },
    { name: "teacher-web", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 920 } } },
    { name: "admin-web", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 920 } } },
  ],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://student.localhost:8080",
    trace: "retain-on-failure",
    ignoreHTTPSErrors: true,
  },
});
