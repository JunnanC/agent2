import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ReviewMonitorPage } from './reviewMonitor'

afterEach(() => vi.restoreAllMocks())

describe('P10 platform review monitor', () => {
  it('renders only aggregate review governance facts', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      data: {
        review_counts: { PENDING: 2, IN_REVIEW: 1, DECIDED: 4 },
        auto_check_failures: 3,
        similarity_counts: { COMPLETED: 5 },
        latest_trace_id: 'trace-monitor',
      },
      meta: { trace_id: 'trace-request' },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><ReviewMonitorPage /></QueryClientProvider>)
    expect(await screen.findByRole('heading', { name: '审核监管' })).toBeTruthy()
    expect(screen.getByText('trace-monitor')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /通过|退回|决定/ })).toBeNull()
    expect(screen.queryByText(/报告正文|逐项评分|批注证据/)).toBeNull()
  })
})
