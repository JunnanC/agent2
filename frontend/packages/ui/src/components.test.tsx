import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ErrorView, HealthView, RequestStateView } from './components'

describe('foundation states', () => {
  it('renders the healthy service state with its trace id', () => {
    render(
      <HealthView
        title="用户端"
        status="ok"
        detail="django · v2-p00"
        traceId="abc123"
        retry={vi.fn()}
      />,
    )

    expect(screen.getByRole('heading', { name: '用户端' })).toBeInTheDocument()
    expect(screen.getByText('服务正常')).toBeInTheDocument()
    expect(screen.getByText('abc123')).toBeInTheDocument()
  })

  it('renders a navigable error state', () => {
    render(<ErrorView code="403" title="无权访问" message="当前会话不能访问此页面。" />)

    expect(screen.getByRole('heading', { name: '无权访问' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '返回状态页' })).toHaveAttribute('href', '/health')
  })

  it.each([
    ['loading', '正在加载'],
    ['empty', '暂无数据'],
    ['forbidden', '无权访问'],
    ['conflict', '当前状态已发生变化'],
    ['stale', '内容已被更新'],
    ['precondition', '缺少更新条件'],
    ['rate-limited', '请求过于频繁'],
  ] as const)('renders the shared %s request state', (state, title) => {
    render(<RequestStateView state={state} />)
    expect(screen.getByRole('heading', { name: title })).toBeInTheDocument()
  })

  it('renders retry and trace controls for request failures', () => {
    render(<RequestStateView state="error" traceId="trace-123" onRetry={vi.fn()} />)

    expect(screen.getByText('trace-123')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '复制 Trace ID' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
  })
})
