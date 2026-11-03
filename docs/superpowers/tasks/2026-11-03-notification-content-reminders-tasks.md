# 通知正文与截止提醒 Tasks

1. 修改 student-web notifications.tsx 和测试：自动已读、已读不重复、失败重试和未读筛选保留详情；验证 Vitest。
2. 修改 experiments/services.py、notifications/services.py：生成实验通知完整正文，添加历史回填管理命令；验证真实发布集成测试与回填测试。
3. 修改 notifications/tasks.py、settings/base.py：实现有效截止时间扫描、幂等提醒与定时注册；验证状态、边界、延期与偏好测试。
4. 执行学生端类型检查和构建、Django相关测试；更新本地前后端容器并运行历史正文回填及一次提醒扫描；记录实际结果。

顺序：1 → 2 → 3 → 4。仅修改本轮所需文件，保留现有工作树改动。
