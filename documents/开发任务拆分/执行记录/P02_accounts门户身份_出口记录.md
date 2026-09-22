# P02 accounts 与三门户身份出口记录

记录日期：2026-09-20  
产物版本：`0.3.0-p02`  
OpenAPI revision：`v2-p02`  
开发环境：本地 Docker Compose  及空 MySQL/Redis 隔离集成环境

## 阶段

阶段：P02 accounts 与三门户身份  
开始条件：P01 已达到“本地通过（真实环境待验收）”  
本次范围：账号、身份资料、教师资格、平台管理员资格、portal 绑定 Session/CSRF、三个独立门户登录与治理工作台。OIDC、父域 Cookie SSO、JWT、teams、课程和实验权限不在本阶段范围内；OIDC 保留至 P13。

## 数据库/schema

- 新增 accounts 初始 schema：
  - `accounts_user`
  - `accounts_identity_verification`
  - `accounts_teacher_qualification`
  - `accounts_teacher_qualification_event`
  - `accounts_platform_admin_assignment`
  - `accounts_platform_admin_assignment_event`
- 对外暴露的核心 `public_id` 已迁移为 26 位 ULID；唯一约束、外键、状态约束、版本字段和必要索引已完成。
- 密码使用 Argon2；身份编号只持久化 HMAC 与掩码，原值不写入账号表、响应、审计、Outbox 或日志。
- 运行时账号只允许 AppendOnly 事件表 `SELECT, INSERT`；空 MySQL 集成环境执行 UPDATE 实测返回 MySQL `1142 UPDATE command denied`。
- Session 使用数据库-backed Django Session；host-only、Secure、HttpOnly、SameSite=Lax，按 portal 配置 idle/absolute expiry。

## 后端

- 实现登录、登出、全量登出、`GET /api/v2/me`、个人资料更新、改密、身份资料提交/审核和平台账号治理 API。
- `PortalContextMiddleware` 只接受可信网关注入的 `X-Portal`；USER、TEACHING、PLATFORM 分别检查教师资格和平台管理员资格。
- Session 绑定 portal；复制 USER Session 到 TEACHING/PLATFORM 返回 `SESSION_PORTAL_MISMATCH` 并立即清除 Session。
- 账号停用、教师资格撤销、平台管理员资格撤销、改密和全量登出通过 security version 立即使旧 Session 失效。
- 登录按 IP+规范化账号+portal 使用 Redis 事务限流；失败响应不泄露账号是否存在。
- 有副作用的 P02 POST 使用 P01 幂等记录和精确响应重放；改密覆盖 If-Match/CAS、冲突和幂等重放。
- 账号、身份审核、教师资格、管理员资格变更均写入审计与 Outbox；最后一名平台管理员撤销受到保护。
- 提供 `bootstrap_platform_admin` 和 `seed_p02_e2e`，只用于本地/集成测试数据，不作为生产初始化数据。

## 前端

- 三个独立应用已从 health shell 替换为真实 P02 页面：
  - user-web：登录、概览、个人资料、密码和身份认证资料。
  - teacher-web：登录和服务端教师资格/门户摘要。
  - admin-web：用户账号、教师资格、管理员资格和身份审核工作台。
- 共享 `auth-client` 提供 CSRF 初始化、`/me`、登录/退出/全量退出、portal mismatch 和 401/403 Session 失效处理；失效时清除 React Query 私有缓存。
- 页面覆盖 loading、error、empty、403、409、412、幂等请求和 ETag/If-Match 状态；浏览器 localStorage 不保存 Session 或 Token。
- Playwright 使用独立入口 URL，且等待登录完成后再读取 host-only Session Cookie。

## 基础设施

- Compose 的 app 子网、入口端口、Fluentd、MinIO 控制台和 Prometheus 端口均可通过环境变量覆盖，避免并行本地项目冲突。
- P02 集成脚本使用独立项目名、`172.30.202.0/24`、入口 `18082`，并在健康探测中显式绕过系统代理；成功或失败均清理容器、网络和卷。
- Swarm stack、README 和 bootstrap 提示已加入独立 `identity_hmac_key` Secret；该密钥与 Django signing key 分离。
- `v2-p02` OpenAPI 已导出并生成 TypeScript 类型；三个 portal 的 paths、tags 和 `x-portals` 已有测试。

