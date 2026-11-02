import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { PlatformInstancesPage } from './instancesAndCompensations'

vi.mock('@edu/event-client', () => ({
  PortalEventClient: class {
    start = vi.fn()
    stop = vi.fn()
  },
}))

afterEach(() => vi.restoreAllMocks())

describe('Platform runtime recovery', () => {
  it('distinguishes an external orphan from a terminal resource leak', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      data: [
        { public_id: 'instance-1', task_id: 'task-1', course_id: 'course-1', student_id: 'student-1', status: 'READY', external_id: 'fake-1', external_status: 'READY', orphan: false, resource_leak: true, row_version: 2, trace_id: 'trace-1' },
        { public_id: 'external:fake-2', task_id: '', course_id: '', student_id: '', status: 'ORPHANED', external_id: 'fake-2', external_status: 'READY', orphan: true, resource_leak: true, row_version: 1, trace_id: '' },
      ],
      meta: { page: 1, page_size: 20, total: 2 },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter><PlatformInstancesPage /></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByRole('heading', { name: '实例与孤儿检测' })).toBeTruthy()
    expect(screen.getByText('终态资源泄漏')).toBeTruthy()
    expect(screen.getAllByText('外部孤儿').length).toBeGreaterThan(0)
  })
})
