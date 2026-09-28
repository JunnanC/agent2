import { expect, test, type Page } from '@playwright/test'

const password = process.env.P02_E2E_PASSWORD ?? 'P06-Disposable-Seed-Only-2026!'
test.setTimeout(60_000)
test.describe.configure({ mode: 'serial' })

async function login(page: Page, identifier: string) {
  await page.goto('/login')
  await page.getByLabel('邮箱或用户名').fill(identifier)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).not.toHaveURL(/\/login$/, { timeout: 15000 })
}

async function assertResponsive(page: Page) {
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 920, height: 900 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
}

function localDateTime(date: Date) {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

test('@teacher P06 publication, tasks, and extension decisions are reachable', async ({ page }) => {
  await login(page, 'teacher.integration@example.edu')
  await page.goto('/courses')
  const coursePath = await page.locator('a[href^="/courses/"]').first().getAttribute('href')
  expect(coursePath).toMatch(/^\/courses\/[A-Z0-9]+$/)
  await page.goto(`${coursePath}/experiments`)
  await expect(page.getByRole('heading', { name: '实验发布' })).toBeVisible()
  await expect(page.getByText('P06 个人实验任务')).toBeVisible()
  await assertResponsive(page)
  await page.getByRole('link', { name: '管理' }).first().click()
  await expect(page.getByRole('heading', { name: '任务追踪' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '延期申请' })).toBeVisible()
  await assertResponsive(page)
})

test('@teacher P06 selected audience draft can be created and published', async ({ page }) => {
  await login(page, 'teacher.integration@example.edu')
  await page.goto('/courses')
  const coursePath = await page.locator('a[href^="/courses/"]').first().getAttribute('href')
  expect(coursePath).toMatch(/^\/courses\/[A-Z0-9]+$/)
  await page.goto(`${coursePath}/experiments`)

  await page.getByRole('button', { name: '新建草稿' }).click()
  const title = `P06 指定学生发布 ${Date.now()}`
  const now = new Date()
  await page.getByLabel('实验标题').fill(title)
  await page.getByLabel('模板版本').selectOption({ index: 1 })
  await page.getByLabel('Rubric 版本').selectOption({ index: 1 })
  await page.getByLabel('受众').selectOption('SELECTED')
  await page.getByLabel('开放时间').fill(localDateTime(new Date(now.getTime() - 60_000)))
  await page.getByLabel('截止时间', { exact: true }).fill(localDateTime(new Date(now.getTime() + 86_400_000)))
  await page.getByLabel('分配截止时间').fill(localDateTime(new Date(now.getTime() + 43_200_000)))
  await page.getByRole('button', { name: '保存草稿' }).click()

  const publicationRow = page.locator('tr', { hasText: title })
  await expect(publicationRow).toBeVisible()
  await publicationRow.getByRole('link', { name: '管理' }).click()
  const student = page.getByRole('checkbox', { name: /^选择 / }).first()
  await expect(student).toBeVisible()
  await student.check()
  await page.getByRole('button', { name: '发布实验' }).click()
  await expect(page.getByText('PUBLISHED', { exact: true })).toBeVisible()
})

test('@user P06 dashboard and task detail expose frozen task facts', async ({ page }) => {
  await login(page, 'student.integration@example.edu')
  await page.goto('/dashboard')
  await expect(page.getByRole('heading', { name: '实验工作台' })).toBeVisible()
  await expect(page.getByText('P06 个人实验任务')).toBeVisible()
  await assertResponsive(page)
  await page.goto('/tasks')
  await page.getByRole('link', { name: '查看' }).first().click()
  await expect(page.getByText('冻结版本')).toBeVisible()
  await expect(page.getByRole('heading', { name: '延期记录' })).toBeVisible()
  await assertResponsive(page)
})

test('@admin P06 anomaly view is read-only and responsive', async ({ page }) => {
  await login(page, 'admin.integration@example.edu')
  await page.goto('/experiment-anomalies')
  await expect(page.getByRole('heading', { name: '实验任务异常' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '补偿积压' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '发布与任务对账' })).toBeVisible()
  await expect(page.getByRole('button')).toHaveCount(1)
  await assertResponsive(page)
})
