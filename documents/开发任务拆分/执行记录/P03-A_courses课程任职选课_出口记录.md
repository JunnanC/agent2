# P03-A 课程、任职与选课

阶段：P03-A
产物版本：`0.4.0-p03a`
OpenAPI revision：`v2-p03a`

## 范围

完成课程聚合、负责人/助教任职、固定 grant、OPEN/APPROVAL 选课、容量与 live 唯一约束、退课/移除 blocker 注册接口、课程 selector、审计和 Outbox，以及 USER/TEACHING/PLATFORM 路由和三端基础接入。

## 本地证据

- Django check、迁移 dry-run、Ruff、mypy 通过。
- 课程、账号和项目测试通过；实现阶段隔离结果为 `55 passed`，最终全量基线继续由 P03-B 门禁复验。
- OpenAPI tags 与 `x-portals` 已覆盖课程、教学和平台监管路径，TypeScript 类型已生成。
- 隔离 Compose 验证脚本已执行成功：空 MySQL 迁移通过，课程相关表数量为 22，MySQL、Redis、MinIO、ClamAV、MongoDB、日志、Celery、Django、Kong、Nginx 全部完成启动并在脚本结束后清理。

## 门禁

开发环境：本地虚拟环境；Compose/MySQL 隔离验证：已执行。

本地门禁：静态与隔离测试通过。

真实环境门禁：待验收（当前仅本地 Compose，不代表真实部署）。

出口结论：本地通过（真实环境待验收）。

阻塞与后续：P03-B 已复用本阶段真实 enrollment service，不得旁路写入名册；Compose 双连接并发容量、入口 Playwright 和最小权限 SQL 的生产等价验收仍待真实环境执行。
