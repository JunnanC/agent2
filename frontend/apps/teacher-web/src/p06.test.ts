import { describe, expect, it } from 'vitest'

import { ApiError } from '@edu/api-client'

import { messageFor } from './p06-errors'

describe('P06 error messages', () => {
  it('shows field validation details instead of the generic API message', () => {
    const error = new ApiError(400, {
      error: {
        code: 'VALIDATION_ERROR',
        message: '请求无法处理',
        detail: { window_end: ['必须晚于 window_start'] },
        trace_id: 'trace-p06',
        retryable: false,
      },
    })

    expect(messageFor(error)).toBe('必须晚于 window_start')
  })

  it('shows publication audience details returned by the service', () => {
    const error = new ApiError(422, {
      error: {
        code: 'PUBLICATION_VALIDATION_ERROR',
        message: '实验发布配置无效',
        detail: { selected_enrollment_ids: '指定学生模式至少选择一名在读学生' },
        trace_id: 'trace-p06',
        retryable: false,
      },
    })

    expect(messageFor(error)).toBe('指定学生模式至少选择一名在读学生')
  })
})
