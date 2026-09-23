# P06 experiments 发布与个人任务出口记录

阶段：P06 experiments 发布、先修、延期、受众与个人任务

日期：2026-09-22

## 范围与边界

- 已建立 `experiments` 七张架构表：publication、publication audience、publication prerequisite、experiment task、task state transition、task extension request、task extension decision。
- 已实现发布草稿与生命周期、模板/Rubric 冻结、受众快照、章节/前置实验先修、个人任务生成、晚选补建、延期决定和 14 态任务状态机。
- 发布人数少于 100 时同步生成并返回 `201`；大于等于 100 时进入 `PUBLISHING`，由 Celery 按可配置分片异步生成并返回 `202`。
- 已通过 `(publication, student)` 唯一约束、幂等服务、行锁和 `If-Match` 覆盖发布重试、Worker 重放、补建、状态跃迁和延期决定。
- 已通过 courses 公开 port 接入选课激活回调及未完成任务退课阻断；未直接跨 app 访问内部实现。
- 已实现 teacher-web 发布/任务/延期页面、user-web 任务/先修/窗口页面和 admin-web 只读异常监管页面；OpenAPI revision 为 `v2-p06`，产品版本为 `0.7.0-p06`。
- 明确不进入 P07-P10：`start` 只将任务推进至 `PROVISIONING`，未创建 Swarm/VM 实例、工作区 token、报告或审核决定。

## 数据、权限与异步证据

- publication 冻结 course、template version、rubric version、核心窗口、受众规则及快照；发布后名册变化不会改写既有受众。
- `SELECTED` 仅接受同课程 `ACTIVE enrollment`；模板、Rubric、前置发布和任务访问均执行课程/学生 scope，越权对象返回受控 `404`。
- 前置发布循环依赖（含传递循环）被拒绝；没有可靠章节完成事实时返回 blocker，不推定先修已满足。
- 课程关闭不直接终止个人任务；撤回不会改写已完成任务，也不会伪造运行时销毁结果。
- 延期决定为不可覆盖的追加事实；并发决定只有一个成功，批准只更新个人有效时间窗。
- Celery 分片分配、发布失败记录、补偿任务、Outbox、审计、trace 和 metrics 入口均已接入；晚选和重放依赖数据库唯一边界保持幂等。
- 平台异常接口可只读汇总失败任务/发布、补偿积压、状态异常及任务/发布对账异常。

## 静态与后端证据

- 后端 pytest：`117 passed`，其中 P06 定向测试 `11 passed`。
- Ruff：通过。
- mypy：通过（193 个源文件）。
- Django check：通过。
- migration dry-run：通过，无遗漏迁移。
- OpenAPI 生成并 validate：无错误；仅有 3 个既有 enum 命名 warning。
- 前端 typecheck、lint、Vitest（`16 passed`）和三端 production build：通过。
- Compose config、Swarm stack config 和 PowerShell 脚本解析：通过。

## 隔离 Compose 证据

执行入口：`scripts/verify-p06-integration.ps1`，使用独立 Compose project、空 MySQL、独立 volumes/networks；验证结束自动清理 containers、volumes 和 networks。

- 空 MySQL 完成全量 migration，并确认 P06 七张表及最小业务账号授权存在。
- Django 与 Celery 启动成功，OpenAPI 校验通过，P02/P03/P04/P05/P06 disposable seed 链通过。
- edge stack（Nginx → Kong → Django 双副本）健康检查通过，P06 请求经真实本地入口执行。
- teacher/user/admin Playwright 串行执行 `3 passed`：
  - teacher 可访问发布、任务追踪和延期决定入口。
  - user 可查看本人任务、冻结事实和任务详情。
  - admin 异常任务页保持跨课程只读。
- 页面覆盖 1440、920、390 视口；未发现横向溢出或页面元素遮挡。

## 修正记录

- 修正审计数据中的 datetime JSON 序列化、已发布受众被后续修改、跨课程晚选补建和撤回误改已完成任务。
- 修正缺失模板/Rubric 的非受控错误、传递先修循环、学生 `allowed_actions` 计算和跨学生任务访问泄露。
- 修正 Docker 构建上下文误排除正式 Django 工程的问题，并补齐 P06 表的最小 MySQL grants。
- Playwright 集成验证改为单 Worker，并为真实 edge 冷启动保留合理超时，避免本机资源竞争造成页面初始化超时。
- 移除初始仓库遗留的平行 `backend/apps`、`backend/config`、旧 `manage.py` 和旧部署链；后端代码、settings、测试和管理命令统一到 `backend/education_experiment_platform`。

## 双门禁与出口

开发环境：本地 Compose。

本地门禁：通过。

真实环境门禁：待验收。

真实环境阻塞：三 Manager Swarm HA、正式 DNS/TLS、私有镜像仓库、外部 MySQL/Redis/MongoDB/MinIO 冗余与恢复、真实 Runtime 网络隔离、节点故障与滚动回滚、接近生产数据量的容量/性能和 RPO/RTO 均未验证。P07 的实际装载能力亦尚未实现，不能由本阶段的 `PROVISIONING` 状态骨架替代。

出口结论：**本地通过（真实环境待验收）**。

该结论只允许进入 P07 的本地开发，不代表正式通过、生产就绪或真实运行时可用。真实环境具备后，仍须按 P00-P14 顺序复验并关闭上述阻塞项。
