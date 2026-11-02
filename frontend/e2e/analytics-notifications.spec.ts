import { expect, test, type Page } from '@playwright/test'

const password = process.env.E2E_SEED_PASSWORD ?? 'Integration-Disposable-Seed-Only-2026!'
const userBaseUrl = process.env.STUDENT_WEB_URL ?? 'http://student.localhost:8080'
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
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 920, height: 900 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport)
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
      .toBe(true)
  }
}

test('@user Notification and recommendation center stays within viewport', async ({ page }) => {
  await login(page, 'student.integration@example.edu', userBaseUrl)
  await page.goto(new URL('/notifications', userBaseUrl).toString())
  await expect(page.getByRole('heading', { name: '通知与学习建议' })).toBeVisible()
  await responsive(page)
})

test('@teacher Course analytics and risk handling stays within viewport', async ({ page }) => {
  await login(page, 'teacher.integration@example.edu', teacherBaseUrl)
  const courseId = await page.evaluate(async () => {
    const response = await fetch('/api/v2/teaching/courses?page_size=100')
    const body = (await response.json()) as { data: Array<{ public_id: string }> }
    return body.data[0]?.public_id ?? ''
  })
  expect(courseId).not.toBe('')
  await page.goto(new URL(`/courses/${courseId}/analytics`, teacherBaseUrl).toString())
  await expect(page.getByRole('heading', { name: '课程分析与风险' })).toBeVisible()
  await responsive(page)
})

test('@admin management navigation stays within viewport', async ({ page }) => {
  await page.goto(new URL('/#overview', adminBaseUrl).toString())
  await expect(page.getByRole('heading', { name: '平台概览' })).toBeVisible()
  await page.getByRole('button', { name: /用户账号/ }).click()
  await expect(page).toHaveURL(/#users$/)
  await expect(page.getByRole('heading', { name: '用户账号' })).toBeVisible()
  await responsive(page)
})