## 测试与本地证据

本地门禁：通过  
真实环境门禁：待验收

已执行并通过：

- `./scripts/verify-p02.ps1`
  - `manage.py check`、`makemigrations --check --dry-run` 通过。
  - 后端 `64 passed`，覆盖 Session portal mismatch、资格/停用失效、改密幂等、限流、脱敏、最后管理员保护、OpenAPI 和基础设施契约。
  - Ruff 通过；mypy 对 100 个 Python 源文件通过。
  - 前端 typecheck、ESLint、Vitest `16 passed`、user/teacher/admin 三端 production build 全部通过；Vite `7.3.6`、Vitest `3.2.7` 已更新至当前兼容安全修复版本线。
  - Compose 与 Swarm 配置验证通过；`npm audit --omit=dev --registry=https://registry.npmjs.org` 返回 `found 0 vulnerabilities`。
- `./scripts/verify-p02-integration.ps1`
  - 空 MySQL/Redis 创建成功；P02 六张 accounts 表与 `django_session` 共 7 张关键表建立成功。
  - bootstrap 管理员和 disposable student/teacher identities 创建成功；ULID 长度断言为 26。
  - 运行时账号更新管理员事件表被 MySQL `1142` 拒绝。
  - Nginx → Kong → Django 真实入口健康检查返回 `openapi_revision=v2-p02`，入口使用独立端口 `18082`。
  - Playwright 三门户共 4 项通过：USER 1、TEACHING 2、PLATFORM 1；覆盖独立登录、教师准入、复制 Session 拒绝、管理工作台、响应式视口和 localStorage 边界。
- 浏览器视觉验收：1440、920、390 视口页面级无横向溢出；管理端移动表格仅在表格容器内滚动；浏览器错误日志为空。

## 失败与恢复覆盖

- 初次隔离集成因现有本地项目占用 app 子网和 8080 入口，已分别通过 `APP_NETWORK_SUBNET` 与 `ENTRY_PORT` 等变量隔离。
- 初次真实入口健康探测受 PowerShell 系统代理影响返回 502；容器内和禁用代理的宿主请求均为 200，脚本已加入 `Invoke-RestMethod -NoProxy`。
- 初次浏览器复制 Session 用例存在登录跳转时序抖动；公共 login helper 现明确等待离开 `/login`，全新空库重跑后三门户 E2E 全部通过。
- 集成脚本使用 `finally` 清理；最终验证后 `edu-platform-p02-verify` 项目无残留容器、网络或卷。

## 真实环境阻塞

- 尚无三台预发布 Manager、正式 DNS/TLS、入口负载均衡、防火墙和可信代理网段；P00 真实入口门禁仍待完成。
- 尚未在外部 MySQL 验证 migration/runtime 账号创建、最小授权、备份恢复、故障切换和生产数据量并发。
- 尚未在外部 Redis、MongoDB Replica Set、MinIO/S3、ClamAV 和队列环境验证冗余、故障切换、恢复、容量和保留策略。
- 尚未完成 Swarm Secrets/Configs 轮换、三 Manager quorum、节点丢失、滚动回滚、跨节点日志/指标连续性和 RPO/RTO 验收。
- P03 尚未提供课程/任职事实，因此教师资格撤销后的课程负责人阻断只能保留结构化接口边界，不能在 P02 提前实现课程规则。
- 开发依赖审计仍有 Vitest 3 线的 2 个 moderate advisory，修复建议跨到 Vitest 5；它们不进入生产依赖，生产审计为 0，本阶段不强制进行 breaking major upgrade。

## 出口结果

**本地通过（真实环境待验收）。** P02 的本地 Definition of Done 已满足，允许进入 P03 的本地开发；该结论不代表“正式通过”“生产就绪”或 HA 已验证。真实服务器条件具备后，必须按 P00 真实基础设施、P01、P02 顺序复验入口、Session、数据库权限、外部数据服务、故障恢复、性能和安全证据，全部阻塞关闭后方可更新为“正式通过”。

## 复验命令

```powershell
./scripts/verify-p02.ps1
./scripts/verify-p02-integration.ps1
npm.cmd audit --omit=dev --registry=https://registry.npmjs.org
docker compose -p edu-platform-p02-verify -f docker-compose.dev.yml ps
```
