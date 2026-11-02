# 课程协作-B 课程内容、互动、导入与复制

阶段：课程协作-B
产物版本：`0.4.0-p03b`
OpenAPI revision：`v2-p03b`

## 范围

完成 chapter、material/material version、announcement、calendar event、问答与 moderation event、课程/章节先修、独立 HMAC 邀请码、CSV 名册导入 job/item、课程复制 job/item、q_content Celery task 注册、课程内容 API 和三端课程页面。

资料发布要求章节已发布，FILE 资料要求 `ObjectAsset.CLEAN`；发布版本通过新版本创建保持历史引用不漂移。先修状态无可靠完成事实时返回 `NOT_EVALUABLE`，不自动视为满足。复制不创建任职、名册或学生业务数据。

## 本地证据

- 全量后端测试：`80 passed`。
- Ruff、mypy、Django check、migration dry-run 通过。
- OpenAPI 无生成 warning/error，已重新生成 `frontend/packages/api-client/src/generated/schema.d.ts`。
- 前端 typecheck、lint、Vitest、build 全部通过。
- 隔离 Compose 验证脚本已执行成功：空 MySQL 迁移通过，课程相关表数量为 22，MySQL、Redis、MinIO、ClamAV、MongoDB、日志、Celery、Django、Kong、Nginx 全部完成启动并在脚本结束后清理。
- 内容服务专项测试覆盖资料版本发布、HMAC 邀请码一次性消费、先修环检测、复制版本映射和 CSV 导入失败行重试。

## 门禁

开发环境：本地虚拟环境；Compose/MySQL、MinIO/ClamAV、Nginx → Kong → Django：已执行；三端 Playwright：待执行。

本地门禁：静态与隔离测试通过。

真实环境门禁：待验收（当前仅本地 Compose，不代表真实部署）。

出口结论：本地通过（真实环境待验收）。

阻塞与后续：补充 disposable 课程协作 seed 后执行三端 Playwright 和 1440/920/390 视口验收；真实服务器 HA、外部数据服务和生产性能仍属于 真实运行环境。
