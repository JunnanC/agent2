import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'

const root = new URL('./', import.meta.url)
const index = await readFile(new URL('index.html', root), 'utf8')
const app = await readFile(new URL('app.js', root), 'utf8')
const workbenchHtml = await readFile(new URL('student-workbench.html', root), 'utf8')
const workbench = await readFile(new URL('workbench.js', root), 'utf8')

function renderPrototype(expression, ids = []) {
  const elements = new Map(ids.map(id => [`#${id}`, {
    innerHTML: '',
    textContent: '',
    addEventListener() {},
    insertAdjacentHTML(position, markup) { this.innerHTML += markup },
  }]))
  return runInNewContext(`${app}\n${expression}`, {
    document: {
      addEventListener() {},
      querySelector(selector) { return elements.get(selector) ?? null },
      querySelectorAll() { return [] },
    },
    localStorage: { getItem() { return null } },
    lucide: { createIcons() {} },
  })
}

test('three portal prototypes expose the planned workflow screens', () => {
  for (const screen of [
    'student-course-detail',
    'student-task-detail',
    'student-notifications',
    'teacher-enrollments',
    'teacher-publishing',
    'teacher-progress',
    'admin-resources',
    'admin-incidents',
  ]) {
    assert.match(index, new RegExp(`id=["']${screen}["']`))
  }
})

test('planned workflow handlers are wired in the prototype', () => {
  for (const handler of [
    'openStudentTaskDetail',
    'markStudentNotificationRead',
    'reviewTeacherEnrollment',
    'publishTeacherExperiment',
  ]) {
    assert.match(app, new RegExp(`function ${handler}\\b`))
  }
})

test('portal navigation names the expanded workflows', () => {
  for (const label of [
    '\\u901a\\u77e5',
    '\\u9009\\u8bfe\\u7ba1\\u7406',
    '\\u5b9e\\u9a8c\\u53d1\\u5e03',
    '\\u5b66\\u751f\\u8fc7\\u7a0b',
    '\\u8d44\\u6e90\\u6cbb\\u7406',
    '\\u5f02\\u5e38\\u4e2d\\u5fc3',
  ]) {
    assert.ok(app.includes(label), `missing navigation label escape: ${label}`)
  }
})

test('teacher navigation groups related workflows into compact menus', () => {
  const teacherNav = JSON.parse(renderPrototype("JSON.stringify(portalConfig.teacher.nav)"))
  assert.deepEqual(teacherNav.map(item => item.label ?? item[0]), ['教学概览', '课程与实验', '学生与评审', '教学分析'])
  assert.deepEqual(teacherNav[1].items.map(item => item[0]), ['我的课程', '选课管理', '实验设计', '实验发布'])
  assert.deepEqual(teacherNav[2].items.map(item => item[0]), ['学生过程', '评审中心'])
  assert.match(app, /nav-group-toggle/)
  assert.match(app, /function toggleNavGroup\b/)
})

