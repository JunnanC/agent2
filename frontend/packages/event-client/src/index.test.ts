import { afterEach, describe, expect, it, vi } from 'vitest'

import { PortalEventClient, type EventConnectionState, type PortalEvent } from './index'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('PortalEventClient', () => {
  it('parses SSE frames and drops duplicate event ids', async () => {
    const events: PortalEvent[] = []
    const body = [
      'id: cursor-1',
      'event: workspace.snapshot.saved',
      'data: {"version":1}',
      '',
      'id: cursor-1',
      'event: workspace.snapshot.saved',
      'data: {"version":1}',
      '',
      '',
    ].join('\n')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body, { status: 200 })))
    const client = new PortalEventClient({
      onEvent: (event) => {
        events.push(event)
        client.stop()
      },
    })

    client.start()
    await vi.waitFor(() => expect(events).toHaveLength(1))

    expect(events[0]).toEqual({
      id: 'cursor-1',
      type: 'workspace.snapshot.saved',
      data: { version: 1 },
    })
    expect(client.lastEventId).toBe('cursor-1')
  })

  it('sends Last-Event-ID when reconnecting', async () => {
    let secondHeaders: Headers | undefined
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response('id: cursor-2\nevent: workspace.session.renewed\ndata: {}\n\n'),
      )
      .mockImplementationOnce((_url: string, init?: RequestInit) => {
        secondHeaders = init?.headers as Headers
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted')))
        })
      })
    vi.stubGlobal('fetch', fetchMock)
    const client = new PortalEventClient()

    client.start()
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))

    expect(secondHeaders?.get('Last-Event-ID')).toBe('cursor-2')
    client.stop()
  })

  it('falls back to polling after a connection failure', async () => {
    const states: EventConnectionState[] = []
    const events: PortalEvent[] = []
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    const client = new PortalEventClient({
      maxBackoffMs: 1,
      poll: async () => [
        { id: 'poll-1', type: 'workspace.snapshot.saved', data: { version: 3 } },
      ],
      onStateChange: (state) => states.push(state),
      onEvent: (event) => {
        events.push(event)
        client.stop()
      },
    })

    client.start()
    await vi.waitFor(() => expect(events).toHaveLength(1))

    expect(states).toContain('polling')
    expect(events[0]?.id).toBe('poll-1')
  })
})
