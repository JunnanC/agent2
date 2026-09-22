# P01 core 共享基础设施出口记录

记录日期：2026-09-20  
产物版本：`0.2.0-p01`  
OpenAPI revision：`v2-p01`  
开发环境：本地 Docker Compose

## 阶段

阶段：P01 core 共享基础设施  
开始条件：P00 已达到“本地通过（真实环境待验收）”  
本次范围：事务一致性、幂等、乐观并发、统一错误、审计、Outbox、补偿、对象资产、trace、共享前端协议和相应本地基础设施接线。未实现 P02 账号与身份、业务上传、MinIO 业务调用或任何领域 API。

## 数据库/schema

- 新增初始 migration `apps/core/migrations/0001_initial.py`，建立八张 P01 表：
  - `core_object_asset`
  - `core_object_purge_log`
  - `core_outbox_event`
  - `core_outbox_delivery`
  - `core_idempotency_record`
  - `core_audit_log`
  - `core_failure_record`
  - `core_compensation_task`
- schema 包含外键、唯一约束、状态 CHECK、调度/主体/trace/digest 索引、`row_version`、lease、重试次数和保留期字段。
- `VersionedModel` 禁止实例直接更新和硬删除，写操作必须通过 CAS；`AppendOnlyModel` 的实例 `save/delete` 和 QuerySet `update/delete` 均阻止修改既有事实。
- migration 与运行时数据库账号分离。运行时账号对四张 AppendOnly 表只有 `SELECT, INSERT`，对可变 core 表只有 `SELECT, INSERT, UPDATE`。
- 隔离的空 MySQL 8.4 环境已从零执行 migration。运行时账号更新 `core_outbox_event` 实测返回 MySQL `1142 UPDATE command denied`，同时仍可追加 `core_failure_record`。

## 后端

- 实现统一稳定错误码和 JSON 错误信封；`428/412/409/429/422` 等横切失败具有固定映射和 trace。
- 实现 ETag、`If-Match` 解析及 `row_version` CAS。真实 MySQL 双连接并发探针严格断言结果为 `SUCCESS + ROW_VERSION_CONFLICT`。
- 实现页码和 cursor 分页工具。
- 幂等范围固定为 actor、auth-context、portal、method、endpoint、key 和请求 digest；相同意图精确重放原状态码、响应头及响应体，不同 digest 返回 `422`。真实 MySQL 双连接并发探针严格断言 `SUCCESS + REPLAY`，副作用函数只执行 1 次。
- 所有有副作用的 POST 默认要求 `Idempotency-Key`，例外仅有架构 `08` 指定的五项：`/auth/login`、`/auth/logout`、`/auth/logout-all`、`/integrations/oauth/token`、`/course-invitations/resolve`。
- 实现递归脱敏，覆盖 Authorization/Token、Cookie、CSRF、密码、IP、证件号、credential 和签名 URL；审计、失败记录、Outbox payload 与日志均在写入前脱敏。
- 实现对象资产登记、digest、扫描状态、保留期和 purge log 基础服务；未实现具体业务上传和对象存储调用。
- 实现 Outbox event/delivery、`on_commit` 入队、delivery lease、指数退避、Redis Stream relay 和消费者幂等。事务回滚不留下 Outbox 事实，重复消费只执行一次。
- 实现补偿任务注册表、lease、重试、`COMPLETED/DEAD` 状态推进和失败事实关联。
- `TraceTask` 将 trace 注入 Celery 执行上下文；Celery 保留项目 JSON logger，不接管根 logger。HTTP、Celery、Redis 事件和 MongoDB 日志可以使用同一 trace 关联。

## 前端

- `api-client` 支持相对 API 路径、CSRF、统一错误信封、trace、ETag/If-Match 和 page/cursor 分页类型。
- `RequestIntent` 在一次用户意图的重试中保持相同幂等键；请求体改变时拒绝复用该意图，避免错误重放。
- `ui` 提供通用 loading、empty、error、403、409、412、428 和 429 状态组件。
- OpenAPI 已按 `v2-p01` 重新导出并生成 TypeScript 类型；P01 未提前加入领域页面或身份流程。
- `react-router-dom` 由 `7.9.1` 升级到兼容的安全修复版本 `7.18.4`，`npm audit --omit=dev` 返回 0 个 production vulnerability。

## 基础设施

- Compose 新增 `mysql-users`、`mysql-grants` 和工具型 `core-check`，由独立迁移账号建表、独立运行时账号访问业务数据。
- Celery 固定并实际订阅九条架构队列：`q_default`、`q_relay`、`q_provision`、`q_archive`、`q_compensate`、`q_agent`、`q_content`、`q_analytics`、`q_integrations`。
- Swarm 配置同步运行时数据库账号、Secrets 边界和上述队列名；Compose 与 Swarm 配置解析均通过。
- Prometheus 暴露 core Outbox/补偿积压指标；结构化 stdout 仍由 P00 Fluent Bit/log-ingest 写入 MongoDB，MongoDB 不参与业务成功判定。
- 运行中健康入口实测返回 `version=0.2.0-p01`、`openapi_revision=v2-p01`、`portal=USER`，入口链路为 Nginx → Kong → Django。

