import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { UserReviewResultPage } from './p10'

vi.mock('@edu/event-client', () => ({
  openPortalEventStream: () => ({ stop: vi.fn() }),
}))

afterEach(() => vi.restoreAllMocks())

describe('P10 student review result', () => {
  it('keeps draft scoring private while a round is in progress', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      data: {
        task_id: 'task-1', task_status: 'UNDER_REVIEW', allowed_actions: [],
        rounds: [{ review_id: 'review-1', round_no: 1, status: 'IN_REVIEW', scores: null, annotations: [], decision: null }],
      },
      meta: { trace_id: 'trace-1' },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/tasks/task-1/review-result']}><Routes><Route path="/tasks/:taskId/review-result" element={<UserReviewResultPage />} /></Routes></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByRole('heading', { name: '审核结果' })).toBeTruthy()
    expect(screen.getByText('教师正在审核，本轮评分和批注将在定案后显示。')).toBeTruthy()
    expect(screen.queryByRole('columnheader', { name: '得分' })).toBeNull()
  })
})
