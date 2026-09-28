# P13-A analytics 与 notifications 出口记录

阶段：P13-A 本地分析投影与通知

日期：2026-09-24

## 范围与边界

- 新增五类 MySQL 分析投影与通知/偏好模型，投影保存 `projection_version`、`source_cursor`、`calculated_at`，重建只读取业务事实，不把 MongoDB 当分析事实源。
- Outbox 通知使用独立 `consumer:notifications` destination 并以事件唯一键幂等创建；通知按 portal 与 account 裁剪，已读和偏好使用 CAS。
- user-web、teacher-web、admin-web 增加通知中心和偏好入口；建议与风险只提供解释和人工处置，不自动修改任务或课程状态。

## 本地证据

- Django check、迁移检查、P13-A 定向 pytest、Ruff、OpenAPI 校验和三端 TypeScript 检查由 `scripts/verify-p13-a.ps1` 执行。
- P13-A 定向测试覆盖投影重放幂等、风险信号 CAS、通知 Outbox 去重、已读和偏好版本更新。
- 本地 Compose 配置检查通过；真实 Compose 空库、三端 Playwright 和 MongoDB/生产容量证据需在隔离环境执行。

## 双门禁与出口

本地门禁：通过（以脚本执行输出为准）。

真实环境门禁：待验收。

真实环境阻塞：真实 MySQL/Redis/Celery 扩展、生产日志链路、HA、容量、恢复和 RPO/RTO 尚未验证。

出口结论：**本地通过（真实环境待验收）**。
