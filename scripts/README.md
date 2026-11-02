# 项目脚本

当前脚本按用途命名。从仓库根目录调用；PowerShell 入口需要 PowerShell 7。`static` 表示源码和契约检查，`integration` 表示依赖容器或浏览器的集成检查，`smoke` 表示有限范围的连通性回归。

## 日常开发

| 入口 | 用途 |
| --- | --- |
| [start.sh](dev/start.sh) | 构建并启动本地 Compose 服务，检查学生门户健康接口。 |
| [stop.sh](dev/stop.sh) | 停止并移除本地 Compose 服务，保留持久数据卷。 |
| [reset-local-data.ps1](dev/reset-local-data.ps1) | 删除所选本地 Compose 项目的数据卷并重建环境；会丢失该项目数据。 |
| [export-openapi.ps1](dev/export-openapi.ps1) | 导出后端 OpenAPI 并重新生成前端 API 类型。 |

日常已有环境启动、查看和停止：

```powershell
docker compose --profile runtime up -d --no-build
docker compose --profile runtime ps -a
docker compose --profile runtime stop
```

修改源码后先执行 `docker compose build django nginx`，再重建服务并执行 `docker compose restart kong nginx`。工作区镜像改动需要单独构建 `runtime-algorithm-workspace`。

## 验证

优先使用 `./scripts/verify/backend-local.ps1`；前端在 `frontend/` 执行 `npm run typecheck`、`npm run lint`、`npm test` 和 `npm run build`。工作区镜像入口为 `./scripts/verify/workspace-image.ps1 -Image experimental-platform-workspace:local -SkipBuild`，完整镜像验收还依赖 `docker sbom`。

