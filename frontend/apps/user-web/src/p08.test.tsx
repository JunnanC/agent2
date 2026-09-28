import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { WorkspaceLabPage } from './p08'

vi.mock('@edu/event-client', () => ({
  PortalEventClient: class {
    start = vi.fn()
    stop = vi.fn()
  },
}))

const baseTask = {
  public_id: 'task-1', course_id: 'course-1', publication_id: 'publication-1', enrollment_id: 'enrollment-1', student_id: 'student-1',
  title: 'P15 生命周期实验', template_version_id: 'template-version-1', template_name: '参考工作区', template_spec_digest: null,
  runtime_type: 'DOCKER', execution_spec: {}, runtime_adapter_id: 'adapter-1', runtime_adapter_driver: 'FAKE', runtime_adapter_config_ref: 'fake',
  image_id: 'image-1', image_digest: 'sha256:test', resource_profile_id: 'profile-1', resource_profile_snapshot: {}, report_required: false,
  terminal_target: null, progress: 0, window_start: '2026-01-01T00:00:00Z', window_end: '2027-01-01T00:00:00Z', effective_deadline: null,
  allowed_actions: [], blockers: [], current_failure: {}, provisioning: null, row_version: 1,
}

const provisioningJob = {
  public_id: 'job-1', task_id: 'task-1', course_id: 'course-1', status: 'PASSED', current_stage: 'WORKSPACE_READY', attempt_no: 1,
  attempt_count: 1, retryable: false, trace_id: 'trace-job', reservation: {}, instance: {}, stages: [], failure: null,
  events_channel: 'task:task-1', row_version: 1,
}

const session = {
  public_id: 'session-1', task_id: 'task-1', course_id: 'course-1', instance_id: 'instance-1', portal: 'USER', status: 'ACTIVE',
  capabilities: { webide: true, preview: true }, workspace_urls: { webide: '/workspace/session-1/webide' }, expires_at: '2026-10-01T00:15:00Z',
  revoked_at: null, current_version: 0, latest_client_seq: 0, row_version: 1, workspace_token: 'workspace-token',
}

const workbench = {
  task: { public_id: 'task-1', course_id: 'course-1', publication_id: 'publication-1', title: baseTask.title, description: '公开实验说明', status: 'IN_PROGRESS', deadline: null, assignment_deadline: null, report_required: false, report_strategy: 'COMPLETE', allowed_actions: [], allowed_operations: ['SAVE_SNAPSHOT', 'RUN_TEST', 'COMPLETE'], blockers: [], current_failure: {}, row_version: 2 },
  content: { description: '公开实验说明', objectives: ['完成工作区练习'], steps: ['打开 WebIDE'], constraints: [], deliverables: [], materials: [] },
  template: { public_id: 'template-1', name: '参考工作区', version_id: 'template-version-1', version_no: 1, dependencies: [], workspace_capabilities: { webide: true, preview: true }, manual_asset_id: null, starter_asset_id: null, report_template_asset_id: null },
  tests: { public_count: 1, count: 1, summary: [{ position: 1, summary: { title: '公开用例' } }], recent_execution: null },
  provisioning: { status: 'PASSED', job_id: 'job-1', current_stage: 'WORKSPACE_READY', progress: 100, retryable: false, failure: null, stages: [], events_channel: 'task:task-1' },
  submission: { required: false, kind: 'SYSTEM_ARTIFACT', strategy: 'COMPLETE', can_submit: true, blocked_reason: null, draft_status: null },
}

