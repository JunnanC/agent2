export function canPublishCourse(status: string, busy: boolean): boolean {
  return status === 'DRAFT' && !busy
}

export function canPublishExperiment({
  status,
  audienceMode,
  busy,
  rosterPending,
  rosterError,
  selectedCount,
}: {
  status: string
  audienceMode: string
  busy: boolean
  rosterPending: boolean
  rosterError: boolean
  selectedCount: number
}): boolean {
  if (status !== 'DRAFT' || busy) return false
  if (audienceMode !== 'SELECTED') return true
  return !rosterPending && !rosterError && selectedCount > 0
}
