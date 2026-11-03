import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useState } from 'react';
import { auditRows, governanceRows, imageRows, incidentRows, instanceRows, moduleRows, pages, profileRows } from './data';
import { Badge, DataTable, Metrics, Panel } from './components';
export function Overview({ navigate }) {
    const items = [
        { label: '活跃工作区', value: '128', foot: '124 正常 · 4 个需关注', onClick: () => navigate('resources') },
        { label: 'CPU 配额使用', value: '62%', foot: '总量 32 vCPU · 近 24 小时', onClick: () => navigate('resources') },
        { label: '内存配额使用', value: '71%', foot: '可用 42 GB · 近 24 小时', onClick: () => navigate('resources') },
        { label: '待处理事项', value: String(governanceRows.length).padStart(2, '0'), foot: '2 项高优先级 · 等待处理', onClick: () => navigate('governance') },
    ];
    const queue = [
        ['教师资格审核', '12 位申请人 · 最早 2 天前', '高', 'governance'],
        ['镜像扫描复核', '3 个镜像等待复核', '中', 'resources'],
        ['运行时容量告警', '集群 B · CPU 余量偏低', '高', 'resources'],
        ['实验任务异常', '2 项等待分派', '低', 'incidents'],
    ];
    return _jsxs(_Fragment, { children: [_jsx(Metrics, { items: items }), _jsxs("div", { className: "columns section", children: [_jsx(Panel, { title: "\u8D44\u6E90\u4F7F\u7528\u8D8B\u52BF", extra: _jsxs("div", { className: "legend", children: [_jsxs("span", { children: [_jsx("i", {}), "CPU"] }), _jsxs("span", { children: [_jsx("i", { className: "blue" }), "\u5185\u5B58"] })] }), children: _jsx("div", { className: "panel-body", children: _jsxs("div", { className: "trend", role: "img", "aria-label": "\u6F14\u793A\u8D8B\u52BF\uFF1ACPU \u4F7F\u7528\u7387\u7EA6\u4E3A 30% \u81F3 66%\uFF0C\u5185\u5B58\u4F7F\u7528\u7387\u7EA6\u4E3A 42% \u81F3 71%", children: [_jsxs("div", { className: "chart-grid", children: [_jsx("span", {}), _jsx("span", {}), _jsx("span", {}), _jsx("span", {})] }), [[30, 44], [35, 42], [41, 47], [38, 49], [48, 53], [55, 52], [51, 57], [62, 59], [58, 63], [66, 68], [62, 71], [59, 65]].map(([cpu, memory], index) => _jsxs("span", { className: "bar-group", title: `${index * 2}:00 CPU ${cpu}% / 内存 ${memory}%`, children: [_jsx("i", { className: "bar", style: { height: `${cpu}%` } }), _jsx("i", { className: "bar secondary", style: { height: `${memory}%` } }), _jsx("em", { children: index % 3 === 0 ? String(index * 2).padStart(2, '0') : '' })] }, index))] }) }) }), _jsx(Panel, { title: "\u5F85\u5904\u7406\u6CBB\u7406\u4E8B\u9879", extra: _jsx("button", { className: "row-action", onClick: () => navigate('governance'), children: "\u67E5\u770B\u5168\u90E8 \u2192" }), children: _jsx("div", { className: "panel-body queue", children: queue.map(([title, meta, priority, page]) => _jsxs("div", { className: "queue-row", children: [_jsxs("div", { children: [_jsx("div", { className: "queue-title", children: title }), _jsx("div", { className: "queue-meta", children: meta })] }), _jsx("button", { className: "row-action", onClick: () => navigate(page), "aria-label": `查看${title}`, children: _jsx(Badge, { value: priority }) })] }, title)) }) })] }), _jsxs("section", { className: "section", children: [_jsxs("div", { className: "section-title", children: [_jsx("h2", { children: "\u5E73\u53F0\u670D\u52A1\u5065\u5EB7" }), _jsx("small", { children: "\u6700\u540E\u66F4\u65B0 14:32 \u00B7 \u6570\u636E\u4E3A\u754C\u9762\u6F14\u793A" })] }), _jsx("div", { className: "health-list", children: [['API 服务', '响应正常 · p95 142 ms'], ['数据存储', '连接池运行正常'], ['运行时集群 B', '容量偏低 · 建议检查配额']].map(([title, description], index) => _jsxs("div", { className: "health", children: [_jsxs("div", { className: "health-top", children: [_jsx("i", { className: `health-dot ${index === 2 ? 'warn' : ''}` }), title] }), _jsx("p", { children: description })] }, title)) })] })] });
}
export function Governance({ onDetail }) {
    return _jsxs(_Fragment, { children: [_jsx(Metrics, { items: [
                    { label: '待处理事项', value: String(governanceRows.length).padStart(2, '0'), foot: '4 类治理队列' },
                    { label: '高优先级', value: '02', foot: '需要尽快响应' },
                    { label: '平均等待', value: '6.4h', foot: '按待处理事项计算' },
                    { label: '今日已完成', value: '14', foot: '较昨日 +3' },
                ] }), _jsx("div", { className: "section", children: _jsx(DataTable, { headers: ['事项', '治理范围', '优先级', '等待时间', '负责人'], rows: governanceRows, statuses: ['高', '中', '低'], badgeColumns: [2], onDetail: onDetail }) })] });
}
export function Resources({ onDetail }) {
    const [tab, setTab] = useState('runtime');
    const tabs = [['runtime', '运行时与配额'], ['images', '镜像治理'], ['instances', '实例与会话']];
    return _jsxs(_Fragment, { children: [_jsx(Metrics, { items: [
                    { label: '运行中实例', value: '62', foot: '当前占用 71%' },
                    { label: '已治理镜像', value: '18', foot: '扫描状态已通过' },
                    { label: '配额预警', value: '04', foot: '2 项高风险' },
                    { label: '活跃工作区会话', value: '84', foot: '最近 24 小时' },
                ] }), _jsxs("section", { className: "section", children: [_jsx("div", { className: "tabs", role: "tablist", "aria-label": "\u8D44\u6E90\u5206\u7C7B", children: tabs.map(([key, title], index) => _jsx("button", { id: `tab-${key}`, role: "tab", "aria-selected": tab === key, "aria-controls": "resource-panel", tabIndex: tab === key ? 0 : -1, className: tab === key ? 'active' : '', onClick: () => setTab(key ?? ''), onKeyDown: event => {
                                if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key))
                                    return;
                                event.preventDefault();
                                const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
                                const nextTab = tabs[next];
                                if (!nextTab)
                                    return;
                                setTab(nextTab[0] ?? '');
                                document.getElementById(`tab-${nextTab[0]}`)?.focus();
                            }, children: title }, key ?? index)) }), _jsx("div", { id: "resource-panel", role: "tabpanel", "aria-labelledby": `tab-${tab}`, children: tab === 'runtime' ? _jsxs(_Fragment, { children: [_jsxs("div", { className: "columns", children: [_jsx(Panel, { title: "\u8FD0\u884C\u65F6\u5065\u5EB7", extra: _jsx("span", { className: "pill green", children: "2 \u6B63\u5E38 \u00B7 1 \u9700\u5173\u6CE8" }), children: _jsx("div", { className: "panel-body", children: [['Docker Sandbox · v3', '健康率 99.8%', '健康'], ['Notebook Runtime · v2', '健康率 99.4%', '健康'], ['Judge Worker · v1', '队列占用 72%', '需关注']].map(([title, meta, status]) => _jsxs("div", { className: "resource-row", children: [_jsxs("div", { children: [_jsx("div", { className: "queue-title", children: title }), _jsx("div", { className: "queue-meta", children: meta })] }), _jsx(Badge, { value: status ?? '' })] }, title ?? '')) }) }), _jsx(Panel, { title: "\u914D\u989D\u4F7F\u7528", extra: _jsx("span", { className: "muted", children: "\u672C\u5B66\u671F" }), children: _jsx("div", { className: "panel-body", children: [['CPU', 71], ['内存', 58], ['对象存储', 43]].map(([label, value]) => _jsxs("div", { className: "progress-row", children: [_jsx("span", { children: label }), _jsx("div", { className: `track ${Number(value) > 70 ? 'amber' : ''}`, children: _jsx("span", { style: { width: `${value}%` } }) }), _jsxs("strong", { children: [value, "%"] })] }, label)) }) })] }), _jsxs("section", { className: "section", children: [_jsxs("div", { className: "section-title", children: [_jsx("h2", { children: "\u8D44\u6E90\u89C4\u683C" }), _jsx("small", { children: "\u72B6\u6001\u53CA\u64CD\u4F5C\u7531\u670D\u52A1\u7AEF\u6743\u9650\u51B3\u5B9A" })] }), _jsx(DataTable, { headers: ['规格', 'CPU', '内存', '当前使用', '状态'], rows: profileRows, badgeColumns: [4], onDetail: onDetail })] })] }) : tab === 'images' ? _jsx(DataTable, { headers: ['镜像', '版本 / Digest', '扫描状态', '治理状态', '最近检查'], rows: imageRows, badgeColumns: [2, 3], onDetail: onDetail }, "images") : _jsx(DataTable, { headers: ['实例', '关联任务', '运行状态', '资源规格', '最近活动'], rows: instanceRows, badgeColumns: [2], onDetail: onDetail }, "instances") })] })] });
}
export function Incidents({ onDetail }) {
    return _jsxs(_Fragment, { children: [_jsx(Metrics, { items: [
                    { label: '待处理异常', value: '07', foot: '跨任务与资源' },
                    { label: '高优先级', value: '02', foot: '建议立即排查' },
                    { label: '待运行补偿', value: '03', foot: '操作前需复核影响' },
                    { label: '今日已解决', value: '14', foot: '近 24 小时' },
                ] }), _jsx("div", { className: "section", children: _jsx(DataTable, { headers: ['异常类型', '关联对象', '优先级', '发生时间', '状态', 'Trace ID'], rows: incidentRows, statuses: ['待处理', '处理中', '待复核'], badgeColumns: [2, 4], timeFilter: true, onDetail: onDetail }) }), _jsx(Panel, { title: "\u8865\u507F\u4EFB\u52A1", extra: _jsx("span", { className: "pill amber", children: "3 \u4E2A\u5F85\u590D\u6838" }), className: "section", children: _jsxs("div", { className: "panel-body split", children: [_jsxs("div", { children: [_jsx("div", { className: "queue-title", children: "\u5B9E\u4F8B\u56DE\u6536\u5931\u8D25" }), _jsx("div", { className: "queue-meta", children: "\u8D44\u6E90\u56DE\u6536 \u00B7 comp_01M8F2 \u00B7 \u6700\u8FD1\u91CD\u8BD5 10:26" })] }), _jsxs("div", { children: [_jsx("div", { className: "queue-title", children: "\u62A5\u544A\u626B\u63CF\u8D85\u65F6" }), _jsx("div", { className: "queue-meta", children: "\u6587\u4EF6\u626B\u63CF \u00B7 comp_01M8D9 \u00B7 \u7B49\u5F85\u4EBA\u5DE5\u590D\u6838" })] })] }) })] });
}
export function Audit({ onDetail }) {
    return _jsxs(_Fragment, { children: [_jsx(DataTable, { headers: ['时间', '操作者', '动作', '对象', '结果', 'Trace ID'], rows: auditRows, statuses: ['成功', '需复核', '失败'], badgeColumns: [4], timeFilter: true, exportable: true, onDetail: onDetail }), _jsxs("div", { className: "section-title section", children: [_jsx("h2", { children: "\u5BA1\u8BA1\u67E5\u8BE2\u8BF4\u660E" }), _jsx("small", { children: "\u6F14\u793A\u8BB0\u5F55\u7684\u65E5\u671F\u57FA\u51C6\u4E3A 2026-10-15" })] }), _jsx("div", { className: "health-list", children: [['操作范围', '筛选管理员、资源对象、操作结果和时间范围。'], ['Trace 关联', '通过 Trace ID 关联请求与必要的运行记录。'], ['数据保护', '不在界面或日志中展示密钥、Cookie 和完整文件内容。']].map(([title, description]) => _jsxs("div", { className: "health", children: [_jsx("div", { className: "health-top", children: title }), _jsx("p", { children: description })] }, title)) })] });
}
const moduleTable = {
    users: { headers: ['用户', '账号', '角色', '状态', '最近活动'], badgeColumns: [3], statuses: ['正常', '待审核'] },
    teachers: { headers: ['申请人', '申请类型', '状态', '材料', '提交时间'], badgeColumns: [2], statuses: ['待审核', '已通过'] },
    admins: { headers: ['管理员', '职责范围', '状态', '有效期', '最近操作'], badgeColumns: [2], statuses: ['有效', '即将到期'] },
    verifications: { headers: ['对象', '身份类型', '状态', '风险', '提交时间'], badgeColumns: [2, 3], statuses: ['待审核', '已通过'] },
    courses: { headers: ['课程', '负责人', '状态', '实验数', '最近更新'], badgeColumns: [2], statuses: ['已发布', '待复核'] },
    experimentAnomalies: { headers: ['异常类型', '关联对象', '优先级', '发生时间', '状态', 'Trace ID'], badgeColumns: [2, 4], statuses: ['待处理', '处理中', '待复核'] },
    workspaceSessions: { headers: ['会话', '任务 / 学生', '状态', '过期时间', '版本'], badgeColumns: [2], statuses: ['运行中', '已过期'] },
    instances: { headers: ['实例', '关联任务', '运行状态', '资源规格', '最近活动'], badgeColumns: [2], statuses: ['运行中', '空闲', '回收失败'] },
    compensations: { headers: ['补偿任务', '关联对象', '状态', '重试次数', 'Trace ID'], badgeColumns: [2], statuses: ['待重试', '待复核'] },
    runtimes: { headers: ['运行时', '类型 / 驱动', '状态', '健康率', '容量'], badgeColumns: [2], statuses: ['启用', '需关注'] },
    images: { headers: ['镜像', '版本 / Digest', '扫描状态', '治理状态', '最近检查'], badgeColumns: [2, 3], statuses: ['已批准', '待审核', '已阻止'] },
    resourceProfiles: { headers: ['规格', 'CPU', '内存', '当前使用', '状态'], badgeColumns: [4], statuses: ['启用'] },
    quotas: { headers: ['范围', '实例上限', 'CPU', '内存', '版本'], badgeColumns: [], statuses: [] },
    security: { headers: ['策略', '范围', '规则', '风险', '状态'], badgeColumns: [4], statuses: ['已启用'] },
    templatePrechecks: { headers: ['状态', '数量', '模板版本', 'Trace ID'], badgeColumns: [0], statuses: ['PASSED', 'FAILED'] },
    reportScanAnomalies: { headers: ['资产', '任务', '扫描状态', '错误代码', '时间'], badgeColumns: [2], statuses: ['TIMEOUT', 'PASSED'] },
    reviewMonitor: { headers: ['审核状态', '数量', '自动检查', '相似度异常'], badgeColumns: [0], statuses: ['PENDING', 'DECIDED'] },
    agentPolicies: { headers: ['工具', '风险', '策略状态', '超时 / 输出', '版本'], badgeColumns: [1, 2], statuses: ['允许', '需审批'] },
    operations: { headers: ['运维指标', '数量', '状态', '更新时间', '来源'], badgeColumns: [2], statuses: ['健康', '需关注'] },
};
export function ModulePage({ page, onDetail }) {
    const config = moduleTable[page] ?? { headers: ['对象', '状态'], badgeColumns: [1], statuses: [] };
    const rows = moduleRows[page] ?? [];
    const attention = rows.filter((row) => !['正常', '已通过', '已发布', '有效', '运行中', '启用', '已批准', 'PASSED', '健康', '允许'].includes(row.status)).length;
    return _jsxs(_Fragment, { children: [_jsx(Metrics, { items: [{ label: '记录总数', value: String(rows.length).padStart(2, '0'), foot: '演示数据快照' }, { label: '需关注', value: String(attention).padStart(2, '0'), foot: '按当前状态统计' }, { label: '今日更新', value: String(rows.filter((row) => row.date === '2026-10-15').length).padStart(2, '0'), foot: '最近活动记录' }, { label: '治理域', value: pages[page]?.eyebrow.split(' ')[0] ?? '平台', foot: '平台管理范围' }] }), _jsx("div", { className: "section", children: _jsx(DataTable, { headers: config.headers, rows: rows, statuses: config.statuses, badgeColumns: config.badgeColumns, timeFilter: true, exportable: true, onDetail: onDetail }) })] });
}
