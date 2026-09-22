import { afterEach, describe, expect, it, vi } from 'vitest'

import { RequestIntent, apiRequest, apiRequestWithMetadata } from './index'

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = 'csrftoken=; Max-Age=0; path=/'
})

describe('api client', () => {
  it('keeps one idempotency key for retries with the same body', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(new Response('{"data":{}}', { status: 201 })))
    vi.stubGlobal('fetch', fetchMock)
    const intent = new RequestIntent('intent-1')
    const request = {
      method: 'POST',
      body: JSON.stringify({ name: 'one' }),
      headers: { 'Content-Type': 'application/json' },
      intent,
    }

    await apiRequest('/api/v2/things', request)
    await apiRequest('/api/v2/things', request)

    for (const call of fetchMock.mock.calls) {
      const headers = call[1]?.headers as Headers
      expect(headers.get('Idempotency-Key')).toBe('intent-1')
    }
    await expect(
      apiRequest('/api/v2/things', { ...request, body: JSON.stringify({ name: 'two' }) }),
    ).rejects.toThrow('create a new RequestIntent')
  })

  it('adds CSRF and If-Match and returns response metadata', async () => {
    document.cookie = 'csrftoken=csrf-value; path=/'
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{"data":{}}', {
        status: 200,
        headers: { ETag: '"4"', 'X-Request-ID': 'trace-1' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await apiRequestWithMetadata('/api/v2/things/one', {
      method: 'PATCH',
      body: '{}',
      ifMatch: '"3"',
    })

    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Headers
    expect(headers.get('X-CSRFToken')).toBe('csrf-value')
    expect(headers.get('If-Match')).toBe('"3"')
    expect(result.etag).toBe('"4"')
    expect(result.traceId).toBe('trace-1')
  })

  it('normalizes non-json gateway failures with trace information', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('upstream unavailable', {
          status: 503,
          headers: { 'X-Request-ID': 'trace-2' },
        }),
      ),
    )

    await expect(apiRequest('/api/v2/health')).rejects.toMatchObject({
      status: 503,
      traceId: 'trace-2',
      payload: { error: { code: 'HTTP_503', retryable: true } },
    })
  })

  it('rejects cross-origin request paths', async () => {
    await expect(apiRequest('https://example.invalid/api')).rejects.toThrow('same-origin')
  })
})
