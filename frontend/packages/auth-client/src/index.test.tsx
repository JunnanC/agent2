import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SessionProvider, useSession } from './index'

function SessionStatus() {
  return <span>{useSession().status}</span>
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('SessionProvider', () => {
  it.each([
    [401, 'anonymous'],
    [403, 'denied'],
  ] as const)('clears cached account data after an HTTP %s session failure', async (status, state) => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    queryClient.setQueryData(['private-account-data'], { secret: true })
    const failure = {
      error: {
        code: status === 401 ? 'SESSION_EXPIRED' : 'TEACHER_QUALIFICATION_REQUIRED',
        message: 'session invalid',
        detail: {},
        trace_id: 'trace-session',
        retryable: false,
      },
    }
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response('{"data":{"csrf":"ready"}}', { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(failure), { status }))
    vi.stubGlobal('fetch', fetchMock)

    render(
      <QueryClientProvider client={queryClient}>
        <SessionProvider>
          <SessionStatus />
        </SessionProvider>
      </QueryClientProvider>,
    )

    await waitFor(() => expect(screen.getByText(state)).toBeTruthy())
    expect(queryClient.getQueryData(['private-account-data'])).toBeUndefined()
  })
})