function response(data: unknown, status = 200) {
  return new Response(JSON.stringify({ data, meta: { trace_id: 'trace-test' } }), {
    status,
    headers: { 'Content-Type': 'application/json', ETag: '"1"' },
  })
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/tasks/task-1/lab']}>
        <Routes><Route path="/tasks/:taskId/lab" element={<WorkspaceLabPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('P15-B workspace lifecycle', () => {
  it('keeps provisioning read-only and does not issue a workspace session', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/workbench')) return response(workbench)
      if (url.endsWith('/provisioning-job')) return response({ ...provisioningJob, status: 'RUNNING', current_stage: 'CREATE' })
      if (url.endsWith('/tasks/task-1')) return response({ ...baseTask, status: 'PROVISIONING' })
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    expect(await screen.findByRole('heading', { name: '环境加载中' })).toBeTruthy()
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/enter'))).toBe(false)
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/workspace-sessions'))).toBe(false)
  })

  it('enters READY once through the explicit mutation', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/workbench')) return response(workbench)
      if (url.endsWith('/provisioning-job')) return response(provisioningJob)
      if (url.endsWith('/tasks/task-1/enter')) return response({ task: { ...baseTask, status: 'IN_PROGRESS', row_version: 2 }, session })
      if (url.endsWith('/tasks/task-1')) return response({ ...baseTask, status: 'READY' })
      if (init?.method === 'POST') throw new Error(`unexpected mutation: ${url}`)
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    expect(await screen.findByRole('heading', { name: 'IDE / 内容' })).toBeTruthy()
    await waitFor(() => expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith('/tasks/task-1/enter'))).toHaveLength(1))
  })

  it('renders the split workbench and preserves iframe mounts across runtime tabs', async () => {
    const sessionWithAllTabs = {
      ...session,
      capabilities: { webide: true, notebook: true, terminal: true, preview: true },
      workspace_urls: {
        webide: '/workspace/session-1/webide',
        notebook: '/workspace/session-1/notebook',
        terminal: '/workspace/session-1/terminal',
        preview: '/workspace/session-1/preview',
      },
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/workbench')) return response(workbench)
      if (url.endsWith('/provisioning-job')) return response(provisioningJob)
      if (url.endsWith('/tasks/task-1/enter')) return response({ task: { ...baseTask, status: 'IN_PROGRESS', row_version: 2 }, session: sessionWithAllTabs })
      if (url.endsWith('/tasks/task-1')) return response({ ...baseTask, status: 'READY' })
      if (init?.method === 'POST') throw new Error(`unexpected mutation: ${url}`)
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    expect(await screen.findByRole('heading', { name: 'IDE / 内容' })).toBeTruthy()
    expect(screen.getByRole('tab', { name: '实验内容' })).toBeTruthy()
    expect(screen.getByRole('tab', { name: '实验模板' })).toBeTruthy()
    expect(screen.getByRole('tab', { name: '测试说明' })).toBeTruthy()
    expect(document.querySelectorAll('iframe')).toHaveLength(4)
    expect(document.body.textContent).not.toContain('workspace-token')

    fireEvent.click(screen.getByRole('tab', { name: 'Notebook' }))
    expect(await screen.findByRole('heading', { name: 'Notebook' })).toBeTruthy()
    expect(document.querySelectorAll('iframe')).toHaveLength(4)
  })

  it('does not show or mount disabled runtime capabilities', async () => {
    const restrictedSession = {
      ...session,
      capabilities: { webide: true, notebook: false, terminal: false, preview: false },
      workspace_urls: {
        webide: '/workspace/session-1/webide',
        notebook: '/workspace/session-1/notebook',
        terminal: '/workspace/session-1/terminal',
        preview: '/workspace/session-1/preview',
      },
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/workbench')) return response(workbench)
      if (url.endsWith('/provisioning-job')) return response(provisioningJob)
      if (url.endsWith('/tasks/task-1/enter')) return response({ task: { ...baseTask, status: 'IN_PROGRESS', row_version: 2 }, session: restrictedSession })
      if (url.endsWith('/tasks/task-1')) return response({ ...baseTask, status: 'READY' })
      if (init?.method === 'POST') throw new Error(`unexpected mutation: ${url}`)
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    expect(await screen.findByRole('heading', { name: 'IDE / 内容' })).toBeTruthy()
    expect(screen.queryByRole('tab', { name: 'Notebook' })).toBeNull()
    expect(screen.queryByRole('tab', { name: 'Terminal' })).toBeNull()
    expect(screen.queryByRole('tab', { name: 'Preview' })).toBeNull()
    expect(document.querySelectorAll('iframe')).toHaveLength(1)
    expect((document.querySelector('iframe') as HTMLIFrameElement).src).toContain('/workspace/session-1/webide')
  })
})
