import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AgentMessageData } from '@edu/api-client'

import { AgentOrb } from './p12'

const eventHarness = vi.hoisted(() => ({ onEvent: undefined as (() => void) | undefined }))

vi.mock('@edu/event-client', () => ({
  PortalEventClient: class {
    constructor(options: { onEvent?: () => void }) { eventHarness.onEvent = options.onEvent }
    start = vi.fn()
    stop = vi.fn()
  },
}))

const agentSession = {
  public_id: 'agent-session-1',
  course_id: 'course-1',
  enrollment_id: 'enrollment-1',
  task_id: 'task-1',
  mode: 'WORKSPACE_ASSIST',
  status: 'ACTIVE',
  profile_id: 'profile-1',
  profile_version: 1,
  row_version: 1,
  trace_id: 'trace-session',
}

const userMessage: AgentMessageData = {
  public_id: 'message-user-1',
  role: 'USER',
  body: '解释当前步骤',
  status: 'COMPLETE',
  citation_status: 'NONE',
  token_count: 0,
  created_at: '2026-09-28T01:00:00Z',
  trace_id: 'trace-user',
  citations: [],
  tool_calls: [],
}

const assistantMessage: AgentMessageData = {
  public_id: 'message-assistant-1',
  role: 'ASSISTANT',
  body: '先检查公开测试摘要，再定位失败步骤。',
  status: 'COMPLETE',
  citation_status: 'CITED',
  token_count: 18,
  created_at: '2026-09-28T01:00:01Z',
  trace_id: 'trace-assistant',
  citations: [
    { public_id: 'citation-1', source_version_id: 'source-1', title: '公开实验手册', snippet: '只显示当前课程资料。', score: 0.9, accessible: true, asset_id: null },
    { public_id: 'citation-hidden', source_version_id: 'source-hidden', title: '不可访问资料', snippet: '不应显示', score: 0.8, accessible: false, asset_id: null },
  ],
  tool_calls: [],
}

function response(data: unknown, status = 200) {
  return new Response(JSON.stringify({ data, meta: { trace_id: 'trace-test' } }), {
    status,
    headers: { 'Content-Type': 'application/json', ETag: '"1"' },
  })
}

function renderOrb(workspaceAvailable = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><AgentOrb taskId="task-1" workspaceAvailable={workspaceAvailable} /></QueryClientProvider>)
}

afterEach(() => {
  eventHarness.onEvent = undefined
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('P15-E workspace Agent drawer', () => {
  it('lazily creates only a WORKSPACE_ASSIST session and closes from the keyboard', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      void _init
      const url = String(input)
      if (url.endsWith('/tasks/task-1/agent-sessions')) return response(agentSession, 201)
      if (url.endsWith('/agent-sessions/agent-session-1')) return response(agentSession)
      if (url.endsWith('/agent-sessions/agent-session-1/messages')) return response([])
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderOrb()
    expect(fetchMock).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: '打开 Agent 助手' }))
    expect(await screen.findByRole('heading', { name: '实验助手' })).toBeTruthy()
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/tasks/task-1/agent-sessions'))).toBe(true))

    const createCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith('/tasks/task-1/agent-sessions'))
    expect(createCall?.[1]?.method).toBe('POST')
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({ mode: 'WORKSPACE_ASSIST' })
    expect(screen.queryByText('agent-session-1')).toBeNull()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('button', { name: '打开 Agent 助手' }).getAttribute('aria-expanded')).toBe('false')
  })

  it('refreshes an asynchronous reply from portal events and marks it unread while closed', async () => {
    let messageItems: AgentMessageData[] = [userMessage]
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      void _init
      const url = String(input)
      if (url.endsWith('/tasks/task-1/agent-sessions')) return response(agentSession, 201)
      if (url.endsWith('/agent-sessions/agent-session-1/messages')) return response(messageItems)
      if (url.endsWith('/agent-sessions/agent-session-1')) return response(agentSession)
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderOrb()
    fireEvent.click(screen.getByRole('button', { name: '打开 Agent 助手' }))
    expect(await screen.findByText('解释当前步骤')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '隐藏 Agent 助手' }))

    messageItems = [userMessage, assistantMessage]
    eventHarness.onEvent?.()

    expect(await screen.findByLabelText('1 条未读消息')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '打开 Agent 助手' }))
    expect(await screen.findByText('先检查公开测试摘要，再定位失败步骤。')).toBeTruthy()
    await waitFor(() => expect(screen.queryByLabelText('1 条未读消息')).toBeNull())
  })

  it('shows only accessible citations and submits answer feedback', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      void _init
      const url = String(input)
      if (url.endsWith('/tasks/task-1/agent-sessions')) return response(agentSession, 201)
      if (url.endsWith('/agent-sessions/agent-session-1/messages')) return response([assistantMessage])
      if (url.endsWith('/agent-sessions/agent-session-1')) return response(agentSession)
      if (url.endsWith('/agent-messages/message-assistant-1/feedback')) return response({ public_id: 'feedback-1', status: 'OPEN' }, 201)
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderOrb()
    fireEvent.click(screen.getByRole('button', { name: '打开 Agent 助手' }))
    expect(await screen.findByText('公开实验手册')).toBeTruthy()
    expect(screen.queryByText('不可访问资料')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: '有帮助' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/agent-messages/message-assistant-1/feedback'))).toBe(true))
    const feedbackCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith('/agent-messages/message-assistant-1/feedback'))
    expect(JSON.parse(String(feedbackCall?.[1]?.body))).toEqual({ rating: 'USEFUL' })
  })

  it('keeps tool approval scoped to one call and sends the current row version', async () => {
    const toolMessage = {
      ...assistantMessage,
      tool_calls: [{
        public_id: 'tool-call-1', session_id: agentSession.public_id, tool_name: 'workspace_draft', risk: 'HIGH', arguments_digest: 'redacted', trace_id: 'trace-tool',
        state: { public_id: 'tool-state-1', status: 'PENDING_APPROVAL', output: {}, error_code: '', row_version: 7 },
      }],
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      void _init
      const url = String(input)
      if (url.endsWith('/tasks/task-1/agent-sessions')) return response(agentSession, 201)
      if (url.endsWith('/agent-sessions/agent-session-1/messages')) return response([toolMessage])
      if (url.endsWith('/agent-sessions/agent-session-1')) return response(agentSession)
      if (url.endsWith('/agent-tool-calls/tool-call-1/decide')) return response({ public_id: 'tool-state-1', status: 'QUEUED', row_version: 8 })
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderOrb()
    fireEvent.click(screen.getByRole('button', { name: '打开 Agent 助手' }))
    fireEvent.click(await screen.findByRole('button', { name: '批准本次' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/agent-tool-calls/tool-call-1/decide'))).toBe(true))
    const decideCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith('/agent-tool-calls/tool-call-1/decide'))
    expect(new Headers(decideCall?.[1]?.headers).get('If-Match')).toBe('"7"')
    expect(JSON.parse(String(decideCall?.[1]?.body))).toEqual({ decision: 'APPROVED', reason: 'student confirmed' })
  })
})