| 入口 | 实际用途 | 当前前置条件 |
| --- | --- | --- |
| [dependency-lock.sh](verify/dependency-lock.sh) | 检查后端依赖锁与项目依赖声明是否一致。 | Bash、uv；未安装 uv 时仅检查锁文件存在，不校验依赖一致性 |
| [backend-local.ps1](verify/backend-local.ps1) | 后端完整单测、Django/迁移、OpenAPI、Ruff、mypy 和基础设施契约检查。 | Python 3.14、backend 的开发依赖、Docker Compose |
| [portal-entry.ps1](verify/portal-entry.ps1) | 门户路由、健康接口、代理上下文与浏览器入口检查。 | 浏览器场景或 npm 命令缺失，运行前立即报错 |
| [analytics-notifications-static.ps1](verify/analytics-notifications-static.ps1) | 分析和通知专项后端测试、OpenAPI、前端类型及 Compose 检查。 | Python 3.14、backend 开发依赖、前端 npm 依赖、Docker Compose |
| [integrations-static.ps1](verify/integrations-static.ps1) | 第三方集成专项后端测试、OpenAPI、前端类型及 Compose 检查。 | Python 3.14、backend 开发依赖、前端 npm 依赖、Docker Compose |
| [operations-static.ps1](verify/operations-static.ps1) | 全项目静态门禁和 API 契约一致性检查。 | Python 3.14、backend 开发依赖、Node.js 24、前端 npm 依赖、Docker CLI |
| [workbench-static.ps1](verify/workbench-static.ps1) | 工作台验收用全后端门禁、前端契约/单测及学生端构建。 | Python 3.14、backend 开发依赖、Node.js 24、前端 npm 依赖、Docker CLI |
| [workbench-integration.ps1](verify/workbench-integration.ps1) | 现有测试环境中的工作台装载、保存、助手与提交浏览器回归。 | 浏览器场景或 npm 命令缺失，运行前立即报错 |
| [real-workspace-integration.ps1](verify/real-workspace-integration.ps1) | 真实工作区浏览器流程、令牌隔离、快照摘要与测试资源回收。 | 浏览器场景或 npm 命令缺失，运行前立即报错 |
| [workspace-image.ps1](verify/workspace-image.ps1) | 只通过 Docker 验证工作区镜像、终端、WebIDE、加固配置并生成 SBOM。 | Docker Buildx、工作区镜像或可构建环境；完整 SBOM 步骤需要 docker sbom |
| [local-runtime-smoke.py](verify/local-runtime-smoke.py) | 真实本地 Docker 工作区创建、编辑、WebIDE/终端、五类判题与回收。 | backend Python 依赖、Docker socket 访问、已构建工作区镜像及专用运行时网络 |
| [swarm-runtime-smoke.py](verify/swarm-runtime-smoke.py) | Swarm 运行时适配器连通性探针；HTTP/WebSocket 断言仍针对参考工作区协议。 | backend Python 依赖、Swarm 管理端连接、参考镜像 digest 与运行时网络；面向单机探针 |
| [redact-browser-artifacts.py](verify/redact-browser-artifacts.py) | 清理浏览器验收产物中的敏感信息；由集成入口调用。 | Python 3；输入为浏览器验收产物目录 |
| [platform-static.ps1](verify/platform-static.ps1) | 平台基础设施验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。 | Python 3.14、backend 开发依赖、Node.js 24、前端 npm 依赖、Docker CLI（含 Compose/Stack 配置解析） |
| [core-static.ps1](verify/core-static.ps1) | 共享基础设施验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。 | Python 3.14、backend 开发依赖、Node.js 24、前端 npm 依赖、Docker CLI（含 Compose/Stack 配置解析） |
| [core-integration.ps1](verify/core-integration.ps1) | 验证 MySQL 追加权限、Redis 数据丢失恢复、并发幂等和 Outbox 转发。 | Docker Compose、测试环境配置；在独立项目中创建数据服务并测试写入和清空 Redis |
| [accounts-static.ps1](verify/accounts-static.ps1) | 账号与门户身份验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。 | Python 3.14、backend 开发依赖、Node.js 24、前端 npm 依赖、Docker CLI（含 Compose/Stack 配置解析） |
| [accounts-integration.ps1](verify/accounts-integration.ps1) | 检查账号表、事件追加权限和门户身份，并调用三个门户的浏览器测试。 | 浏览器场景或 npm 命令缺失，运行前立即报错 |
| [courses-static.ps1](verify/courses-static.ps1) | 课程与选课验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。 | Python 3.14、backend 开发依赖、Node.js 24、前端 npm 依赖、Docker CLI（含 Compose/Stack 配置解析） |
| [courses-integration.ps1](verify/courses-integration.ps1) | 启动独立 Compose 环境并验证课程相关 MySQL 表。 | Docker Compose、测试环境配置；启动独立服务并检查课程相关数据库表 |
| [governance-static.ps1](verify/governance-static.ps1) | 运行时目录与配额治理验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。 | Python 3.14、backend 开发依赖、Node.js 24、前端 npm 依赖、Docker CLI（含 Compose/Stack 配置解析） |
| [governance-integration.ps1](verify/governance-integration.ps1) | 验证治理表、默认数据、维护任务及 OpenAPI。 | Docker Compose、测试环境配置；创建治理默认数据并检查表、维护任务和 OpenAPI |
| [templates-static.ps1](verify/templates-static.ps1) | 实验模板与附件扫描验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。 | Python 3.14、backend 开发依赖、Node.js 24、前端 npm 依赖、Docker CLI（含 Compose/Stack 配置解析） |
| [templates-integration.ps1](verify/templates-integration.ps1) | 检查模板表、MinIO 策略、ClamAV 和附件拒绝链，再调用教师与管理端浏览器测试。 | 浏览器场景或 npm 命令缺失，运行前立即报错 |
| [publications-static.ps1](verify/publications-static.ps1) | 实验发布与个人任务验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。 | Python 3.14、backend 开发依赖、Node.js 24、前端 npm 依赖、Docker CLI（含 Compose/Stack 配置解析） |
| [publications-integration.ps1](verify/publications-integration.ps1) | 检查发布表、Celery 队列与 OpenAPI，准备发布数据并调用三个门户的浏览器测试。 | 浏览器场景或 npm 命令缺失，运行前立即报错 |
| [provisioning-static.ps1](verify/provisioning-static.ps1) | 实验装载与模拟运行时验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。 | Python 3.14、backend 开发依赖、Node.js 24、前端 npm 依赖、Docker CLI（含 Compose/Stack 配置解析） |
| [provisioning-integration.ps1](verify/provisioning-integration.ps1) | 检查装载表和后台服务，准备模拟运行时数据并调用三个门户的浏览器测试。 | 浏览器场景或 npm 命令缺失，运行前立即报错 |
| [workspaces-static.ps1](verify/workspaces-static.ps1) | 工作区与执行生命周期验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。 | Python 3.14、backend 开发依赖、Node.js 24、前端 npm 依赖、Docker CLI（含 Compose/Stack 配置解析） |
| [workspaces-integration.ps1](verify/workspaces-integration.ps1) | 准备工作区会话测试数据，检查门户健康接口并调用工作区浏览器测试。 | 浏览器场景或 npm 命令缺失，运行前立即报错 |
| [reports-static.ps1](verify/reports-static.ps1) | 报告与成果验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。 | Python 3.14、backend 开发依赖、Node.js 24、前端 npm 依赖、Docker CLI（含 Compose/Stack 配置解析） |
| [reports-integration.ps1](verify/reports-integration.ps1) | 准备报告测试数据，检查服务健康接口并调用报告浏览器测试。 | 浏览器场景或 npm 命令缺失，运行前立即报错 |
| [reviews-static.ps1](verify/reviews-static.ps1) | 教师审核与自动检查验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。 | Python 3.14、backend 开发依赖、Node.js 24、前端 npm 依赖、Docker CLI（含 Compose/Stack 配置解析） |
| [reviews-integration.ps1](verify/reviews-integration.ps1) | 准备审核、自动检查和相似度数据，并调用审核浏览器测试。 | 浏览器场景或 npm 命令缺失，运行前立即报错 |
| [archives-static.ps1](verify/archives-static.ps1) | 归档与资源回收验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。 | Python 3.14、backend 开发依赖、Node.js 24、前端 npm 依赖、Docker CLI（含 Compose/Stack 配置解析） |
| [archives-integration.ps1](verify/archives-integration.ps1) | 准备归档测试数据并调用归档浏览器测试。 | 浏览器场景或 npm 命令缺失，运行前立即报错 |
| [agents-static.ps1](verify/agents-static.ps1) | 受控智能助手验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。 | Python 3.14、backend 开发依赖、Node.js 24、前端 npm 依赖、Docker CLI（含 Compose/Stack 配置解析） |
| [agents-integration.ps1](verify/agents-integration.ps1) | 准备智能助手配置和测试数据，并调用助手浏览器测试。 | 浏览器场景或 npm 命令缺失，运行前立即报错 |

