import { ApiError } from '@edu/api-client'

function detailMessages(detail: unknown): string[] {
  if (typeof detail === 'string' && detail.trim()) return [detail.trim()]
  if (Array.isArray(detail)) return detail.flatMap(detailMessages)
  if (detail && typeof detail === 'object') return Object.values(detail).flatMap(detailMessages)
  return []
}

export function messageFor(error: unknown): string {
  if (!(error instanceof ApiError)) return '请求未完成，请稍后重试。'
  if (error.status === 409) return '当前状态已变化，请刷新后重试。'
  if (error.status === 412) return '内容已被其他操作更新，请刷新后重试。'
  const details = [...new Set(detailMessages(error.payload.error.detail))]
  if (details.length) return details.join('；')
  return error.payload.error.message
}
