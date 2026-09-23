import { expect, test, type Page } from '@playwright/test'

const password = process.env.P02_E2E_PASSWORD ?? 'P08-Disposable-Seed-Only-2026!'
const teacherBaseUrl = process.env.TEACHER_WEB_URL ?? 'http://teacher.localhost:8080'
test.setTimeout(120_000)

async function login(page: Page, identifier: string, url = '/login') {
  await page.goto(url)
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

test('@user P09 submits a frozen report and @teacher previews and downloads it', async ({ page }) => {
  const evidenceName = `evidence-${Date.now()}.txt`
  await login(page, 'student.integration@example.edu')
  await page.goto('/tasks')
  await page.getByRole('link', { name: '查看' }).first().click()
  const taskId = new URL(page.url()).pathname.split('/').at(-1) ?? ''
  await expect(page.getByRole('heading', { name: '可执行操作' })).toBeVisible()
  await page.getByRole('link', { name: '进入工作区' }).click()
  await expect(page.getByRole('heading', { name: 'IDE / 内容' })).toBeVisible()
  await page.getByLabel('实验内容').fill('// P09 first workspace snapshot\nconsole.log("report")\n')
  await page.getByRole('button', { name: '立即保存' }).click()
  await expect(page.getByRole('status')).toContainText('已保存到工作区对象存储')

  await page.goto(`/tasks/${taskId}/report`)
  await page.getByLabel('Markdown 报告正文').fill('# P09 integration report\n\nVerified workspace output.')
  await page.getByRole('button', { name: '保存草稿' }).click()
  await expect(page.getByRole('status')).toContainText('草稿已保存')

  await page.goto(`/tasks/${taskId}`)
  await page.getByRole('link', { name: '进入工作区' }).click()
  await expect(page.getByRole('heading', { name: 'IDE / 内容' })).toBeVisible()
  await page.getByLabel('实验内容').fill('// P09 latest workspace snapshot\nconsole.log("final")\n')
  await page.getByRole('button', { name: '立即保存' }).click()
  await expect(page.getByRole('status')).toContainText('已保存到工作区对象存储')

  await page.goto(`/tasks/${taskId}/report`)
  await page.getByLabel('Markdown 报告正文').fill('# P09 integration report\n\nVerified the latest workspace output.')
  await page.getByRole('button', { name: '保存草稿' }).click()
  await expect(page.getByRole('status')).toContainText('草稿已保存')
  await checkResponsiveWidths(page)

  await page.getByLabel('上传附件').setInputFiles({
    name: evidenceName,
    mimeType: 'text/plain',
    buffer: Buffer.from('P09 scanned evidence'),
  })
  const evidenceRow = page.getByRole('row').filter({ hasText: evidenceName })
  await expect(evidenceRow.getByRole('cell', { name: 'CLEAN' })).toBeVisible({ timeout: 30_000 })
  page.once('dialog', (dialog) => void dialog.accept())
  await page.getByRole('button', { name: '提交报告' }).click()
  await expect(page.getByText('v1', { exact: true })).toBeVisible({ timeout: 15_000 })

  const task = await page.evaluate(async (id) => {
    const response = await fetch(`/api/v2/tasks/${id}`, { headers: { 'X-Portal': 'USER' } })
    return (await response.json()).data
  }, taskId) as { course_id: string }
  await page.goto(new URL('/login', teacherBaseUrl).toString())
  await page.getByLabel('邮箱或用户名').fill('teacher.integration@example.edu')
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).not.toHaveURL(/\/login$/, { timeout: 15_000 })
  await page.goto(`${teacherBaseUrl}/courses/${task.course_id}/tasks/${taskId}/submission`)
  await expect(page.getByRole('heading', { name: '成果预览' })).toBeVisible()
  await expect(page.locator('.report-preview')).toContainText('Verified the latest workspace output.')
  const teacherEvidenceRow = page.getByRole('row').filter({ hasText: evidenceName })
  await expect(teacherEvidenceRow.getByRole('cell', { name: evidenceName, exact: true })).toBeVisible()
  const downloadPromise = page.waitForEvent('download')
  await teacherEvidenceRow.getByRole('button', { name: '下载' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe(evidenceName)
})

test('@admin P09 scan summary is available without attachment contents', async ({ page }) => {
  await login(page, 'admin.integration@example.edu')
  await page.goto('/report-scan-anomalies')
  await expect(page.getByRole('heading', { name: '附件扫描异常' })).toBeVisible()
  await expect(page.locator('body')).not.toContainText('P09 scanned evidence')
})
