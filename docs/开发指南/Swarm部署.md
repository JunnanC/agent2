# 部署与运维

> 核对日期：2026-11-05。依据当前 Compose、Swarm 模板和部署脚本。返回[文档索引](../README.md)。

## 本地与目标环境

日常开发使用根目录 [docker-compose.dev.yml](../../docker-compose.dev.yml)；启动、演示数据和常规更新见[根 README](../../README.md)。它包含本地数据服务和单机持久卷，本地通过不证明高可用或生产恢复能力。

Swarm 服务栈位于 [stack.yml](../../infrastructure/swarm/stack.yml)，用于部署平台无状态服务。MySQL、Redis、MongoDB Replica Set 和 MinIO 需要外部服务或单独审查的持久化部署。复制数、节点标签或单机卷存在不能替代故障切换与恢复演练。

## 配置与密钥

- 先审阅 [.env.example](../../.env.example)、生产设置、stack 模板与 [deploy-swarm.ps1](../../scripts/deploy/deploy-swarm.ps1) 的实际检查；配置项以这些文件为准。
- 镜像使用可追溯标签和 Registry digest；运行时使用受控镜像与网络，不用浮动 `latest` 作为验收依据。
- 数据库、对象存储、Django、身份 HMAC、邀请码 HMAC、SMTP 密码、工作区及 Docker mTLS 等密钥通过对应 secret 管理；不能把密钥值写进普通配置、文档或命令历史。注册邮件使用外部 `email_host_password` secret。
- 核对四个门户 Host、学生和教师公开 URL、SMTP 主机与发件人、可信代理网段、CSRF/工作区允许 Origin、证书、外部服务地址、日志和运行时网络。
- 工作区访问材料只授予对应 Worker 或网关，Django Web 和普通 Worker 不直接获得 Docker API 管理权限。

## Swarm 基础条件

节点角色使用 `edu.role` 下的 `edge`、`app`、`worker`、`runtime`、`data` 标签。按部署规模安排节点；学生运行时与数据服务共置需要明确的资源和隔离审查。

运行时 overlay 网络由平台栈外部管理，默认名称为 `experimental-platform-swarm-runtime`，与本地 Compose bridge 分开。使用其他名称时同步 `SWARM_RUNTIME_NETWORK`。Fluent Bit 收集 Fluentd 日志驱动的输出，部署前核对节点端口与日志缓冲条件。

[bootstrap-local-swarm.ps1](../../scripts/deploy/bootstrap-local-swarm.ps1) 只用于可丢弃的单节点适配器环境。正式环境需要管理节点仲裁、镜像拉取、网络、密钥和数据服务均满足目标部署条件。

## 发布顺序

1. 备份业务数据库与对象数据，确认恢复路径、维护窗口和回退镜像。
2. 构建平台镜像与生产 Nginx 入口；后者使用 [Dockerfile.prod](../../infrastructure/nginx/Dockerfile.prod)，核对 TLS 与四个 Host。
3. 准备版本化配置和 secret，标记节点，建立外部运行时网络。
4. 按迁移与发布计划更新数据库并执行 [deploy-swarm.ps1](../../scripts/deploy/deploy-swarm.ps1)；该脚本会改变目标服务栈。
5. 通过真实门户验证登录、选课、发布、工作区访问、保存测试、成果提交和教师审核。
6. 记录服务状态、镜像摘要与证据，验证回退和恢复，再判定发布结果。

工作区镜像晋级使用 [promote-workspace-image.ps1](../../scripts/deploy/promote-workspace-image.ps1)，它要求与源镜像摘要匹配的成功旅程证据；已有本地 Registry 或本地镜像不能证明生产 Registry 晋级完成。

## 观测与恢复

- 健康入口：`/api/v2/health`、`/api/v2/health/ready`；内部指标与采集配置在 `infrastructure/`。健康通过只说明对应探针范围。
- MySQL 保存审计与业务事实；日志经 Fluent Bit/log-ingest 写入 MongoDB，指标和追踪由 Prometheus/OTel 配置管理。日志保留、容量和告警需按目标环境验收。
- 配额、实例、存储作业和孤儿资源通过业务补偿与对账处理；清理按任务标签和精确资源清单，避免影响其他项目。
- 服务回滚入口为 [rollback-swarm-service.ps1](../../scripts/deploy/rollback-swarm-service.ps1)；数据库和对象结构是否向后兼容需要独立确认。
- 证据采集使用 [collect-swarm-evidence.ps1](../../scripts/deploy/collect-swarm-evidence.ps1)，默认写入 `evidence/swarm/`。

## 尚需目标环境验收

Swarm 真实执行、三管理节点与节点丢失、外部数据库和对象存储故障切换、DNS/TLS、生产 Registry 晋级、滚动回退、备份恢复及容量性能，都需要在对应环境执行并留证。阶段结果用[记录模板](../文档模板/阶段记录.md)注明环境和未验证项；不能把本次文档核对写成验收通过。