test('expanded screens use the compact page-intro rule', () => {
  assert.doesNotMatch(app, /head\.closest\('#student-course-detail/)
  assert.match(app, /function stripPageIntros\(\)/)
  assert.match(app, /function go\(id\)\{[^}]*stripPageIntros\(\);/)
})

test('student workbench supports saved checkpoints, execution history, attachments, and report versions', () => {
  for (const marker of ['restoreCheckpoint', 'renderCheckpointList', 'renderExecutionHistory', 'saveReportVersion', 'handleReportAttachment', 'confirmReportSubmission']) {
    assert.match(workbench, new RegExp(`function ${marker}\\b`))
  }
  for (const action of ['open-executions', 'add-report-attachment']) {
    assert.ok(workbenchHtml.includes(`data-action="${action}"`), `missing workbench action: ${action}`)
  }
})

test('workbench keeps the report toolbar focused on editing and saving', () => {
  assert.doesNotMatch(workbenchHtml, /id="reportSubmissionStatus"/)
  assert.doesNotMatch(workbenchHtml, /data-action="open-review-result"/)
  assert.doesNotMatch(workbenchHtml, /data-action="open-report-versions"/)
  assert.match(workbenchHtml, /data-action="submit-chapter-report"/)
  assert.match(app, /报告记录/)
  assert.match(app, /报告版本/)
  assert.match(app, /评审意见/)
})

test('teacher review workflow supports rubric scoring, annotations, decisions, and student feedback sync', () => {
  for (const marker of ['openTeacherReview', 'saveTeacherReview', 'addTeacherReviewAnnotation', 'decideTeacherReview', 'syncStudentReviewResult']) {
    assert.match(app, new RegExp(`function ${marker}\\b`))
  }
  assert.ok(app.includes('id="teacherReview"'))
  assert.ok(app.includes('criterion-scores'))
  assert.ok(app.includes('operation-replay'))
})

test('each student task has one primary action and an accessible detail title', () => {
  for (const [taskId, action] of [
    ['task-linux-network', '进入工作台'],
    ['task-database-index', '查看详情'],
    ['task-container-network', '查看详情'],
  ]) {
    const markup = renderPrototype(`renderStudentTaskRow(studentCalendarTasks.find(task => task.id === '${taskId}'))`)
    assert.equal((markup.match(/<button\b/g) || []).length, 1)
    assert.match(markup, new RegExp(`>${action}</button>`))
    assert.match(markup, /<a\b[^>]*class="task-title task-title-link"/)
    assert.ok(markup.includes(`data-task-id="${taskId}"`))
    assert.match(markup, /openStudentTaskDetail\(this\.dataset\.taskId\)/)
    assert.doesNotMatch(markup, /任务详情（演示）/)
  }
  assert.doesNotMatch(app, /button\.className='btn sm detail-link'/)
})

test('student task detail exposes one workbench entry while retaining report records', () => {
  const markup = renderPrototype(
    "renderStudentTaskDetail(); document.querySelector('#student-task-detail').innerHTML",
    ['student-task-detail'],
  )
  assert.equal((markup.match(/onclick="openWorkbench\(\)"/g) || []).length, 1)
  assert.match(markup, /openStudentReportRecord\('versions'\)/)
  assert.match(markup, /openStudentReportRecord\('review'\)/)
})

test('student overview relies on primary navigation rather than a duplicate course button', () => {
  const markup = renderPrototype(
    "renderStudent(); document.querySelector('#student-home').innerHTML",
    ['student-home', 'student-courses', 'student-tasks', 'student-join-courses', 'studentJoinSearch', 'studentJoinMode', 'studentJoinResults', 'studentJoinResultCount'],
  )
  assert.doesNotMatch(markup, /<button\b[^>]*onclick="go\('student-courses'\)"/)
  assert.match(markup, /我的课程/)
})

test('joined courses and pending applications keep only their relevant action', () => {
  const markup = renderPrototype(
    "studentJoinTab='enrollments'; renderStudentJoinResults(); document.querySelector('#studentJoinResults').innerHTML",
    ['studentJoinResults', 'studentJoinResultCount'],
  )
  const cards = [...markup.matchAll(/<article\b[^>]*>[\s\S]*?<\/article>/g)]
  assert.equal(cards.length, 4)
  for (const [card] of cards) assert.equal((card.match(/<button\b/g) || []).length, 1)
  assert.match(markup, /查看课程/)
  assert.match(markup, /查看申请/)
})

test('available courses retain distinct course information and application actions', () => {
  const markup = renderPrototype(
    "renderStudentJoinResults(); document.querySelector('#studentJoinResults').innerHTML",
    ['studentJoinResults', 'studentJoinResultCount'],
  )
  const cards = [...markup.matchAll(/<article\b[^>]*>[\s\S]*?<\/article>/g)]
  assert.equal(cards.length, 2)
  for (const [card] of cards) {
    assert.match(card, /课程详情/)
    assert.match(card, /申请加入/)
  }
})

test('workbench report tab is the only report-switch control and distinct save actions remain', () => {
  assert.equal((workbenchHtml.match(/data-view="report"/g) || []).length, 1)
  assert.match(workbenchHtml, /id="reportTab"/)
  for (const action of ['submit-chapter-report', 'checkpoint', 'run-tests', 'open-submit']) {
    assert.equal(workbenchHtml.split(`data-action="${action}"`).length - 1, 1)
  }
})
