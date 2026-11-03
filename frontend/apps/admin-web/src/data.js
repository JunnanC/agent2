// 界面演示数据；完成后端联调时，用服务端响应替换此模块的数据源。
export const pages = {
    overview: { title: '平台概览', eyebrow: '平台运行', description: '汇总平台运行状态与待处理治理事项，快速定位需要处理的风险。' },
    governance: { title: '治理待办', eyebrow: '平台治理', description: '按风险和时效处理教师资格、资源治理与安全事项。' },
    resources: { title: '运行资源', eyebrow: '资源治理', description: '查看镜像治理、运行时健康、资源配额与实例状态。' },
    incidents: { title: '异常中心', eyebrow: '运行保障', description: '集中定位任务、扫描、预检与运行异常，并追踪补偿任务状态。' },
    audit: { title: '操作审计', eyebrow: '安全与审计', description: '检索关键平台操作，核对操作者、变更对象、执行结果和关联 Trace。' },
    users: { title: '用户账号', eyebrow: '账号与教学', description: '查看平台用户状态、角色和最近活动，支持账号治理。' },
    teachers: { title: '教师资格', eyebrow: '账号与教学', description: '审核教师资格申请和资格状态，保留审核依据。' },
    admins: { title: '管理员资格', eyebrow: '账号与教学', description: '管理平台管理员授权、版本和撤销记录。' },
    verifications: { title: '身份审核', eyebrow: '账号与教学', description: '集中处理身份材料审核与风险状态。' },
    courses: { title: '课程监管', eyebrow: '账号与教学', description: '查看课程发布状态、实验数量和课程治理风险。' },
    experimentAnomalies: { title: '实验异常', eyebrow: '实验运行', description: '定位失败任务、发布失败、对账异常和终止状态异常。' },
    workspaceSessions: { title: '工作区会话', eyebrow: '实验运行', description: '查看工作区会话状态、过期时间、撤销和版本摘要。' },
    instances: { title: '实例回收', eyebrow: '实验运行', description: '检查运行实例、孤儿资源和回收状态。' },
    compensations: { title: '补偿任务', eyebrow: '实验运行', description: '追踪归档、回收和失败重试补偿任务。' },
    runtimes: { title: '运行时', eyebrow: '资源治理', description: '维护运行时目录、驱动和健康快照。' },
    images: { title: '镜像', eyebrow: '资源治理', description: '管理镜像 digest、扫描状态和批准状态。' },
    resourceProfiles: { title: '资源规格', eyebrow: '资源治理', description: '查看 CPU、内存、磁盘和网络模式等资源规格。' },
    quotas: { title: '配额', eyebrow: '资源治理', description: '查看平台、课程和用户三级资源配额。' },
    security: { title: '安全策略', eyebrow: '资源治理', description: '查看默认拒绝策略、网络白名单、扩缩容和告警。' },
    templatePrechecks: { title: '模板预检', eyebrow: '质量与智能', description: '查看模板预检通过率、失败阶段和相关 Trace。' },
    reportScanAnomalies: { title: '报告扫描异常', eyebrow: '质量与智能', description: '查看报告附件扫描状态、失败原因和关联任务。' },
    reviewMonitor: { title: '审核监控', eyebrow: '质量与智能', description: '查看审核队列、自动检查失败和相似度运行。' },
    agentPolicies: { title: 'Agent 策略', eyebrow: '质量与智能', description: '管理工具策略、模型路由、评测套件和调用成本。' },
    operations: { title: '运维分析与集成', eyebrow: '运维与集成', description: '查看运行时库存、投影新鲜度、通知和外部集成。' },
};
export const governanceRows = [
    { id: 'gov_01', cells: ['教师资格审核', '用户与资格', '高', '2 天 4 小时', '未分配'], status: '高', date: '2026-10-13' },
    { id: 'gov_02', cells: ['运行时容量告警', '运行时与实例', '高', '5 小时', '管理员 A'], status: '高', date: '2026-10-15' },
    { id: 'gov_03', cells: ['镜像扫描异常', '镜像治理', '中', '19 小时', '管理员 B'], status: '中', date: '2026-10-14' },
    { id: 'gov_04', cells: ['异常实验任务', '安全与审计', '中', '8 小时', '未分配'], status: '中', date: '2026-10-15' },
    { id: 'gov_05', cells: ['模板预检失败', '模板治理', '低', '1 天', '管理员 A'], status: '低', date: '2026-10-14' },
    { id: 'gov_06', cells: ['课程状态复核', '课程治理', '低', '2 天', '管理员 C'], status: '低', date: '2026-10-13' },
];
export const incidentRows = [
    { id: 'incident_01', cells: ['实验任务异常', 'task_01M8F2', '中', '今天 10:02', '待处理', 'tr_7fd2a190'], status: '待处理', date: '2026-10-15' },
    { id: 'incident_02', cells: ['报告扫描超时', 'asset_01M8C7', '低', '今天 09:14', '处理中', 'tr_1ac93e71'], status: '处理中', date: '2026-10-15' },
    { id: 'incident_03', cells: ['模板预检失败', 'template_01M7D1', '中', '昨天 18:40', '待复核', 'tr_37be24c0'], status: '待复核', date: '2026-10-14' },
];
export const auditRows = [
    { id: 'audit_01', cells: ['今天 14:32', '管理员 A', '更新运行时资源配置', '集群 B', '成功', 'tr_2de891a4'], status: '成功', date: '2026-10-15' },
    { id: 'audit_02', cells: ['今天 13:55', '周老师', '发布模板版本 v1.3', 'Linux 网络故障排查', '成功', 'tr_79b382cd'], status: '成功', date: '2026-10-15' },
    { id: 'audit_03', cells: ['今天 12:18', '系统', '停止异常实验实例', 'task_01M8F2', '需复核', 'tr_37be24c0'], status: '需复核', date: '2026-10-15' },
    { id: 'audit_04', cells: ['昨天 19:44', '管理员 B', '撤回镜像批准状态', 'Ubuntu Network Lab v2.2', '成功', 'tr_e491f12b'], status: '成功', date: '2026-10-14' },
];
export const imageRows = [
    { id: 'image_01', cells: ['Ubuntu Network Lab', 'v2.4 · sha256:8f2c…b91', '扫描通过', '已批准', '今天 14:22'], status: '已批准', date: '2026-10-15' },
    { id: 'image_02', cells: ['Python Data Science', 'v1.8 · sha256:51ad…90e', '等待复核', '待审核', '今天 11:05'], status: '待审核', date: '2026-10-15' },
    { id: 'image_03', cells: ['Docker Sandbox', 'v3 · sha256:11ce…82a', '扫描失败', '已阻止', '昨天 16:38'], status: '已阻止', date: '2026-10-14' },
];
export const instanceRows = [
    { id: 'ws_01M8F2', cells: ['ws_01M8F2', 'task_01M8F2', '运行中', 'medium · 2 vCPU', '今天 14:32'], status: '运行中', date: '2026-10-15' },
    { id: 'ws_01M7C9', cells: ['ws_01M7C9', 'task_01M7C9', '空闲', 'small · 1 vCPU', '今天 13:54'], status: '空闲', date: '2026-10-15' },
    { id: 'ws_01M6B4', cells: ['ws_01M6B4', 'task_01M6B4', '回收失败', 'large · 4 vCPU', '昨天 22:18'], status: '回收失败', date: '2026-10-14' },
];
export const profileRows = [
    { id: 'profile_small', cells: ['small', '1 vCPU', '2 GB', '34 / 60', '启用'], status: '启用', date: '2026-10-15' },
    { id: 'profile_medium', cells: ['medium', '2 vCPU', '4 GB', '22 / 40', '启用'], status: '启用', date: '2026-10-15' },
];
export const moduleRows = {
    users: [{ id: 'user_01', cells: ['林同学', 'student@example.edu', '学生', '正常', '今天 14:22'], status: '正常', date: '2026-10-15' }, { id: 'user_02', cells: ['周老师', 'teacher@example.edu', '教师', '待审核', '今天 11:05'], status: '待审核', date: '2026-10-15' }],
    teachers: [{ id: 'teacher_01', cells: ['周老师', '教师资格申请', '待审核', '材料 4 项', '今天 11:05'], status: '待审核', date: '2026-10-15' }, { id: 'teacher_02', cells: ['陈老师', '教师资格续期', '已通过', '材料 3 项', '昨天 16:38'], status: '已通过', date: '2026-10-14' }],
    admins: [{ id: 'admin_01', cells: ['管理员 A', '平台运维与治理', '有效', '2026-12-31', '今天 14:32'], status: '有效', date: '2026-10-15' }, { id: 'admin_02', cells: ['管理员 B', '审核监管', '即将到期', '2026-11-08', '昨天 19:44'], status: '即将到期', date: '2026-10-14' }],
    verifications: [{ id: 'verify_01', cells: ['周老师', '教师身份', '待审核', '高', '今天 11:05'], status: '待审核', date: '2026-10-15' }, { id: 'verify_02', cells: ['林同学', '学生身份', '已通过', '低', '昨天 15:20'], status: '已通过', date: '2026-10-14' }],
    courses: [{ id: 'course_01', cells: ['Linux 网络故障排查', '周老师', '已发布', '12 个实验', '今天 13:55'], status: '已发布', date: '2026-10-15' }, { id: 'course_02', cells: ['Python 数据分析', '陈老师', '待复核', '8 个实验', '昨天 16:10'], status: '待复核', date: '2026-10-14' }],
    experimentAnomalies: incidentRows,
    workspaceSessions: [{ id: 'session_01', cells: ['ws_01M8F2', 'task_01M8F2 / 林同学', '运行中', '今天 16:30', 'v3'], status: '运行中', date: '2026-10-15' }, { id: 'session_02', cells: ['ws_01M7C9', 'task_01M7C9 / 陈同学', '已过期', '今天 12:10', 'v2'], status: '已过期', date: '2026-10-15' }],
    instances: instanceRows,
    compensations: [{ id: 'comp_01', cells: ['实例回收失败', 'ws_01M6B4', '待重试', '2 / 5', 'tr_37be24c0'], status: '待重试', date: '2026-10-15' }, { id: 'comp_02', cells: ['报告扫描超时', 'asset_01M8C7', '待复核', '1 / 3', 'tr_1ac93e71'], status: '待复核', date: '2026-10-15' }],
    runtimes: [{ id: 'runtime_01', cells: ['Docker Sandbox', 'CONTAINER / DOCKER_SWARM', '启用', '99.8%', '32 / 48 vCPU'], status: '启用', date: '2026-10-15' }, { id: 'runtime_02', cells: ['Judge Worker', 'CONTAINER / LOCAL', '需关注', '97.1%', '18 / 24 vCPU'], status: '需关注', date: '2026-10-15' }],
    images: imageRows,
    resourceProfiles: profileRows,
    quotas: [{ id: 'quota_01', cells: ['平台', '60 并发实例', '32 vCPU', '128 GB', 'v4'], status: '启用', date: '2026-10-15' }, { id: 'quota_02', cells: ['课程 / Linux 网络', '20 并发实例', '8 vCPU', '32 GB', 'v2'], status: '启用', date: '2026-10-15' }],
    security: [{ id: 'policy_01', cells: ['默认出网策略', '平台', 'DENY_ALL', '高', '已启用'], status: '已启用', date: '2026-10-15' }, { id: 'policy_02', cells: ['资源扩缩容', '平台', '预算 10000', '中', '已启用'], status: '已启用', date: '2026-10-15' }],
    templatePrechecks: [{ id: 'precheck_01', cells: ['PASSED', '42', '模板版本 v1.3', 'tr_79b382cd'], status: 'PASSED', date: '2026-10-15' }, { id: 'precheck_02', cells: ['FAILED', '3', '模板版本 v1.2', 'tr_37be24c0'], status: 'FAILED', date: '2026-10-15' }],
    reportScanAnomalies: [{ id: 'scan_01', cells: ['asset_01M8C7', 'task_01M8F2', 'TIMEOUT', 'SCAN_TIMEOUT', '今天 09:14'], status: 'TIMEOUT', date: '2026-10-15' }, { id: 'scan_02', cells: ['asset_01M7D1', 'task_01M7C9', 'PASSED', '-', '昨天 18:40'], status: 'PASSED', date: '2026-10-14' }],
    reviewMonitor: [{ id: 'review_01', cells: ['PENDING', '12', '自动检查通过', '0'], status: 'PENDING', date: '2026-10-15' }, { id: 'review_02', cells: ['DECIDED', '38', '自动检查失败', '2'], status: 'DECIDED', date: '2026-10-15' }],
    agentPolicies: [{ id: 'agent_01', cells: ['workspace.inspect', 'LOW', '允许', '30s / 8192', 'v3'], status: '允许', date: '2026-10-15' }, { id: 'agent_02', cells: ['runtime.exec', 'HIGH', '需审批', '5s / 4096', 'v2'], status: '需审批', date: '2026-10-15' }],
    operations: [{ id: 'op_01', cells: ['运行时库存', '48', '健康', '今天 14:32', 'runtime/local'], status: '健康', date: '2026-10-15' }, { id: 'op_02', cells: ['Webhook 投递', '3', '需关注', '今天 13:55', 'integrations/webhook'], status: '需关注', date: '2026-10-15' }],
};
export const demoToday = '2026-10-15';
export function filterRows(rows, query, status = 'all', days = 0) {
    const term = query.trim().toLocaleLowerCase();
    const cutoff = Date.parse(`${demoToday}T00:00:00Z`) - (days - 1) * 86400000;
    return rows.filter(row => [...row.cells, row.id].join(' ').toLocaleLowerCase().includes(term)
        && (status === 'all' || row.status === status)
        && (!days || Date.parse(`${row.date}T00:00:00Z`) >= cutoff));
}
export function toCsv(headers, rows) {
    // 防止导出的文本在表格软件中被当作公式执行。
    const cell = (value) => `"${(/^[=+@\-\t\r]/.test(value) ? `'${value}` : value).replaceAll('"', '""')}"`;
    return '\ufeff' + [headers, ...rows].map(row => row.map(cell).join(',')).join('\r\n');
}
