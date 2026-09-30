import { expect, test, type Page } from '@playwright/test'

const password = process.env.P02_E2E_PASSWORD ?? 'P08-Disposable-Seed-Only-2026!'
test.setTimeout(120_000)

async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel('邮箱或用户名').fill('student.integration@example.edu')
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).not.toHaveURL(/\/login$/, { timeout: 15_000 })
}

async function openWorkbench(page: Page) {
  await page.goto('/tasks')
  await page.getByRole('row').filter({ hasText: 'P07 FakeRuntime 任务' }).getByRole('link', { name: '查看' }).click()
  await page.getByRole('link', { name: '进入工作区' }).click()
  await expect(page.getByRole('heading', { name: 'IDE / 内容' })).toBeVisible()
}

test('@user P15-E workspace Agent stays task scoped and clear of primary actions', async ({ page }) => {
  await login(page)
  await openWorkbench(page)

  const geometryResults: Array<{ viewport: number; overlaps: boolean; footer: unknown; drawer: unknown; trigger: unknown }> = []
  for (const viewport of [{ width: 1440, height: 900 }, { width: 920, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    const orb = page.getByRole('button', { name: '打开 Agent 助手' })
    await expect(orb).toBeVisible()
    await orb.click()
    await expect(page.getByRole('dialog', { name: '实验助手' })).toBeVisible()

    const geometry = await page.evaluate(() => {
      const footer = document.querySelector('.workspace-lab__footer')?.getBoundingClientRect()
      const drawer = document.querySelector('.task-agent-drawer:not([hidden])')?.getBoundingClientRect()
      const trigger = document.querySelector('.task-agent-orb')?.getBoundingClientRect()
      if (!footer || !drawer || !trigger) return { overlaps: true, footer: null, drawer: null, trigger: null }
      const overlaps = (left: DOMRect, right: DOMRect) => left.left < right.right && left.right > right.left && left.top < right.bottom && left.bottom > right.top
      const position = (rect: DOMRect) => ({ top: rect.top, right: rect.right, bottom: rect.bottom, left: rect.left })
      return { overlaps: overlaps(drawer, footer) || overlaps(trigger, footer), footer: position(footer), drawer: position(drawer), trigger: position(trigger) }
    })
    geometryResults.push({ viewport: viewport.width, ...geometry })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)

    await page.getByRole('button', { name: '关闭 Agent 助手' }).click()
  }
  const overlapping = geometryResults.filter((item) => item.overlaps)
  expect(overlapping, `Agent overlaps workbench actions: ${JSON.stringify(overlapping)}`).toEqual([])

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.getByRole('button', { name: '打开 Agent 助手' }).click()
  await page.getByRole('button', { name: '解释当前步骤' }).click()
  await expect(page.locator('.task-agent-message--assistant').last()).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.task-agent-message--assistant').last()).not.toContainText('hidden test')

  const storedSecrets = await page.evaluate(() => Object.entries(localStorage).filter(([key, value]) => /workspace.token|agent.session/i.test(`${key}:${value}`)))
  expect(storedSecrets).toEqual([])
})
