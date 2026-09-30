import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { TeachingArchivesPage } from './p11'

vi.mock('@edu/event-client', () => ({
  PortalEventClient: class {
    start = vi.fn()
    stop = vi.fn()
  },
}))

afterEach(() => vi.restoreAllMocks())

describe('P11 teaching archives', () => {
  it('renders archive verification status from the course-scoped API', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      data: [{
        public_id: 'archive-1', task_id: 'task-1', course_id: 'course-1', student_id: 'student-1', student_name: 'Student One',
        status: 'PASSED', terminal_target: 'COMPLETED', task_status: 'COMPLETED', safe_recycle_at: '2026-09-24T12:00:00Z',
        attempt_count: 1, max_attempts: 5, row_version: 3, failure: null, compensation: null, manifest: {},
        verifications: [{ public_id: 'verify-1', result: 'PASSED' }], recycle: {},
      }],
      meta: { page: 1, page_size: 20, total: 1 },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/courses/course-1/archives']}><Routes><Route path="/courses/:courseId/archives" element={<TeachingArchivesPage />} /></Routes></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByRole('heading', { name: '课程成果归档' })).toBeTruthy()
    expect(screen.getByText('Student One')).toBeTruthy()
    expect(screen.getAllByText('PASSED').length).toBeGreaterThan(0)
  })
})
