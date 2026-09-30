import { expect, request as playwrightRequest, test, type Frame, type Page } from '@playwright/test'

const password = process.env.P02_E2E_PASSWORD ?? 'P08-Disposable-Seed-Only-2026!'
const taskTitle = process.env.P16_E2E_TASK_TITLE ?? ''

test.setTimeout(240_000)

async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel('邮箱或用户名').fill('student.integration@example.edu')
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).not.toHaveURL(/\/login$/, { timeout: 15_000 })
}

async function workspaceFrame(page: Page): Promise<Frame> {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    await expect.poll(() => page.frames().some((frame) => /\/workspace\/[^/]+\/webide/.test(frame.url()))).toBe(true)
    const frame = page.frames().find((item) => /\/workspace\/[^/]+\/webide/.test(item.url()))
    if (!frame) throw new Error('P16 WebIDE iframe did not attach to a workspace session')
    await frame.locator('body').waitFor({ state: 'visible', timeout: 30_000 })
    const bodyText = await frame.locator('body').innerText()
    if (!bodyText.includes('WORKSPACE_SESSION_INVALID') && !bodyText.includes('WORKSPACE_SESSION_REVOKED')) return frame
    if (attempt === 1) throw new Error(`P16 WebIDE session remained invalid: ${bodyText}`)
    await page.reload()
    await expect(page.getByRole('heading', { name: 'IDE / 内容' })).toBeVisible({ timeout: 120_000 })
  }
  throw new Error('P16 WebIDE iframe retry exhausted')
}

async function editMainPy(page: Page, source: string) {
  const frame = await workspaceFrame(page)
  const editor = frame.getByRole('code').first()
  if (!(await editor.isVisible())) {
    const mainPy = frame.getByRole('treeitem', { name: /^main\.py/ })
    await expect(mainPy).toBeVisible({ timeout: 60_000 })
    await mainPy.dblclick()
  }
  await expect(editor).toBeVisible({ timeout: 30_000 })
  await editor.click()
  await page.keyboard.press('Control+A')
  await page.keyboard.insertText(source)
  await page.keyboard.press('Control+S')
  await page.waitForTimeout(750)
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
}

