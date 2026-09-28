import { expect, test, type Page } from '@playwright/test'

const password = process.env.P02_E2E_PASSWORD ?? 'P10-Disposable-Seed-Only-2026!'
const userBaseUrl = process.env.USER_WEB_URL ?? 'http://user.localhost:8080'
const teacherBaseUrl = process.env.TEACHER_WEB_URL ?? 'http://teacher.localhost:8080'
test.setTimeout(180_000)

async function login(page: Page, identifier: string, baseUrl: string) {
  await page.goto(new URL('/login', baseUrl).toString())
  await page.getByLabel('邮箱或用户名').fill(identifier)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).not.toHaveURL(/\/login$/, { timeout: 15_000 })
}

async function checkResponsiveWidths(page: Page) {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 920, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
}

async function fillScores(page: Page) {
  await page.getByLabel('功能正确性分值').fill('55')
  await page.getByLabel('功能正确性评语').fill('自动检查与实验输出一致')
  await page.getByLabel('报告质量分值').fill('35')
  await page.getByLabel('报告质量评语').fill('报告结构清晰')
  await page.getByRole('button', { name: '保存评分' }).click()
  await expect(page.getByRole('status')).toContainText('评分已保存')
}

test('@user P10 teacher review rejects, student resubmits, and teacher approves', async ({ page }) => {
  await login(page, 'student.integration@example.edu', userBaseUrl)
  await page.goto(new URL('/tasks', userBaseUrl).toString())
  await page.getByRole('link', { name: '查看' }).first().click()
  const taskId = new URL(page.url()).pathname.split('/').at(-1) ?? ''
  const task = await page.evaluate(async (id) => {
    const response = await fetch(`/api/v2/tasks/${id}`)
    return (await response.json()).data
  }, taskId) as { course_id: string }

  await login(page, 'teacher.integration@example.edu', teacherBaseUrl)
  await page.goto(new URL(`/courses/${task.course_id}/reviews`, teacherBaseUrl).toString())
  const firstRound = page.getByRole('row').filter({ hasText: 'Integration Student' }).filter({ has: page.getByRole('cell', { name: '1', exact: true }) })
  await firstRound.getByRole('link', { name: '打开审核' }).click()
  await expect(page.getByRole('heading', { name: /Integration Student/ })).toBeVisible()
  await fillScores(page)
  await page.getByLabel('起始位置').fill('0')
  await page.getByLabel('结束位置').fill('5')
  await page.getByLabel('批注正文').fill('补充说明该段结果来源。')
  await page.getByRole('button', { name: '添加批注' }).click()
  await expect(page.getByRole('status')).toContainText('批注已添加')
  await expect(page.getByRole('cell', { name: 'PASSED', exact: true })).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: '运行分析' }).click()
  await expect(page.getByText('P10 Similarity Peer')).toBeVisible({ timeout: 30_000 })
  await checkResponsiveWidths(page)
  await page.getByLabel('总体反馈').fill('请补充结果讨论后重新提交。')
  page.once('dialog', (dialog) => void dialog.accept())
  await page.getByRole('button', { name: '退回' }).click()
  await expect(page.getByRole('status')).toContainText('成果已退回')

  await page.goto(new URL(`/tasks/${taskId}/review-result`, userBaseUrl).toString())
  await expect(page.getByText('请补充结果讨论后重新提交。')).toBeVisible()
  await page.getByRole('link', { name: '修改并重新提交' }).click()
  await page.getByLabel('Markdown 报告正文').fill('# P10 教师审核\n\n补充结果讨论后重新提交。')
  await page.getByRole('button', { name: '保存草稿' }).click()
  await expect(page.getByRole('status')).toContainText('草稿已保存')
  page.once('dialog', (dialog) => void dialog.accept())
  await page.getByRole('button', { name: '提交报告' }).click()
  await expect(page.getByText('v2', { exact: true })).toBeVisible({ timeout: 15_000 })

  await page.goto(new URL(`/courses/${task.course_id}/reviews`, teacherBaseUrl).toString())
  const secondRound = page.getByRole('row').filter({ hasText: 'Integration Student' }).filter({ has: page.getByRole('cell', { name: '2', exact: true }) })
  await secondRound.getByRole('link', { name: '打开审核' }).click()
  await fillScores(page)
  await expect(page.getByRole('cell', { name: 'PASSED', exact: true })).toBeVisible({ timeout: 30_000 })
  await page.getByLabel('总体反馈').fill('修改内容符合要求。')
  page.once('dialog', (dialog) => void dialog.accept())
  await page.getByRole('button', { name: '通过' }).click()
  await expect(page.getByRole('status')).toContainText('审核已通过')
  await page.goto(new URL(`/tasks/${taskId}/review-result`, userBaseUrl).toString())
  await expect(page.getByText('修改内容符合要求。')).toBeVisible()
  await expect(page.getByText('APPROVE', { exact: true }).first()).toBeVisible()
})

test('@admin P10 review governance is read only', async ({ page }) => {
  await login(page, 'admin.integration@example.edu', process.env.ADMIN_WEB_URL ?? 'http://admin.localhost:8080')
  await page.goto('/review-monitor')
  await expect(page.getByRole('heading', { name: '审核监管' })).toBeVisible()
  await expect(page.getByRole('button', { name: /通过|退回|决定/ })).toHaveCount(0)
  await expect(page.locator('body')).not.toContainText('补充结果讨论后重新提交。')
  await checkResponsiveWidths(page)
})

test('@teacher P10 review queue is course scoped', async ({ page }) => {
  await login(page, 'teacher.integration@example.edu', teacherBaseUrl)
  await page.goto('/courses')
  await page.getByRole('link', { name: 'P03 课程协作实践' }).click()
  await page.getByRole('link', { name: '教师审核' }).click()
  await expect(page.getByRole('heading', { name: '教师审核' })).toBeVisible()
  await expect(page.getByRole('row').filter({ hasText: 'Integration Student' }).first()).toBeVisible()
})
