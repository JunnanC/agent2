import { render, screen } from '@testing-library/react'
import type { TaskData } from '@edu/api-client'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { TaskTable } from './p06'
import { canEnterWorkspace } from './workspace-actions'

describe('P06 workspace entry visibility', () => {
  it.each(['PROVISIONING', 'READY', 'IN_PROGRESS', 'REPORT_DRAFT'] as const)(
    'allows the workspace entry for %s tasks',
    (status) => {
      expect(canEnterWorkspace(status)).toBe(true)
    },
  )

  it.each(['ASSIGNED', 'FAILED', 'UNDER_REVIEW', 'COMPLETED', 'CANCELLED', 'EXPIRED'] as const)(
    'does not expose the workspace entry for %s tasks',
    (status) => {
      expect(canEnterWorkspace(status)).toBe(false)
    },
  )
})

describe('task list workspace actions', () => {
  it('shows a direct workspace entry while provisioning', () => {
    const task = {
      public_id: 'task-1',
      title: '装载中的实验',
      course_id: 'course-1',
      template_name: '容器模板',
      runtime_type: 'CONTAINER',
      status: 'PROVISIONING',
      effective_deadline: null,
    } as TaskData

    render(<MemoryRouter><TaskTable tasks={[task]} /></MemoryRouter>)

    expect(screen.getByRole('link', { name: '进入工作区' }).getAttribute('href')).toBe('/tasks/task-1/lab')
  })
})
