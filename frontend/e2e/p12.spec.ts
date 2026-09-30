import { expect, test, type Page } from '@playwright/test'

const password = process.env.P02_E2E_PASSWORD ?? 'P12-Disposable-Seed-Only-2026!'
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

test('@teacher P12 profile, knowledge, evaluation and feedback surfaces are course scoped', async ({ page }) => {
  await login(page, 'teacher.integration@example.edu', teacherBaseUrl)
  const courseId = await page.evaluate(async () => {
    const response = await fetch('/api/v2/teaching/courses?page_size=100')
    const body = await response.json() as { data: Array<{ public_id: string; code: string }> }
    return body.data.find((item) => item.code === 'P03-DEMO-001')?.public_id ?? ''
  })
  expect(courseId).not.toBe('')
  await page.goto(new URL(`/courses/${courseId}/agents`, teacherBaseUrl).toString())
  await expect(page.getByRole('heading', { name: '课程 Agent 配置' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Profile 与激活门禁' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '知识库与来源' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '课程评测套件' })).toBeVisible()
  await responsive(page)
})

test('@user P12 course Agent creates an async cited session surface', async ({ page }) => {
  await login(page, 'student.integration@example.edu', userBaseUrl)
  const courseId = await page.evaluate(async () => {
    const response = await fetch('/api/v2/courses')
    const body = await response.json() as { data: Array<{ public_id: string }> }
    return body.data[0]?.public_id ?? ''
  })
  expect(courseId).not.toBe('')
  await page.goto(new URL(`/courses/${courseId}/agent`, userBaseUrl).toString())
  await expect(page.getByRole('heading', { name: '课程 Agent' })).toBeVisible()
  await page.getByRole('button', { name: '创建会话' }).click()
  await expect(page.getByText(/会话 .*profile v/)).toBeVisible({ timeout: 30_000 })
  await page.getByLabel('发送消息').fill('课程资料中有哪些关键概念？')
  await page.getByRole('button', { name: '提交推理' }).click()
  await expect(page.getByText(/消息已进入受控推理队列/)).toBeVisible()
  await responsive(page)
})

test('@admin P12 governance shows routes, tools, evaluations and aggregate usage only', async ({ page }) => {
  await login(page, 'admin.integration@example.edu', adminBaseUrl)
  await page.goto(new URL('/agent-policies', adminBaseUrl).toString())
  await expect(page.getByRole('heading', { name: 'Agent 策略、路由与评测' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '模型路由与 fallback' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '平台强制评测' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '调用与成本聚合' })).toBeVisible()
  await expect(page.locator('body')).not.toContainText('完整提示词')
  await responsive(page)
})
