# 学生退课通知老师 Checklist

- [x] 退课即时生效、无需老师审批，产生可靠通知事件（真实待办退课 API、事件消费与教师通知接口测试）。
- [x] 仅课程负责人和有效选课管理老师收到，通知快照包含完整信息及选课管理链接（通知测试覆盖无权限、权限过期、成员撤销、其他课程老师和名称后续改变）。
- [x] 重复投递不重复通知；失败/事务回滚不产生退课通知；申请撤回和教师移除不产生该事件（服务/API 测试）。
- [x] 教师通知页可阅读正文、标记已读、访问选课管理，显示未读数（4 项页面交互测试通过）。
- [x] Django 相关测试、前端相关测试、类型检查、lint、学生/教师构建通过。
- [x] 本地 Django 和 Celery 同步本次代码并重启，manage.py check 与 /api/v2/health 通过。

## 验证记录
- 独立 SQLite Django 测试：notifications.tests、courses.test_services/test_api、experiments.test_api，共 49 项通过。
- Vitest：教师 notifications.test.tsx、学生 student-api-ui.test.tsx/courses.test.tsx，共 14 项通过。
- 学生和教师 TypeScript 检查、变更前端文件 ESLint、变更后端文件 Ruff 均通过。
- 学生与教师生产构建通过，git diff --check 通过。

通知沿用站内通知偏好。已有消费者每 30 秒投递一次，教师页面每 30 秒刷新；退课成功不等待投递或已读。未进行浏览器视觉验收或修改真实学生退课数据。
