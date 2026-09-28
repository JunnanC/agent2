import { expect, test, type Page } from '@playwright/test'

const password = process.env.P02_E2E_PASSWORD ?? 'P08-Disposable-Seed-Only-2026!'
test.setTimeout(60_000)

async function login(page: Page, identifier: string) {
  await page.goto('/login')
  await page.getByLabel('邮箱或用户名').fill(identifier)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).not.toHaveURL(/\/login$/, { timeout: 15_000 })
}

async function responsive(page: Page) {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 920, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    const toolbarOverlapsFrame = await page.evaluate(() => {
      const layout = document.querySelector('.workspace-lab__layout')?.getBoundingClientRect()
      const frame = document.querySelector('.workspace-lab__frames')?.getBoundingClientRect()
      const footer = document.querySelector('.workspace-lab__footer')?.getBoundingClientRect()
      if (!layout || !frame || !footer) return true
      const visibleTop = Math.max(layout.top, frame.top)
      const visibleBottom = Math.min(layout.bottom, frame.bottom)
      return visibleTop < footer.bottom && visibleBottom > footer.top && visibleTop < visibleBottom
    })
    expect(toolbarOverlapsFrame).toBe(false)
  }
}

test('@user P08 workspace lab, checkpoint and replay are reachable', async ({ page, context }) => {
  const checkpointName = `P08 integration checkpoint ${Date.now()}`
  await login(page, 'student.integration@example.edu')
  await page.goto('/tasks')
  await page.getByRole('row').filter({ hasText: 'P07 FakeRuntime 任务' }).getByRole('link', { name: '查看' }).click()
  await page.getByRole('link', { name: '进入工作区' }).click()
  await expect(page.getByRole('heading', { name: 'IDE / 内容' })).toBeVisible()
  await responsive(page)
  await page.getByRole('textbox', { name: '实验内容' }).fill('// P08 integration snapshot\nconsole.log("saved")\n')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('已保存到工作区对象存储')
  await context.setOffline(true)
  await page.getByRole('textbox', { name: '实验内容' }).fill('// P08 queued while offline\n')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByText('待同步', { exact: true })).toBeVisible()
  await context.setOffline(false)
  await expect(page.getByText('已保存', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '运行测试' }).click()
  await expect(page.getByRole('status')).toContainText('测试通过')
  await page.getByRole('button', { name: '检查点' }).click()
  await expect(page.getByRole('heading', { name: '命名检查点' })).toBeVisible()
  await page.getByLabel('检查点名称').fill(checkpointName)
  await page.getByRole('button', { name: '创建检查点' }).click()
  await expect(page.getByRole('status')).toContainText('检查点已创建')
  await page.getByRole('row').filter({ hasText: checkpointName }).getByRole('button', { name: '恢复' }).click()
  await expect(page.getByRole('status')).toContainText(new RegExp(`已恢复“${checkpointName}”并创建 v\\d+`))
  await page.getByRole('link', { name: '返回实验室' }).click()
  await page.getByRole('button', { name: '回放' }).click()
  await expect(page.getByRole('heading', { name: '工作区回放' })).toBeVisible()
  await expect(page.getByText('operation.run_check').first()).toBeVisible()
  await expect(page.getByText('checkpoint.restored').first()).toBeVisible()
})

test('@teacher P08 workspace projection never exposes a token', async ({ page }) => {
  await login(page, 'teacher.integration@example.edu')
  await expect(page.locator('body')).not.toContainText('workspace_token')
})

test('@admin P08 session summary is read only', async ({ page }) => {
  await login(page, 'admin.integration@example.edu')
  await page.goto('/workspace-sessions')
  await expect(page.getByRole('heading', { name: '工作区会话摘要' })).toBeVisible()
  await expect(page.getByText('不提供进入学生工作区')).toBeVisible()
})
