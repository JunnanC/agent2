import { execFileSync } from 'node:child_process'
import { expect, test, type Page } from '@playwright/test'

const password = process.env.P02_E2E_PASSWORD ?? 'P08-Disposable-Seed-Only-2026!'
const taskTitle = process.env.P15_E2E_TASK_TITLE ?? ''
const composeProject = process.env.P15_COMPOSE_PROJECT ?? ''
const composeFile = process.env.P15_COMPOSE_FILE ?? ''

test.setTimeout(180_000)

async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel('邮箱或用户名').fill('student.integration@example.edu')
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).not.toHaveURL(/\/login$/, { timeout: 15_000 })
}

function startRuntimeWorker() {
  execFileSync(
    'docker',
    [
      'compose', '--profile', 'p14', '-p', composeProject, '-f', composeFile,
      'up', '--detach', '--no-deps', 'runtime-worker',
    ],
    { stdio: 'inherit' },
  )
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
}

test('@user P15-F complete workbench journey and security boundary', async ({ page, context }) => {
  test.skip(!taskTitle || !composeProject || !composeFile, 'Run through scripts/verify-p15-integration.ps1.')

  const requestedUrls: string[] = []
  page.on('request', (request) => requestedUrls.push(request.url()))

  await login(page)
  await page.goto('/tasks')
  await expect(page.getByRole('heading', { name: '我的实验' })).toBeVisible()
  const taskRow = page.getByRole('row').filter({ hasText: taskTitle })
  await expect(taskRow).toHaveCount(1)
  await taskRow.getByRole('link', { name: '查看' }).click()
  await expect(page.getByRole('heading', { name: taskTitle })).toBeVisible()
  const detailUrl = page.url()
  const taskId = /\/tasks\/([^/]+)$/.exec(new URL(detailUrl).pathname)?.[1]
  expect(taskId).toBeTruthy()

  const startResponsePromise = page.waitForResponse(
    (response) => response.request().method() === 'POST' && response.url().endsWith(`/api/v2/tasks/${taskId}/start`),
  )
  await page.getByRole('button', { name: '开始装载' }).click()
  const startResponse = await startResponsePromise
  expect(startResponse.status()).toBe(202)
  const startPayload = await startResponse.json()
  expect(startPayload.data.status).toBe('QUEUED')

  await page.goto(`/tasks/${taskId}/lab`)
  await expect(page.getByRole('heading', { name: '环境加载中' })).toBeVisible()
  await expect(page.getByText(/0%.*轮询同步|0%.*实时事件/)).toBeVisible()
  for (const stage of ['配额检查', '准备镜像', '创建环境', '连接网络', '启动探测', '工作区就绪']) {
    await expect(page.getByRole('cell', { name: stage })).toBeVisible()
  }

  startRuntimeWorker()
  await expect(page.getByRole('heading', { name: 'IDE / 内容' })).toBeVisible({ timeout: 60_000 })

  const workbenchResponse = await page.request.get(`/api/v2/tasks/${taskId}/workbench`)
  expect(workbenchResponse.ok()).toBe(true)
  const workbenchText = await workbenchResponse.text()
  for (const sensitiveField of ['hidden_tests', 'expected_output', 'judge_path', 'docker_service_id', 'workspace_token', 'signed_url']) {
    expect(workbenchText).not.toContain(`"${sensitiveField}"`)
  }

  await expect(page.getByRole('tab', { name: '实验内容' })).toHaveAttribute('aria-selected', 'true')
  await page.getByRole('tab', { name: '实验模板' }).click()
  await expect(page.getByText('模板资产不会直接暴露对象存储地址。')).toBeVisible()
  await page.getByRole('tab', { name: '测试说明' }).click()
  await expect(page.getByText(/公开用例 1 个/)).toBeVisible()

  for (const runtimeTab of ['Terminal', 'Preview']) {
    await page.getByRole('tab', { name: runtimeTab }).click()
    await expect(page.getByRole('heading', { name: runtimeTab })).toBeVisible()
  }
  await page.getByRole('tab', { name: 'WebIDE' }).click()

  const draft = page.getByRole('textbox', { name: '实验内容' })
  await draft.fill('// P15 automatic save\nconsole.log("autosaved")\n')
  await expect(page.getByText('已保存', { exact: true })).toBeVisible({ timeout: 20_000 })
  await draft.fill('// P15 manual save\nconsole.log("submitted")\n')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('已保存到工作区对象存储')

  const checkpointName = `P15 checkpoint ${Date.now()}`
  await page.getByRole('button', { name: '检查点' }).click()
  await page.getByLabel('检查点名称').fill(checkpointName)
  await page.getByRole('button', { name: '创建检查点' }).click()
  await expect(page.getByRole('status')).toContainText('检查点已创建')
  await page.getByRole('link', { name: '返回实验室' }).click()
  await expect(page.getByRole('heading', { name: 'IDE / 内容' })).toBeVisible()

  await page.getByRole('button', { name: '运行测试' }).click()
  await expect(page.getByRole('status')).toContainText('测试通过', { timeout: 45_000 })

  await page.getByRole('button', { name: '打开 Agent 助手' }).click()
  await page.getByRole('button', { name: '解释当前步骤' }).click()
  await expect(page.locator('.task-agent-message--assistant').last()).toBeVisible({ timeout: 45_000 })
  await page.getByRole('button', { name: '关闭 Agent 助手' }).click()

  for (const viewport of [{ width: 1440, height: 900 }, { width: 920, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    await expectNoHorizontalOverflow(page)
    await expect(page.getByRole('region', { name: '实验操作' })).toBeVisible()
  }

  await page.setViewportSize({ width: 1440, height: 900 })
  page.once('dialog', (dialog) => dialog.accept())
  await expect(page.getByRole('button', { name: '提交实验' })).toBeEnabled()
  await page.getByRole('button', { name: '提交实验' }).click()
  await expect(page.getByRole('heading', { name: '实验已提交' })).toBeVisible({ timeout: 20_000 })

  const localValues = await page.evaluate(() => Object.entries(localStorage))
  expect(localValues.filter(([key, value]) => /session|token|cookie|report.body/i.test(`${key}:${value}`))).toEqual([])
  expect(requestedUrls.filter((url) => /[?&](workspace_?token|signature|x-amz-(?:credential|signature|security-token))=/i.test(url))).toEqual([])
  expect(page.url()).not.toMatch(/workspace_?token|signature|x-amz-/i)
  const cookies = await context.cookies()
  expect(cookies.filter((cookie) => /session|workspace/i.test(cookie.name)).every((cookie) => cookie.httpOnly)).toBe(true)
})