历史累计静态门禁保留各自的检查组合和版本输入，不能把名称对应的开发模块理解为唯一测试范围。它们可能导出 OpenAPI 并更新前端类型；本轮验证使用上述后端入口和 npm 命令。

### 缺少的浏览器验收材料

当前仓库仅有 `frontend/e2e/analytics-notifications.spec.ts`。以下脚本来自早期验收流程，依赖的场景已不在当前源码中。它们已添加执行前检查；不能将这轮重命名视为恢复或通过这些业务验收。

| 入口 | 需要恢复 |
| --- | --- |
| `accounts-integration.ps1` | `test:e2e:student`、`test:e2e:teacher`、`test:e2e:admin` npm 命令 |
| `agents-integration.ps1` | `frontend/e2e/agents.spec.ts` |
| `archives-integration.ps1` | `frontend/e2e/archives.spec.ts` |
| `portal-entry.ps1` | `test:e2e:student`、`test:e2e:teacher`、`test:e2e:admin` npm 命令 |
| `provisioning-integration.ps1` | `frontend/e2e/provisioning.spec.ts` |
| `publications-integration.ps1` | `frontend/e2e/publications.spec.ts` |
| `real-workspace-integration.ps1` | `frontend/e2e/real-workspace.spec.ts` |
| `reports-integration.ps1` | `frontend/e2e/reports.spec.ts` |
| `reviews-integration.ps1` | `frontend/e2e/reviews.spec.ts` |
| `templates-integration.ps1` | `frontend/e2e/templates.spec.ts` |
| `workbench-integration.ps1` | `frontend/e2e/workbench-assistant.spec.ts`, `frontend/e2e/workbench-journey.spec.ts`, `frontend/e2e/workspaces.spec.ts` |
| `workspaces-integration.ps1` | `frontend/e2e/workspaces.spec.ts` |

## 部署

| 入口 | 用途 |
| --- | --- |
| [label-swarm-nodes.ps1](deploy/label-swarm-nodes.ps1) | 为已加入 Swarm 的三个管理节点分配服务角色标签。 |
| [bootstrap-local-swarm.ps1](deploy/bootstrap-local-swarm.ps1) | 准备单节点 Swarm 适配器测试环境；初始化必须显式指定参数。 |
| [deploy-swarm.ps1](deploy/deploy-swarm.ps1) | 检查环境变量、外部配置和密钥，部署指定版本的 Swarm 服务栈。 |
| [rollback-swarm-service.ps1](deploy/rollback-swarm-service.ps1) | 请求回滚指定 Swarm 服务，恢复情况需继续检查。 |
| [collect-swarm-evidence.ps1](deploy/collect-swarm-evidence.ps1) | 收集服务栈、节点与运行时网络的原始状态输出，仅留本地。 |
| [promote-workspace-image.ps1](deploy/promote-workspace-image.ps1) | 按已通过的真实工作区证据晋级镜像，保留 Registry digest 和回滚清单。 |

部署脚本会更改目标环境。集成验收需要可丢弃的测试库；不要在日常数据上执行重置、种子或资源回收命令。Swarm 部署及 Registry 晋级仍需在目标环境验收。

旧入口与现入口的完整对应见 [命名约定与迁移表](../docs/naming-conventions.md)。
