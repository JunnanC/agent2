import { expect, test, type Page } from '@playwright/test'

const password = process.env.P02_E2E_PASSWORD ?? 'P02-Integration-Admin!234'
const userWebUrl = process.env.USER_WEB_URL ?? 'http://user.localhost:8080'
const teacherWebUrl = process.env.TEACHER_WEB_URL ?? 'http://teacher.localhost:8080'
const adminWebUrl = process.env.ADMIN_WEB_URL ?? 'http://admin.localhost:8080'

async function login(page: Page, identifier: string) {
  await page.goto('/login')
  await page.getByLabel('邮箱或用户名').fill(identifier)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).not.toHaveURL(/\/login$/)
}

test('@user user portal login, profile, and responsive storage boundary', async ({ page }) => {
  await login(page, 'student.integration@example.edu')
  await expect(page.getByRole('heading', { name: /你好，Integration Student/ })).toBeVisible()
  await page.getByRole('link', { name: '个人资料' }).click()
  await expect(page.getByRole('heading', { name: '个人资料' })).toBeVisible()
  for (const viewport of [{ width: 1440, height: 900 }, { width: 920, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
  expect(await page.evaluate(() => localStorage.length)).toBe(0)
})

test('@teacher teacher portal requires and displays active qualification', async ({ page }) => {
  await login(page, 'teacher.integration@example.edu')
  await expect(page.getByRole('heading', { name: '教师门户准入' })).toBeVisible()
  await expect(page.getByText('ACTIVE', { exact: true })).toBeVisible()
  for (const viewport of [{ width: 1440, height: 900 }, { width: 920, height: 900 }]) {
    await page.setViewportSize(viewport)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
  expect(await page.evaluate(() => localStorage.length)).toBe(0)
})

test('@teacher copied user session is rejected by teaching and platform portals', async ({ page, context }) => {
  for (const portalUrl of [teacherWebUrl, adminWebUrl]) {
    await page.goto(`${userWebUrl}/login`)
    await page.getByLabel('邮箱或用户名').fill('student.integration@example.edu')
    await page.getByLabel('密码').fill(password)
    await page.getByRole('button', { name: '登录' }).click()
    await expect(page.getByRole('heading', { name: /你好，Integration Student/ })).toBeVisible()
    const cookies = await context.cookies(userWebUrl)
    const session = cookies.find((cookie) => cookie.name === 'sessionid')
    expect(session).toBeDefined()
    await context.addCookies([{ ...session!, domain: new URL(portalUrl).hostname }])

    const response = await page.request.get(`${portalUrl}/api/v2/me`)
    expect(response.status()).toBe(401)
    expect((await response.json()).error.code).toBe('SESSION_PORTAL_MISMATCH')
  }
})

test('@admin admin portal exposes account governance without browser credentials', async ({ page }) => {
  await login(page, 'admin.integration@example.edu')
  await expect(page.getByRole('heading', { name: '用户账号' })).toBeVisible()
  await expect(page.getByText('Integration Student')).toBeVisible()
  await page.getByRole('link', { name: '教师资格' }).first().click()
  await expect(page.getByRole('heading', { name: '教师资格' })).toBeVisible()
  for (const viewport of [{ width: 1440, height: 900 }, { width: 920, height: 900 }]) {
    await page.setViewportSize(viewport)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
  expect(await page.evaluate(() => localStorage.length)).toBe(0)
})
