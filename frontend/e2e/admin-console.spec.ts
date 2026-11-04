import { expect, test } from "@playwright/test";

// An isolated API fixture exercises the production React shell without requiring local credentials.
test.use({
  baseURL: process.env.E2E_ADMIN_CONSOLE_URL ?? "http://127.0.0.1:5186",
  channel: "msedge",
});

test("seven-page console preserves real write semantics and read-only resources", async ({
  page,
}) => {
  const users = Array.from({ length: 11 }, (_, n) => ({
    public_id: `U-${n}`,
    display_name: ["林知远", "周明远", "运维管理员"][n] ?? `同学${n}`,
    username: `member${n}`,
    email: `member${n}@school.edu`,
    account_status: "ACTIVE",
    row_version: 3,
  }));
  const courses = [
    {
      public_id: "C-1",
      title: "Linux 系统实验",
      code: "LINUX-A",
      owner_id: "U-1",
      owner_name: "周明远",
      status: "PUBLISHED",
      active_enrollment_count: 6,
      summary: "网络配置实验",
      row_version: 1,
    },
    {
      public_id: "C-2",
      title: "Linux 系统实验",
      code: "LINUX-B",
      owner_id: "U-1",
      owner_name: "周明远",
      status: "PUBLISHED",
      active_enrollment_count: 3,
      row_version: 1,
    },
  ];
  const images = [
    {
      public_id: "I-1",
      registry: "registry.school.edu",
      repository: "labs/linux",
      display_tag: "v2",
      digest: `sha256:${"a".repeat(64)}`,
      scan_status: "CLEAN",
      approval_status: "APPROVED",
      row_version: 2,
    },
  ];
  const logs: Record<string, unknown>[] = [];
  const writes: {
    path: string;
    body: Record<string, unknown>;
    match?: string;
  }[] = [];
  let rejectMutation = false;
  await page.route("**/api/v2/**", async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname.replace("/api/v2", "");
    let data: unknown = [],
      total: number | undefined;
    if (path === "/me")
      data = {
        public_id: "U-2",
        display_name: "运维管理员",
        username: "ops",
        portal: "PLATFORM",
        eligible_portals: ["PLATFORM"],
        permissions: [],
        course_scopes: [],
      };
    else if (path === "/auth/csrf") {
      await route.fulfill({
        json: { data: {}, meta: {} },
        headers: { "set-cookie": "csrftoken=test; Path=/" },
      });
      return;
    } else if (req.method() !== "GET") {
      const body = req.postDataJSON();
      writes.push({ path, body, match: req.headers()["if-match"] });
      if (rejectMutation) {
        await route.fulfill({
          status: 412,
          json: {
            error: { code: "ROW_VERSION_CONFLICT", message: "版本冲突" },
          },
        });
        return;
      }
      if (path.startsWith("/platform/users/")) {
        const u = users.find((x) => path.endsWith(x.public_id))!;
        Object.assign(u, body, { row_version: u.row_version + 1 });
        data = u;
      } else if (path.endsWith("/decide")) {
        images[0]!.approval_status = body.decision;
        data = images[0];
      } else if (path === "/platform/images") {
        images.push({
          ...images[0]!,
          ...body,
          public_id: "I-2",
          approval_status: "PENDING",
        });
        data = images[1];
      }
      logs.unshift({
        id: String(logs.length + 1),
        occurred_at: "2026-11-04T09:00:00Z",
        actor: "U-2",
        action: "account.status.changed",
        target: path,
        result: "SUCCESS",
        trace_id: "trace-test",
      });
    } else if (path === "/platform/users") data = users;
    else if (path === "/platform/teacher-qualifications")
      data = [
        {
          public_id: "Q-1",
          user_id: "U-1",
          display_name: "周明远",
          status: "ACTIVE",
        },
      ];
    else if (path === "/platform/admin-assignments")
      data = [{ public_id: "A-1", user_id: "U-2", status: "ACTIVE" }];
    else if (path === "/platform/courses") data = courses;
    else if (path === "/platform/images") data = images;
    else if (path === "/platform/runtime-adapters")
      data = [
        {
          public_id: "R-1",
          name: "实验运行环境",
          code: "lab-01",
          driver: "DOCKER_SWARM",
          health_status: "HEALTHY",
          status: "ENABLED",
          capacity_cpu_millicores: 8000,
          available_cpu_millicores: 4000,
          capacity_memory_mb: 16384,
          available_memory_mb: 8192,
        },
      ];
    else if (path === "/platform/instances")
      data = [
        {
          public_id: "W-1",
          course_id: "C-1",
          student_id: "U-0",
          status: "RUNNING",
          runtime_driver: "DOCKER_SWARM",
        },
      ];
    else if (path === "/platform/operations/overview")
      data = { runtime: { status: "AVAILABLE" }, alerts: [] };
    else if (path === "/platform/operations/audit") data = logs;
    if (Array.isArray(data)) total = data.length;
    await route.fulfill({ json: { data, meta: { total } } });
  });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "运行概览", exact: true }),
  ).toBeVisible();
  for (const label of [
    "课程与班级",
    "学生管理",
    "教师管理",
    "镜像管理",
    "服务与资源",
    "操作日志",
  ]) {
    await page
      .getByRole("navigation")
      .getByRole("button", { name: label, exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: label, exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: "../outputs/admin-web1/" + label + ".png",
      fullPage: true,
    });
  }
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "学生管理", exact: true })
    .click();
  await expect(page.getByRole("cell", { name: "周明远" })).toHaveCount(0);
  await page.getByPlaceholder("搜索姓名、账号 ID 或邮箱").fill("林知远");
  await page.getByRole("button", { name: "禁用", exact: true }).click();
  await page.getByLabel("操作原因").fill("安全核查");
  await page.getByRole("button", { name: "确认禁用", exact: true }).click();
  await expect(page.locator(".console-feedback")).toContainText("账号已禁用");
  expect(writes[0]?.match).toBe('"3"');
  expect(writes[0]?.body.reason).toBe("安全核查");
  await page.getByRole("button", { name: "恢复", exact: true }).click();
  rejectMutation = true;
  await page.getByRole("button", { name: "确认恢复", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("刷新列表后重试");
  await page.getByRole("button", { name: "取消", exact: true }).click();
  rejectMutation = false;
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "课程与班级", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "下架", exact: true }).first(),
  ).toBeDisabled();
  await page.getByRole("button", { name: "详情", exact: true }).first().click();
  await page.getByRole("button", { name: "学生名单", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("查询接口尚未开放");
  await page.getByRole("button", { name: "关闭弹窗" }).click();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "镜像管理", exact: true })
    .click();
  await page.getByRole("button", { name: "停用", exact: true }).click();
  await page.getByRole("button", { name: "确认停用" }).click();
  await expect(page.locator(".console-feedback")).toContainText("镜像已停用");
  expect(writes.at(-1)?.body.decision).toBe("RETIRED");
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "服务与资源", exact: true })
    .click();
  await page.getByRole("button", { name: "资源占用", exact: true }).click();
  await expect(
    page.getByRole("button", { name: /重启|销毁|停止实例|扩缩容/ }),
  ).toHaveCount(0);
  await page.screenshot({
    path: "../outputs/admin-web1/resources-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "切换导航" }).click();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "运行概览", exact: true })
    .click();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "../outputs/admin-web1/overview-mobile.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
