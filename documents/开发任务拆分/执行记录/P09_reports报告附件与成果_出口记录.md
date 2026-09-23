# P09 reports 报告、附件与成果出口记录

阶段：P09 本地 Compose + FakeRuntime

日期：2026-09-23

## 范围与边界

- 新增报告草稿、附件关联、冻结报告版本、版本附件映射和系统成果模型及迁移。
- 报告草稿按 task/student scope 读写，正文使用 Markdown，并通过 ETag/If-Match CAS 防止并发覆盖。
- 学生首次进入必交报告任务工作区时初始化草稿；只读 GET 不产生业务事实。
- 附件复用 core asset、MinIO、ClamAV、Audit、Outbox 和异步扫描能力；对象 key 使用 opaque 标识，不含原文件名。
- 提交事务锁定 task/draft，校验任务、选课、课程、学生、最新工作区快照 digest 和附件扫描状态；同一事务内创建只追加冻结版本及附件映射、推进任务到 `UNDER_REVIEW` 并写入 Audit/Outbox。
- 非报告任务通过服务端读取的最新已扫描工作区快照登记系统成果，不接受客户端指定跨任务资产。
- core 增加通用一次性下载 grant；数据库只保存 token hash，并原子校验资产/课程 scope、有效期、次数和撤销状态，客户端不接触 MinIO key。
- P09 不实现教师审核决定、归档销毁、管理员代提交，也不声明生产环境就绪。

## 接口与前端交付

- USER：报告草稿读取/保存、受控附件上传、上传完成、扫描状态、报告提交、版本历史和非报告任务完成。
- TEACHING：具备课程 `REVIEW_SUBMISSION` 权限时只读预览冻结报告和成果，并通过受控 grant 下载附件；授权撤销后服务端拒绝访问。
- PLATFORM：仅提供脱敏的附件扫描异常摘要，不返回报告正文或附件内容。
- 通用下载接口为 `POST /api/v2/files/{asset_id}/download-grants` 与 `GET /files/{one_time_token}`；过期、用尽、撤销或 scope 不符时拒绝下载。
- user-web 已接入 Markdown 编辑、扫描状态、提交确认和版本历史；teacher-web 已接入只读成果预览和下载；admin-web 已接入脱敏扫描异常摘要。
- OpenAPI revision 固定为 `v2-p09`，API 类型和 query keys 已按契约生成。

## 本地证据

- `scripts/verify-p09.ps1`：通过。
- Django `check`：通过；`makemigrations --check --dry-run`：通过（No changes detected）。
- 后端 pytest：`150 passed`，覆盖草稿 CAS、提交幂等、快照/附件校验、冻结事实不可变、下载 grant 和权限边界等 P09 行为。
- Ruff：通过。
- OpenAPI 生成与校验：0 errors；保留 5 个既有枚举命名 warning。
- 前端 typecheck 与 ESLint：通过；Vitest：`19 passed`。
- user-web、teacher-web、admin-web production build：通过。
- `scripts/verify-p09-integration.ps1 -ProjectName edu-platform-p09-final-0923a`：通过；隔离项目验证完成后已自动清理其容器和卷。
- 隔离 Compose 验证通过 MySQL migration/最小运行权限、MinIO 版本化对象与受控宿主机上传、ClamAV 异步扫描、Celery、Nginx -> Kong -> Django、OpenAPI 和健康检查。
- P09 Playwright：`2 passed`；学生旅程完成快照保存、草稿 CAS、附件上传与 `CLEAN` 扫描、冻结版本提交，教师完成授权预览和一次性 grant 下载，管理端验证脱敏异常摘要且不暴露附件内容。

## 双门禁与出口

开发环境：本地 Compose + FakeRuntime。

本地门禁：通过。

真实环境门禁：待验收。

真实环境阻塞：真实节点与 DNS/TLS、Swarm/HA、真实 Runtime、外部对象存储与数据库冗余、节点/依赖故障、容量与性能、生产恢复和 RPO/RTO、对象生命周期及生产回滚证据均未在 P09 本地环境验证。

出口结论：**本地通过（真实环境待验收）**。

该结论仅开放 P10 的本地开发，不代表正式生产通过、真实基础设施已验收或生产性能与恢复目标已满足。
