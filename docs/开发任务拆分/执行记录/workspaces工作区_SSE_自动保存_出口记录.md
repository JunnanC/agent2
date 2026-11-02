> 历史命令说明（2026-10-30）：本文保留原开发阶段编号及当时执行记录。当前脚本、管理命令和 Compose 配置档已按功能重命名，执行前请查看[现入口迁移表](../../naming-conventions.md)；原命令不作为当前可用性证明。

# 工作区 workspaces 工作区、SSE、自动保存与回放出口记录

阶段：工作区 本地 Compose + FakeRuntime

日期：2026-09-23

## 范围与边界

- 新增 `apps.workspaces` 工作区事实模型、迁移、选择器、权限、服务、API、HTTP FakeRuntime 网关和 Celery 维护任务。
- 工作区票据只持久化 token hash 与 jti；原始 token 仅在签发/续签响应返回，并由前端内存持有。
- 自动保存使用 multipart 上传，执行 MIME/magic 校验、ClamAV 扫描、SHA-256、MinIO 版本化对象登记和 MySQL CAS latest pointer 更新。
- 检查点不可变；恢复通过新 snapshot/恢复事件产生新版本，不覆盖历史对象。
- 操作面板只接受白名单动作并记录脱敏摘要；FakeRuntime 通过 HTTP 受控网关提供状态和操作，不实现真实终端、WebSocket、Docker、Swarm 或 VM 连接。
- SSE 使用门户 Session 认证、服务端 scope 裁剪、Last-Event-ID、Redis Stream/MySQL Outbox 回放、去重、`resync.required`、心跳和 no-buffering 响应头。
- user-web 增加实验室、检查点、回放和实验路由别名；teacher-web 只读快照/回放；admin-web 只读会话异常摘要，不提供学生工作区入口。

## 接口与前端交付

- USER：进入/创建/续签/撤销工作区会话、multipart 快照、检查点创建/恢复、操作回放。
- TEACHING：课程授权范围内的快照摘要和脱敏操作回放；授权撤销后由服务端拒绝。
- PLATFORM：工作区 session/过期/撤销/失败摘要；不返回学生票据。
- `/workspace/{session_public_id}/state` 和 `/operations` 仅接受 USER 工作区票据，并由白名单 FakeRuntime 操作服务处理。
- event-client 支持每门户单连接、SSE 解析、cursor、去重、指数退避和轮询降级；api-client/query-keys 已加入 工作区 类型和 key。
- user-web IndexedDB 仅保存实验内容待同步队列，不保存 session/token；网络恢复后按 client_seq 顺序提交，冲突提供服务端/本地/新版本选择。

## 验证证据

- Django `check`：通过（`education_experiment_platform.settings.test`，SQLite 内存数据库）。
- `makemigrations --check --dry-run`：通过（No changes detected）。
- 后端 pytest：`133 passed`。
- 工作区专项测试：`9 passed`，覆盖票据轮换、撤销、退课/停用/任务撤回即时失效、网关白名单、敏感参数脱敏、SSE grant 裁剪和 cursor 恢复。
- Ruff：通过。
- OpenAPI 生成与校验：0 errors；保留 4 个既有枚举命名 warning。
- 前端 typecheck：通过。
- 前端 ESLint：通过。
- 前端 Vitest：`19 passed`，包含 event-client SSE 解析/去重、`Last-Event-ID` 重连和失败后轮询降级。
- user-web、teacher-web、admin-web production build：通过。
- Compose 配置静态检查已纳入 `scripts/verify-p08.ps1`。
- `scripts/verify-p08-integration.ps1` 隔离 Compose 全链路通过；三端 Playwright `3 passed`，用户旅程实际完成 ClamAV 扫描、MinIO 版本化快照、FakeRuntime 操作、离线 IndexedDB 入队、网络恢复后按序 flush、检查点创建、恢复为新版本和操作回放。

## 双门禁与出口

开发环境：本地 Compose + FakeRuntime。

本地门禁：通过（以最终验证命令输出为准）。

真实环境门禁：待验收。真实 DNS/TLS、Swarm/VM、HA、外部存储冗余、节点故障、容量性能、RPO/RTO、生产对象生命周期和回滚证据未在 工作区 验证。

出口结论：**本地通过（真实环境待验收）**。

该结论不代表正式生产通过、真实 Runtime 已接入或生产性能已验收。
