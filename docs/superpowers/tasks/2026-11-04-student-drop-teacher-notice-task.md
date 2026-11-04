# 学生退课通知老师 Tasks

1. 修改 courses/events.py、services.py 与 notifications/services.py，实现独立退课通知事件和可靠幂等投递（通知服务测试）。
2. 新增 notifications/tests/test_enrollment_notifications.py，验证真实退课、权限范围、快照、重复消费、回滚和其他结束状态。
3. 新增 teacher-web 通知页和测试，接入 App/guards，更新学生退出说明与断言（Vitest、两端类型检查、lint、构建）。
4. 执行课程、实验和通知 Django 测试；测试结束后同步本地 Django/Celery 服务，重启并检查健康；记录验收结果。
