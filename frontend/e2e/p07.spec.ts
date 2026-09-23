import { expect, test, type Page } from '@playwright/test'

const password = process.env.P02_E2E_PASSWORD ?? 'P06-Disposable-Seed-Only-2026!'
test.setTimeout(60_000)

async function login(page: Page, identifier: string) {
  await page.goto('/login')
  await page.getByLabel('邮箱或用户名').fill(identifier)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).not.toHaveURL(/\/login$/, { timeout: 15_000 })
}

test('@user P07 task detail exposes provisioning stages and fallback status', async ({ page }) => {
  await login(page, 'student.integration@example.edu')
  await page.goto('/tasks')
  await page.getByRole('link', { name: '查看' }).first().click()
  await expect(page.getByRole('heading', { name: '装载作业' })).toBeVisible()
})

test('@teacher P07 tracking includes provisioning summary', async ({ page }) => {
  await login(page, 'teacher.integration@example.edu')
  await page.goto('/courses')
  const coursePath = await page.locator('a[href^="/courses/"]').first().getAttribute('href')
  await page.goto(`${coursePath}/experiments`)
  await page.getByRole('link', { name: '管理' }).first().click()
  await expect(page.getByRole('heading', { name: '任务追踪' })).toBeVisible()
})

test('@admin P07 anomaly page shows stage and compensation columns', async ({ page }) => {
  await login(page, 'admin.integration@example.edu')
  await page.goto('/experiment-anomalies')
  await expect(page.getByRole('heading', { name: '实验任务异常' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '补偿积压' })).toBeVisible()
})
