import { describe, expect, it } from 'vitest'

import { canPublishCourse, canPublishExperiment } from './publish-actions'

describe('course publication action state', () => {
  it('enables publishing only for a draft course while idle', () => {
    expect(canPublishCourse('DRAFT', false)).toBe(true)
    expect(canPublishCourse('DRAFT', true)).toBe(false)
  })

  it.each(['PUBLISHED', 'CLOSED', 'ARCHIVED'])('does not expose publish for %s courses', (status) => {
    expect(canPublishCourse(status, false)).toBe(false)
  })
})

describe('experiment publication action state', () => {
  it('keeps an all-active draft publishable when the selected-audience query is disabled', () => {
    expect(canPublishExperiment({ status: 'DRAFT', audienceMode: 'ALL_ACTIVE', busy: false, rosterPending: true, rosterError: false, selectedCount: 0 })).toBe(true)
  })

  it('requires a selected student only for selected-audience drafts', () => {
    const base = { status: 'DRAFT', audienceMode: 'SELECTED', busy: false, rosterPending: false, rosterError: false }
    expect(canPublishExperiment({ ...base, selectedCount: 0 })).toBe(false)
    expect(canPublishExperiment({ ...base, selectedCount: 1 })).toBe(true)
  })
})
