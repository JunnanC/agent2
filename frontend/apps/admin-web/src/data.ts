// 界面演示数据；完成后端联调时，用服务端响应替换此模块的数据源。
export const pages = {
  overview: { title: '平台概览', eyebrow: '平台运行', description: '汇总平台运行状态与待处理治理事项，快速定位需要处理的风险。' },
  governance: { title: '治理待办', eyebrow: '平台治理', description: '按风险和时效处理教师资格、资源治理与安全事项。' },
  resources: { title: '运行资源', eyebrow: '资源治理', description: '查看镜像治理、运行时健康、资源配额与实例状态。' },
  incidents: { title: '异常中心', eyebrow: '运行保障', description: '集中定位任务、扫描、预检与运行异常，并追踪补偿任务状态。' },
  audit: { title: '操作审计', eyebrow: '安全与审计', description: '检索关键平台操作，核对操作者、变更对象、执行结果和关联 Trace。' },
} as const;
export type Page = keyof typeof pages;
export type RecordRow = { id: string; cells: string[]; status: string; date: string };

export const governanceRows: RecordRow[] = [
  { id: 'gov_01', cells: ['教师资格审核', '用户与资格', '高', '2 天 4 小时', '未分配'], status: '高', date: '2026-10-13' },
  { id: 'gov_02', cells: ['运行时容量告警', '运行时与实例', '高', '5 小时', '管理员 A'], status: '高', date: '2026-10-15' },
  { id: 'gov_03', cells: ['镜像扫描异常', '镜像治理', '中', '19 小时', '管理员 B'], status: '中', date: '2026-10-14' },
  { id: 'gov_04', cells: ['异常实验任务', '安全与审计', '中', '8 小时', '未分配'], status: '中', date: '2026-10-15' },
  { id: 'gov_05', cells: ['模板预检失败', '模板治理', '低', '1 天', '管理员 A'], status: '低', date: '2026-10-14' },
  { id: 'gov_06', cells: ['课程状态复核', '课程治理', '低', '2 天', '管理员 C'], status: '低', date: '2026-10-13' },
];
export const incidentRows: RecordRow[] = [
  { id: 'incident_01', cells: ['实验任务异常', 'task_01M8F2', '中', '今天 10:02', '待处理', 'tr_7fd2a190'], status: '待处理', date: '2026-10-15' },
  { id: 'incident_02', cells: ['报告扫描超时', 'asset_01M8C7', '低', '今天 09:14', '处理中', 'tr_1ac93e71'], status: '处理中', date: '2026-10-15' },
  { id: 'incident_03', cells: ['模板预检失败', 'template_01M7D1', '中', '昨天 18:40', '待复核', 'tr_37be24c0'], status: '待复核', date: '2026-10-14' },
];
export const auditRows: RecordRow[] = [
  { id: 'audit_01', cells: ['今天 14:32', '管理员 A', '更新运行时资源配置', '集群 B', '成功', 'tr_2de891a4'], status: '成功', date: '2026-10-15' },
  { id: 'audit_02', cells: ['今天 13:55', '周老师', '发布模板版本 v1.3', 'Linux 网络故障排查', '成功', 'tr_79b382cd'], status: '成功', date: '2026-10-15' },
  { id: 'audit_03', cells: ['今天 12:18', '系统', '停止异常实验实例', 'task_01M8F2', '需复核', 'tr_37be24c0'], status: '需复核', date: '2026-10-15' },
  { id: 'audit_04', cells: ['昨天 19:44', '管理员 B', '撤回镜像批准状态', 'Ubuntu Network Lab v2.2', '成功', 'tr_e491f12b'], status: '成功', date: '2026-10-14' },
];
export const imageRows: RecordRow[] = [
  { id: 'image_01', cells: ['Ubuntu Network Lab', 'v2.4 · sha256:8f2c…b91', '扫描通过', '已批准', '今天 14:22'], status: '已批准', date: '2026-10-15' },
  { id: 'image_02', cells: ['Python Data Science', 'v1.8 · sha256:51ad…90e', '等待复核', '待审核', '今天 11:05'], status: '待审核', date: '2026-10-15' },
  { id: 'image_03', cells: ['Docker Sandbox', 'v3 · sha256:11ce…82a', '扫描失败', '已阻止', '昨天 16:38'], status: '已阻止', date: '2026-10-14' },
];
export const instanceRows: RecordRow[] = [
  { id: 'ws_01M8F2', cells: ['ws_01M8F2', 'task_01M8F2', '运行中', 'medium · 2 vCPU', '今天 14:32'], status: '运行中', date: '2026-10-15' },
  { id: 'ws_01M7C9', cells: ['ws_01M7C9', 'task_01M7C9', '空闲', 'small · 1 vCPU', '今天 13:54'], status: '空闲', date: '2026-10-15' },
  { id: 'ws_01M6B4', cells: ['ws_01M6B4', 'task_01M6B4', '回收失败', 'large · 4 vCPU', '昨天 22:18'], status: '回收失败', date: '2026-10-14' },
];
export const profileRows: RecordRow[] = [
  { id: 'profile_small', cells: ['small', '1 vCPU', '2 GB', '34 / 60', '启用'], status: '启用', date: '2026-10-15' },
  { id: 'profile_medium', cells: ['medium', '2 vCPU', '4 GB', '22 / 40', '启用'], status: '启用', date: '2026-10-15' },
];
export const demoToday = '2026-10-15';

export function filterRows(rows: RecordRow[], query: string, status = 'all', days = 0) {
  const term = query.trim().toLocaleLowerCase();
  const cutoff = Date.parse(`${demoToday}T00:00:00Z`) - (days - 1) * 86400000;
  return rows.filter(row =>
    [...row.cells, row.id].join(' ').toLocaleLowerCase().includes(term)
    && (status === 'all' || row.status === status)
    && (!days || Date.parse(`${row.date}T00:00:00Z`) >= cutoff),
  );
}

export function toCsv(headers: string[], rows: string[][]) {
  // 防止导出的文本在表格软件中被当作公式执行。
  const cell = (value: string) => `"${(/^[=+@\-\t\r]/.test(value) ? `'${value}` : value).replaceAll('"', '""')}"`;
  return '\ufeff' + [headers, ...rows].map(row => row.map(cell).join(',')).join('\r\n');
}
