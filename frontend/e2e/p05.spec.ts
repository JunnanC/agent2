import { expect, test, type Page } from '@playwright/test'

const password = process.env.P02_E2E_PASSWORD ?? 'P05-Disposable-Seed-Only-2026!'

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

test('@teacher P05 template and rubric pages are reachable and responsive', async ({ page }) => {
  await login(page, 'teacher.integration@example.edu')
  await page.goto('/courses')
  const courseLink = page.locator('a[href^="/courses/"]').first()
  await expect(courseLink).toBeVisible()
  const coursePath = await courseLink.getAttribute('href')
  expect(coursePath).toMatch(/^\/courses\/[A-Z0-9]+$/)
  await page.goto(`${coursePath}/templates`)
  await expect(page.getByRole('heading', { name: '实验模板' })).toBeVisible()
  await assertResponsive(page)
  const rubricHref = `${coursePath}/rubrics`
  await page.goto(rubricHref)
  await expect(page.getByRole('heading', { name: '评分量规' })).toBeVisible()
  await assertResponsive(page)
})

test('@admin P05 precheck supervision page is read-only and responsive', async ({ page }) => {
  await login(page, 'admin.integration@example.edu')
  await page.goto('/template-prechecks')
  await expect(page.getByRole('heading', { name: '预检监管' })).toBeVisible()
  await expect(page.getByText('平台管理员不能代替教师修改或发布')).toBeVisible()
  await assertResponsive(page)
})
