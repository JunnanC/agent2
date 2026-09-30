import type { TaskData } from '@edu/api-client'

const workspaceEntryStatuses = new Set<TaskData['status']>([
  'PROVISIONING',
  'READY',
  'IN_PROGRESS',
  'REPORT_DRAFT',
])

export function canEnterWorkspace(status: TaskData['status']): boolean {
  return workspaceEntryStatuses.has(status)
}