test('@user P16 Docker local WebIDE, snapshot, restore, boundary, and cleanup journey', async ({ page, context }) => {
  test.skip(!taskTitle, 'Run through scripts/verify-p16-integration.ps1.')

  await login(page)
  await page.goto('/tasks')
  await expect(page.getByRole('heading', { name: '我的实验' })).toBeVisible()
  const taskRow = page.getByRole('row').filter({ hasText: taskTitle })
  await expect(taskRow).toHaveCount(1)
  await taskRow.getByRole('link', { name: '查看' }).click()
  await expect(page.getByRole('heading', { name: taskTitle })).toBeVisible()
  const taskId = /\/tasks\/([^/]+)$/.exec(new URL(page.url()).pathname)?.[1]
  expect(taskId).toBeTruthy()

  const start = page.getByRole('button', { name: '开始装载' })
  if (await start.count()) {
    const responsePromise = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith(`/api/v2/tasks/${taskId}/start`))
    await start.click()
    expect((await responsePromise).status()).toBe(202)
  }
  await page.goto(`/tasks/${taskId}/lab`)
  await expect(page.getByRole('heading', { name: 'IDE / 内容' })).toBeVisible({ timeout: 120_000 })

  const workbenchResponse = await page.request.get(`/api/v2/tasks/${taskId}/workbench`)
  expect(workbenchResponse.ok()).toBe(true)
  const workbench = await workbenchResponse.json()
  expect(workbench.data.workspace.mode).toBe('RUNTIME_IDE')
  expect(workbench.data.workspace.capture_supported).toBe(true)
  expect(page.getByRole('tab', { name: 'WebIDE' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tab', { name: 'Terminal' })).toHaveCount(0)
  await expect(page.getByRole('tab', { name: 'Preview' })).toHaveCount(0)

  const saveButton = page.getByRole('button', { name: '同步并保存' })
  await expect(saveButton).toBeEnabled({ timeout: 120_000 })
  const firstSource = 'import sys\n\nvalue = sys.stdin.read().strip()\nprint(value.upper())\n# P16 checkpoint\n'
  await editMainPy(page, firstSource)
  await saveButton.click()
  await expect(page.getByRole('status')).toContainText(/已同步 v\d+/, { timeout: 45_000 })
  await page.getByRole('button', { name: '运行测试' }).click()
  await expect(page.getByRole('status')).toContainText('测试通过', { timeout: 60_000 })

  const syncStatus = await page.getByRole('region', { name: '实验操作' }).innerText()
  expect(syncStatus).toMatch(/已同步 v\d+/)
  const checkpointName = `P16 checkpoint ${Date.now()}`
  await page.getByRole('button', { name: '检查点' }).click()
  await expect(page.getByRole('heading', { name: '命名检查点' })).toBeVisible()
  await page.getByLabel('检查点名称').fill(checkpointName)
  await page.getByRole('button', { name: '创建检查点' }).click()
  await expect(page.getByRole('status')).toContainText('检查点已创建', { timeout: 30_000 })
  const checkpointRow = page.getByRole('row').filter({ hasText: checkpointName })
  await expect(checkpointRow).toHaveCount(1)

  const changedSource = 'import sys\n\nvalue = sys.stdin.read().strip()\nprint(value.lower())\n# P16 changed after checkpoint\n'
  await page.getByRole('link', { name: '返回实验室' }).click()
  await expect(page.getByRole('heading', { name: 'IDE / 内容' })).toBeVisible()
  await editMainPy(page, changedSource)
  await page.getByRole('button', { name: '同步并保存' }).click()
  await expect(page.getByRole('status')).toContainText(/已同步 v\d+/, { timeout: 45_000 })

  await page.getByRole('button', { name: '检查点' }).click()
  await expect(page.getByRole('heading', { name: '命名检查点' })).toBeVisible()
  await page.getByRole('row').filter({ hasText: checkpointName }).getByRole('button', { name: '恢复' }).click()
  await expect(page).toHaveURL(new RegExp(`/tasks/${taskId}/lab\\?workspace_refresh=`), { timeout: 60_000 })
  await expect(page.getByRole('heading', { name: 'IDE / 内容' })).toBeVisible()
  const restoredFrame = await workspaceFrame(page)
  await expect(restoredFrame.getByRole('code').first()).toContainText('P16 checkpoint', { timeout: 30_000 })

  const restoredWorkbenchResponse = await page.request.get(`/api/v2/tasks/${taskId}/workbench`)
  expect(restoredWorkbenchResponse.ok()).toBe(true)
  const restoredWorkbench = await restoredWorkbenchResponse.json()
  const restoredSnapshotId = restoredWorkbench.data.workspace.last_synchronized_snapshot_id as string
  expect(restoredSnapshotId).toBeTruthy()
  const executionResponse = page.waitForResponse((response) => response.request().method() === 'GET' && response.url().includes(`/tasks/${taskId}/execution-runs/`) && response.status() === 200)
  await expect(page.getByRole('button', { name: '运行测试' })).toBeEnabled({ timeout: 30_000 })
  await page.getByRole('button', { name: '运行测试' }).click()
  await expect(page.getByRole('status')).toContainText('测试通过', { timeout: 60_000 })
  const executionResult = await executionResponse
  expect((await executionResult.json()).data.snapshot_id).toBe(restoredSnapshotId)
  const ideFrameUrl = page.frames().find((frame) => /\/workspace\/[^/]+\/webide/.test(frame.url()))?.url()
  expect(ideFrameUrl).toBeTruthy()
  const workspacePath = new URL(ideFrameUrl as string).pathname.replace(/\/webide.*$/, '/webide/')
  const isolatedRequest = await playwrightRequest.newContext({ baseURL: process.env.USER_WEB_URL ?? 'http://user.localhost:8080' })
  try {
    const denied = await isolatedRequest.get(workspacePath, { headers: { 'X-Workspace-Token': 'p16-invalid-token' } })
    expect([401, 403]).toContain(denied.status())
  } finally {
    await isolatedRequest.dispose()
  }
  const teacherBoundary = await context.request.get(`${process.env.TEACHER_WEB_URL ?? 'http://teacher.localhost:8080'}${workspacePath}`)
  expect([401, 403, 404]).toContain(teacherBoundary.status())

  await page.goto(`/tasks/${taskId}/lab`)
  await expect(page.getByRole('heading', { name: 'IDE / 内容' })).toBeVisible()
  for (const viewport of [{ width: 1440, height: 900 }, { width: 920, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    await expectNoHorizontalOverflow(page)
    await expect(page.getByRole('region', { name: '实验操作' })).toBeVisible()
  }

  await expect(page.getByRole('button', { name: '提交实验' })).toBeEnabled()
  page.once('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: '提交实验' }).click()
  await expect(page.getByRole('heading', { name: '实验已提交' })).toBeVisible({ timeout: 30_000 })

  const localValues = await page.evaluate(() => Object.entries(localStorage))
  expect(localValues.filter(([key, value]) => /session|token|cookie|x-amz|secret|authorization/i.test(`${key}:${value}`))).toEqual([])
  expect(page.url()).not.toMatch(/workspace_?token|signature|x-amz-/i)
  const cookies = await context.cookies()
  expect(cookies.filter((cookie) => /session|workspace/i.test(cookie.name)).every((cookie) => cookie.httpOnly)).toBe(true)
})
