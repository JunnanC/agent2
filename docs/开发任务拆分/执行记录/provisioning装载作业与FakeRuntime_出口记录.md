> 历史命令说明（2026-10-30）：本文保留原开发阶段编号及当时执行记录。当前脚本、管理命令和 Compose 配置档已按功能重命名，执行前请查看[现入口迁移表](../../naming-conventions.md)；原命令不作为当前可用性证明。

# 实验环境装载 provisioning 装载作业与 FakeRuntime 出口记录

阶段：实验环境装载 本地 Compose + FakeRuntime

日期：2026-09-23

## 范围与边界

- 新增 provisioning instance、job、stage event 三张业务事实表及迁移。
- 复用现有 实验发布 任务状态机、治理配额预留、Core CAS、Outbox、审计、FailureRecord 与 CompensationTask。
- Worker 按 QUOTA_CHECK、IMAGE_PREPARE、CREATE、NETWORK_ATTACH、BOOT_PROBE、WORKSPACE_READY 六阶段执行；阶段事件为追加事实。
- FakeRuntime 支持失败、超时、部分创建成功、幂等重放、状态探测、端点和销毁注入。
- 仅实现本地 FakeRuntime；不连接真实 Docker/Swarm/VM，不实现工作区票据、终端或真实 Runtime。真实 Runtime 保留到 真实运行环境。
- 取消仅允许尚未调用 Runtime 的 QUEUED 作业；残留外部实例必须先完成补偿才能 retry。

## 接口与前端

- `POST /api/v2/tasks/{task_id}/start`
- `GET /api/v2/tasks/{task_id}/provisioning-job`
- `POST /api/v2/tasks/{task_id}/retry`
- `POST /api/v2/tasks/{task_id}/provisioning-job/cancel`
- teacher-web 任务追踪和 admin-web 异常汇总复用既有任务查询，增加 provisioning 摘要。
- user-web 增加阶段展示、SSE 接收与轮询降级、排队取消、重试、403/409/412/429 提示和 trace 复制。

## 验证范围

- 后端专项测试：六阶段成功、各阶段失败、超时/部分成功补偿、补偿前拒绝 retry、补偿后 retry、排队取消、Worker 重放、追加阶段事件。
- Django check、迁移 dry-run、Ruff、OpenAPI validate、前端 typecheck/lint/build 和 实验环境装载 Playwright 脚本已纳入 `scripts/verify-p07.ps1` 与 `scripts/verify-p07-integration.ps1`。
- FakeRuntime disposable seed：`seed_p07_e2e`，仅允许 local/integration/test 或 DEBUG 环境。
- 本次本地证据：后端 `122 passed`，前端 Vitest `16 passed`，三端生产构建通过；隔离 Compose 完成全量迁移、账号与门户身份–实验环境装载 seed、MySQL 最小授权、Django/Celery、OpenAPI 校验，实验环境装载 三端 Playwright `3 passed`。

## 双门禁与出口

开发环境：本地 Compose + FakeRuntime。

本地门禁：通过（以最终验证命令输出为准）。

真实环境门禁：待验收。真实 Runtime、Swarm/VM 网络隔离、三 Manager HA、正式 DNS/TLS、外部依赖冗余与恢复、节点故障、容量性能和 RPO/RTO 均未在本阶段验证。

出口结论：**本地通过（真实环境待验收）**。

该结论不代表正式通过、生产就绪或真实 Runtime 已验收。