## 测试与本地证据

本地门禁：通过  
真实环境门禁：待验收

已执行并通过：

- `./scripts/verify-p01.ps1`
  - `manage.py check` 和 `makemigrations --check --dry-run` 通过。
  - 后端 `46 passed`，其中 core `20 passed`；覆盖 model 不变量、CAS、幂等、事务回滚、Outbox、重复消费、失败退避、补偿、trace、脱敏、middleware 和基础设施契约。
  - Ruff 通过，mypy 对 76 个 Python 源文件通过。
  - 前端 typecheck、ESLint、`14 passed`、user/teacher/admin 三端 production build 全部通过。
  - Compose 与 Swarm 配置验证通过。
- `./scripts/verify-p01-integration.ps1`
  - 使用独立空卷创建 MySQL/Redis，执行初始 migration 后完成账号授权验证。
  - AppendOnly 更新返回 MySQL `1142`；受限账号可正常追加事实。
  - Redis `FLUSHDB` 后 `PING=PONG`，MySQL 中的业务事实仍为 1 条，证明 Redis 不承载业务事实。
  - 真实 MySQL 并发 CAS 结果为一个成功、一个版本冲突；真实幂等并发结果为一个执行、一个重放且副作用计数为 1。
  - 管理命令实际 relay 1 个 Outbox delivery，Redis Stream `edu:events:v2` 收到事件。
- 真实常驻环境 Outbox/trace 验证：
  - trace：`p01relay20260920fedcba0987654321`；event：`decaacb2-65fa-4b05-afa3-ce33f78ed5fa`。
  - 事务提交后 Celery 从 `q_relay` 消费；MySQL delivery 为 `DELIVERED`、`attempt_count=1`。
  - Redis Stream 收到相同 event/trace，测试 Authorization 值在 MySQL payload 和 Redis payload 中均为 `[REDACTED]`。
  - MongoDB `observability.runtime_logs` 可按相同 trace 查到 `message=outbox relay completed`、`action=outbox.relay`、`result=SUCCEEDED`、`delivered=1`。
- `./scripts/verify-p00-entry.ps1`
  - 三个 portal 的 Host、可信上下文覆盖、机器入口隔离和 SSE `X-Accel-Buffering: no` 通过。
  - Playwright user/teacher/admin 三端 smoke 各 1 项，共 `3 passed`。
- `npm audit --omit=dev` 返回退出码 0；`git diff --check` 作为最终工作区门禁执行。

## 失败与恢复覆盖

- Outbox 外部写入失败会生成已脱敏的 `FailureRecord`，delivery 进入 `RETRY` 并设置退避时间；达到最大次数后进入 `DEAD`。
- 补偿处理器成功进入 `COMPLETED`；不可重试失败进入 `DEAD` 并关联失败事实，敏感异常文本不落库。
- Redis 丢失/清空不会删除 MySQL 事实；relay 可以从数据库事实恢复投递。
- MongoDB 仅保存运行日志，日志链不可用不参与业务事务提交结果。
- 本地重建 Django 后曾出现一个 Kong 副本短暂缓存旧容器地址并返回 `502`；重启本地 Kong 两副本刷新服务发现后，完整入口门禁连续通过。该现象不作为真实集群服务发现或 HA 已通过的证据。

## 真实环境阻塞

- 尚无三台预发布 Manager、正式 DNS/TLS、入口负载均衡、防火墙和可信代理网段，继承的 P00 真实入口门禁仍待完成。
- 尚未在外部 MySQL 上验证 migration/runtime 账号创建、最小授权、备份恢复、故障切换及真实并发负载。
- 尚未在外部 Redis/队列环境验证 Worker 多副本、lease 回收、消息堆积、故障切换与恢复；本地单机结果不能替代 HA 证据。
- 尚未验证跨节点 Fluent Bit 缓冲、MongoDB Replica Set 连续性、Prometheus 告警、Secrets/Configs 轮换和日志检索保留策略。
- 尚未执行滚动升级失败自动回滚、节点丢失、接近生产数据量的容量/性能、RPO/RTO 和长时间稳定性测试。
- P01 不包含真实 Runtime、业务对象存储和领域业务旅程；这些能力必须按 P02-P14 顺序实现与验收。

## 出口结果

**本地通过（真实环境待验收）。** P01 的本地 Definition of Done 已满足，允许进入 P02 的本地开发；该结论不代表“正式通过”“生产就绪”或 HA 已验证。真实服务器条件具备后，必须先补齐 P00 真实环境证据，再按顺序复验本阶段的数据库权限、并发、Outbox、Worker、trace、日志、故障恢复和性能，全部阻塞关闭后方可更新为“正式通过”。

## 复验命令

```powershell
./scripts/verify-p01.ps1
./scripts/verify-p01-integration.ps1
./scripts/verify-p00-entry.ps1
docker compose -p edu-platform-p00 -f docker-compose.dev.yml ps
```
