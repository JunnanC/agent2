// Run through ego-browser with an already authorized task space.
export async function run({ taskSpaceId, taskId, baseURL }) {
  const task = await taskSpace(taskSpaceId);
  const page = task.page('p2');
  await page.goto(baseURL + '/experiments/' + taskId);
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(
    button => /^(开始任务|进入实验工作台)$/.test(button.textContent.trim()),
  ));
  const snapshot = await page.snapshot();
  const enter = snapshot.includes('进入实验工作台') ? '进入实验工作台' : '开始任务';
  await page.click('loc=role:button[name="' + enter + '"]');
  await page.waitForURL(baseURL + '/experiments/' + taskId + '/workbench', {
    timeout: 30_000,
  });
  await page.waitForFunction(() => !document.body.innerText.includes('正在打开工作台'));
  await page.waitForSelector('.monaco-workbench', { timeout: 30_000 });
  const before = await page.evaluate(async taskId => {
    const response = await fetch('/api/v2/tasks/' + taskId + '/workbench');
    if (!response.ok) throw new Error('Workbench unavailable');
    const { data } = await response.json();
    return {
      snapshot: data.workspace.last_synchronized_snapshot_id,
      language: data.workspace.language,
      execution: data.tests.recent_execution?.public_id ?? null,
    };
  }, taskId);
  await page.click('loc=role:button[name="运行测试"]');
  await page.waitForFunction(() => document.body.innerText.includes('全部通过'), undefined, {
    timeout: 60_000,
  });
  // Confirm server eligibility rather than relying only on a displayed prior result.
  await page.waitForFunction(async ({ taskId, previous }) => {
    const { data } = await (await fetch('/api/v2/tasks/' + taskId + '/workbench')).json();
    return data.tests.recent_execution?.public_id !== previous
      && data.submission.can_submit && data.tests.recent_execution?.status === 'PASSED'
      && [...document.querySelectorAll('button')].some(
        button => button.textContent.trim() === '完成实验' && !button.disabled,
      );
  }, { taskId, previous: before.execution }, { timeout: 60_000 });
  await page.click('loc=role:button[name="完成实验"]');
  await page.click('loc=role:button[name="确认完成"]');
  await page.waitForFunction(() => document.body.innerText.includes('等待教师评审'), undefined, {
    timeout: 30_000,
  });
  return { task_id: taskId, result: 'passed', before, submitted: true };
}
