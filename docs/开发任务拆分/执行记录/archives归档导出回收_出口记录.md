> 历史命令说明（2026-10-30）：本文保留原开发阶段编号及当时执行记录。当前脚本、管理命令和 Compose 配置档已按功能重命名，执行前请查看[现入口迁移表](../../naming-conventions.md)；原命令不作为当前可用性证明。

# 归档与回收 archives 归档、导出与资源回收出口记录

阶段：归档与回收 本地 Compose + FakeRuntime

日期：2026-09-24

## 范围与边界

- 在既有架构内新增 `archives` app、四张归档/校验/导出事实表、首个 migration、FK/唯一约束/索引和 AppendOnly 保护；ArchiveJob 保持可更新，事实表仅查询和插入。
- 归档包使用确定性 ZIP，收录冻结报告、干净附件/系统成果、工作区最终快照和检查点、脱敏操作回放、Rubric 得分、批注与审核决定；不写入 token、运行时端点、Cookie 或敏感原始日志。
- Worker 重新核验来源对象 CLEAN、版本、大小和 SHA-256，执行 MinIO 上传、回读 digest 验证、ObjectAsset 登记、失败 Verification/FailureRecord/Audit/Outbox 和补偿；15 分钟安全期限后强制撤销会话、销毁 FakeRuntime 实例并释放 reservation。
- 审核通过、有效截止时间和发布撤回分别进入 `COMPLETED`、`EXPIRED`、`CANCELLED` 目标流程；课程关闭只触发归档条件重算和对账，不直接终止活动个人任务。
- 归档通过后统一执行 `ARCHIVING -> DESTROYING -> ABSENT -> terminal_target`，调用 workspaces/provisioning 公开 service 和 quota release，不直接更新其他 app 的表；运行时 inventory 支持外部孤儿、数据库活动实例缺失、终态资源泄漏和归档对象不一致对账。
- 归档与回收 使用 FakeRuntime 和本地 MySQL、MinIO、Celery、Outbox、Audit、补偿框架；真实 Runtime、Swarm/HA 适配仍留在 真实运行环境。

## 接口与前端交付

- USER：`GET /api/v2/tasks/{id}/archive` 返回本人归档、校验、回收、终态和受控下载摘要；兼容 教师审核 结果页并增加 `/experiments/:taskId/result` 路由。
- TEACHING：课程归档清单、归档详情、校验记录和带 If-Match/Idempotency-Key 的受控导出；导出授权受课程能力、manifest retention、一次下载和 5 分钟 token 限制。
- PLATFORM：实例/外部孤儿/终态资源泄漏清单、近期认证的实例销毁、补偿查询和 `RETRY/DEAD` 人工重试；异常操作带原因、幂等、并发版本和审计，不修改 ReviewDecision。
- teacher-web 新增课程归档清单、校验详情和实际传输进度下载；admin-web 新增 `/instances`、`/compensations`；三端使用生成 OpenAPI 类型、api-client 和 query keys，SSE 只做缓存失效并在断线时短轮询降级。
- 所有新增页面覆盖 loading、empty、error、403、404、409、412、异步处理中和重试状态；下载 token 只保存在内存。

## 本地证据

- `scripts/verify-p11.ps1`：通过。
- Django `check`：通过；`makemigrations --check --dry-run`：通过（No changes detected）。
- 后端 pytest：`173 passed`；归档与回收 归档 service/API 与基础设施契约定向测试 `24 passed`，归档与回收 service/API 当前 `8 passed`，覆盖确定性归档、对象 digest/大小/缺失校验、失败安全回收、重放清理补偿、导出 scope、管理员补偿和实例销毁 API。
- Ruff：通过；`git diff --check`：通过（仅保留 Git 的 LF/CRLF 提示）。
- OpenAPI 生成与校验：0 errors；保留 9 个既有枚举命名 warning；TypeScript 类型已生成并同步到 api-client。
- 前端 typecheck、ESLint：通过；Vitest：`23 passed`；user-web、teacher-web、admin-web production build：通过；Compose 配置校验通过。
- `scripts/verify-p11-integration.ps1 -ProjectName edu-platform-p11-verify-0924c`：最终通过并自动清理隔离环境；链路覆盖 MySQL migration/最小权限、Redis、MinIO、ClamAV、MongoDB、Celery/Beat、FakeRuntime、Nginx -> Kong -> Django、容器 OpenAPI、账号与门户身份-归档与回收 种子和健康检查。
- 归档与回收 三门户 Playwright：`3 passed`；真实旅程完成 user 兼容结果页归档展示、teacher 校验详情与受控导出、admin 实例/补偿监管页，并验证 1440px、920px、390px 响应式无横向溢出。

## 双门禁与出口

开发环境：本地 Compose + FakeRuntime。

本地门禁：通过。

真实环境门禁：待验收。

真实环境阻塞：真实 Runtime 适配与销毁语义、Swarm/HA 调度与故障转移、外部对象存储版本恢复和跨区域恢复、生产容量/性能/压测、生产回滚与 RPO/RTO 证据尚未在本地环境验证。

出口结论：**本地通过（真实环境待验收）**。

该结论仅开放后续真实环境验收，不代表正式生产通过、真实 Runtime/Swarm/HA 已完成，或外部存储恢复、性能和生产回滚已经具备证据。
