# 学生有待办时退课 Tasks

1. 修改 courses/services.py、views.py：学生检查及提交允许未完成任务；测试学生允许、其他阻塞拒绝、教师规则不变（courses 服务/API 测试）。
2. 修改 experiments/selectors.py、services.py：退出后未完成任务不再进入当前任务列表，历史保留且无操作入口（真实任务 API/服务测试）。
3. 修改 enrollment-exit.tsx 及相关组件测试：明确说明允许带待办退课（Vitest）。
4. 执行相关 Django 测试、前端类型检查、lint、学生构建，记录结果（checklist）。
