> 历史命令说明（2026-10-30）：本文保留原开发阶段编号及当时执行记录。当前脚本、管理命令和 Compose 配置档已按功能重命名，执行前请查看[现入口迁移表](../../naming-conventions.md)；原命令不作为当前可用性证明。

# 资源治理 governance 治理目录、配额与策略出口记录

阶段：资源治理 governance 治理目录、配额与策略

开始条件：课程协作-B 本地基线文件和三端真实 API 实现已保留并接续。

本次范围：

- 建立 runtime adapter、image asset、resource profile、quota、quota reservation、security policy、network allowlist 七张治理表。
- 实现 ULID、row_version/CAS、不可硬删除、digest/资源规格冻结、三级配额交集、MySQL reservation、Redis 重建、审计、Outbox、维护任务、健康/配额告警和对象存储探测。
- 提供 platform-governance 管理 API、教学课程治理摘要、用户资源摘要，包含 portal scope、Idempotency-Key、If-Match、近期认证和脱敏错误链路。
- 三端接入真实治理 API：管理端运行时/镜像/资源规格/配额/安全策略页面，教师端课程治理摘要，用户端课程资源摘要。
- 固定产物版本 `0.5.0-p04`、OpenAPI revision `v2-p04`，加入 资源治理 静态和隔离 Compose 验证入口。

数据库/schema：

- `apps/governance/migrations/0001_initial.py` 只创建上述七张表；未创建 实验发布/实验环境装载 task、instance 或 provisioning 表。
- scope、状态、风险、网络端口、资源正数、容量边界和唯一键由模型约束与 service 双重校验；reservation 以固定 Platform → Course → User 锁顺序执行。

后端：

- model/service/selector/permission/API/task/metrics/ports 和幂等、审计、Outbox 已接入现有 core/accounts/courses 边界。
- 默认 seed 仅包含拒绝出网/禁止 privileged 安全策略和 `2 CPU / 4096 MB / 20 GB` 资源规格；资源治理 disposable seed 独立限制在本地/integration/test。

前端：

- `admin-web` 增加 `/runtimes`、`/images`、`/resource-profiles`、`/quotas`、`/security`；安全页读取白名单、预热/扩缩容策略、usage 和 alerts。
- `teacher-web` 和 `user-web` 分别读取课程治理摘要与 ACTIVE enrollment 资源摘要；查询失败、空结果、403/409/412 状态沿用共享 RequestStateView，凭证和治理事实不写入 localStorage。

基础设施：

- Compose 与 Swarm 默认元数据更新至 资源治理；保留 Nginx → Kong → Django、MySQL、Redis、MinIO、Celery 和日志链路。
- 未启用 django-celery-beat、Docker Socket、真实 Swarm/VM Runtime 或学生工作区。

测试与本地证据（2026-09-21）：

- `python -m pytest`：91 passed（包含跨用户课程配额交集回归）。
- `python -m ruff check education_experiment_platform`：通过。
- `python -m mypy education_experiment_platform`：通过。
- `manage.py check`：通过；`makemigrations --check --dry-run` 在 test settings：无变更。
- OpenAPI 生成/validate、共享 TypeScript 生成：通过，包含治理路径、错误契约、ETag、Idempotency-Key 和 `x-portals`。
- 前端 `npm run typecheck`、`lint`、`test`、`build`：通过。
- `docker compose ... config --quiet`、`docker stack config`：通过。
- `scripts/verify-p04-integration.ps1`：隔离 Compose 验证通过并已清理临时资源；空 MySQL 建表、七张治理表计数、治理默认 seed、维护任务、OpenAPI validate、MinIO 健康和全量本地服务启动均通过。
- 隔离验证使用独立入口 `18084`、Fluent Bit `24226`、MinIO 控制台 `19002`、Prometheus `19090` 和 `172.32.204.0/24` 子网，未覆盖其他本地项目。

真实环境门禁：待验收。三 Manager quorum、正式 DNS/TLS、外部持久化 HA、真实 Runtime、节点容量、故障恢复、性能和回滚尚未提供证据。

入口 Playwright：待执行。当前缺少 disposable 资源治理 seed 凭证和持续运行的本地 Nginx → Kong → Django 入口；不将未执行的真实入口验收伪记为通过。

出口结果：本地通过（真实环境待验收）。该结论只允许进入后续本地 实验模板 工作，不代表生产就绪或正式通过。
