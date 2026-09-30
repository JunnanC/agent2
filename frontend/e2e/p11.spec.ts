import { expect, test, type Page } from '@playwright/test'

const password = process.env.P02_E2E_PASSWORD ?? 'P11-Disposable-Seed-Only-2026!'
const userBaseUrl = process.env.USER_WEB_URL ?? 'http://user.localhost:8080'
const teacherBaseUrl = process.env.TEACHER_WEB_URL ?? 'http://teacher.localhost:8080'
const adminBaseUrl = process.env.ADMIN_WEB_URL ?? 'http://admin.localhost:8080'
test.setTimeout(180_000)

async function login(page: Page, identifier: string, baseUrl: string) {
  await page.goto(new URL('/login', baseUrl).toString())
  await page.getByLabel('邮箱或用户名').fill(identifier)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).not.toHaveURL(/\/login$/, { timeout: 15_000 })
}

async function responsive(page: Page) {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 920, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
}

test('@user P11 verified archive is visible on the compatible result route', async ({ page }) => {
  await login(page, 'student.integration@example.edu', userBaseUrl)
  const taskId = await page.evaluate(async () => {
    const response = await fetch('/api/v2/tasks?page_size=100')
    const body = await response.json() as { data: Array<{ public_id: string; status: string }> }
    return body.data.find((item) => ['ARCHIVING', 'DESTROYING', 'COMPLETED'].includes(item.status))?.public_id ?? ''
  })
  expect(taskId).not.toBe('')
  await page.goto(new URL(`/experiments/${taskId}/result`, userBaseUrl).toString())
  await expect(page.getByRole('heading', { name: '审核结果' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '归档与导出' })).toBeVisible()
  await expect(page.getByText('PASSED', { exact: true }).last()).toBeVisible({ timeout: 60_000 })
  await expect(page.getByRole('button', { name: '下载归档' })).toBeEnabled()
  await responsive(page)
})

test('@teacher P11 course archive exposes verification and controlled export', async ({ page }) => {
  await login(page, 'teacher.integration@example.edu', teacherBaseUrl)
  const courseId = await page.evaluate(async () => {
    const response = await fetch('/api/v2/teaching/courses?page_size=100')
    const body = await response.json() as { data: Array<{ public_id: string; code: string }> }
    return body.data.find((item) => item.code === 'P03-DEMO-001')?.public_id ?? ''
  })
  await page.goto(new URL(`/courses/${courseId}/archives`, teacherBaseUrl).toString())
  await expect(page.getByRole('heading', { name: '课程成果归档' })).toBeVisible()
  await page.getByRole('link', { name: '查看校验' }).first().click()
  await expect(page.getByRole('heading', { name: '校验记录' })).toBeVisible()
  await expect(page.getByText('PASSED', { exact: true }).first()).toBeVisible({ timeout: 60_000 })
  await expect(page.getByRole('button', { name: '申请并下载' })).toBeEnabled()
  await responsive(page)
})

test('@admin P11 recovery views expose instances and compensation state', async ({ page }) => {
  await login(page, 'admin.integration@example.edu', adminBaseUrl)
  await page.goto(new URL('/instances', adminBaseUrl).toString())
  await expect(page.getByRole('heading', { name: '实例与孤儿检测' })).toBeVisible()
  await page.goto(new URL('/compensations', adminBaseUrl).toString())
  await expect(page.getByRole('heading', { name: '归档与回收补偿' })).toBeVisible()
  await expect(page.getByRole('button', { name: /通过|退回|审核决定/ })).toHaveCount(0)
  await responsive(page)
})
