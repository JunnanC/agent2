import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { TemplateVersionsPage } from './p05'

function response(data: unknown, status = 200) {
  return new Response(JSON.stringify({ data, meta: { trace_id: 'trace-test' } }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('P16-E template capabilities', () => {
  it('defaults unverified capabilities off and sends selected capabilities', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/template-options')) return response({
        runtime_adapters: [{ public_id: 'adapter-1', name: 'Docker Local', runtime_type: 'CONTAINER' }],
        images: [{ public_id: 'image-1', repository: 'algorithm-workspace', display_tag: 'p16' }],
        resource_profiles: [{ public_id: 'profile-1', name: '小型', cpu_millicores: 1000 }],
        materials: [],
      })
      if (url.endsWith('/templates/template-1/versions') && init?.method === 'POST') {
        const capabilities = JSON.parse(String(init.body)).workspace_capabilities
        expect(capabilities).toEqual({
          require_gateway: true, webide: true, notebook: false, terminal: false,
          preview: false, snapshot: true, checkpoint: true,
        })
        return response({ public_id: 'version-1' }, 201)
      }
      if (url.endsWith('/templates/template-1/versions')) return response([])
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/courses/course-1/templates/template-1']}>
          <Routes><Route path="/courses/:courseId/templates/:templateId" element={<TemplateVersionsPage />} /><Route path="/courses/:courseId/template-versions/:versionId" element={<div>版本已创建</div>} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    fireEvent.click(await screen.findByRole('button', { name: '新建版本' }))
    const webide = await screen.findByRole('checkbox', { name: 'WebIDE' }) as HTMLInputElement
    expect(webide.checked).toBe(false)
    expect((screen.getByRole('checkbox', { name: '独立 Terminal' }) as HTMLInputElement).checked).toBe(false)
    fireEvent.click(webide)
    fireEvent.click(screen.getByRole('checkbox', { name: '快照同步' }))
    fireEvent.click(screen.getByRole('checkbox', { name: '检查点' }))
    fireEvent.click(screen.getByRole('button', { name: '创建草稿' }))

    await waitFor(() => expect(screen.getByText('版本已创建')).toBeTruthy())
  })
})
