# 命名约定与入口迁移

2026-11-02：当前操作入口、业务显示名称、测试标识和文档文件名按功能命名。脚本按 `scripts/dev/`（开发）、`scripts/verify/`（验证）、`scripts/deploy/`（部署）分类，文件名使用小写单词和连字符；Python 模块、Django 命令使用下划线。

## 当前入口

- 日常运行见 [项目说明](../README.md)，完整脚本用途、依赖及缺失材料见 [脚本索引](../scripts/README.md)。
- Compose 配置档 `p14` 已改为 `runtime`；例如 `docker compose --profile runtime up -d --no-build`。项目、镜像及持久卷名称不随本轮入口整理变更。
- Django 种子命令只适用于可丢弃的 local/integration/test 环境。`seed_simulated_experiment` 初始化模拟实验环境，`seed_provisioning_e2e` 保留为兼容别名。
- `python manage.py rename_seed_labels` 通过事务和 CAS 将旧种子数据的显示名称改成业务名称，保留主键、关系和稳定查找键；重复执行不再修改数据。相关种子入口也会在查找数据前执行更名。若新旧名称发生唯一约束冲突，整个更名事务回滚，需先核对冲突记录。

## 保留的历史或兼容标识

以下项目有现存数据或证据依赖，不能当成普通描述直接替换：

- 数据库迁移文件中的 `p13`、`t07` 和迁移依赖：已运行数据库记录了这些迁移名。
- 演示数据的 `P03-DEMO-001` 等稳定查找键、对象存储路径、运行环境配置引用、账号标识和幂等标识：保留以免种子失去幂等性、丢失对象或产生重复数据。它们不再用于解释业务用途。显示名称由独立更名命令更新。
- 镜像 label 中的 `p16-b` 工作区协议版本、`p13-v1` 分析投影版本、`APP_VERSION`/`OPENAPI_REVISION`：它们是兼容或发布版本，不是当前功能说明。
- 历史规划和执行记录的文件名、说明按业务命名，并同步修正文档链接。原始命令、迁移名、证据输出中的兼容标识以及日期和执行结果保留，不能将更名视为重新验收。
- 现有 `.env` 中 `P10_AUTO_CHECK_MAX_ATTEMPTS`、`P06_PUBLICATION_SYNC_LIMIT`、`P06_PUBLICATION_CHUNK_SIZE` 仍可作为旧环境变量回退；新配置分别使用 `AUTO_CHECK_MAX_ATTEMPTS`、`PUBLICATION_SYNC_LIMIT`、`PUBLICATION_CHUNK_SIZE`。测试账号密码改用 `E2E_SEED_PASSWORD`，账号种子仍接受旧的 `P02_E2E_PASSWORD`。若新旧同时设置，以新名称为准。
- 真实 Docker 审核测试使用 `LOCAL_DOCKER_INTEGRATION=1`，仍接受旧的 `T10_DOCKER_INTEGRATION` 开关。

## 文件入口对应

旧路径只用于查阅历史；执行应使用右列入口。历史原始输出中的旧命令没有重新运行。

| 旧路径 | 当前路径 |
| --- | --- |
| `scripts/dev-up.sh` | [scripts/dev/start.sh](../scripts/dev/start.sh) |
| `scripts/dev-down.sh` | [scripts/dev/stop.sh](../scripts/dev/stop.sh) |
| `scripts/reset-p00-local-data.ps1` | [scripts/dev/reset-local-data.ps1](../scripts/dev/reset-local-data.ps1) |
| `scripts/export-openapi.ps1` | [scripts/dev/export-openapi.ps1](../scripts/dev/export-openapi.ps1) |
| `scripts/check-lock.sh` | [scripts/verify/dependency-lock.sh](../scripts/verify/dependency-lock.sh) |
| `scripts/bootstrap-swarm.ps1` | [scripts/deploy/label-swarm-nodes.ps1](../scripts/deploy/label-swarm-nodes.ps1) |
| `scripts/p14-bootstrap-swarm.ps1` | [scripts/deploy/bootstrap-local-swarm.ps1](../scripts/deploy/bootstrap-local-swarm.ps1) |
| `scripts/p14-collect-evidence.ps1` | [scripts/deploy/collect-swarm-evidence.ps1](../scripts/deploy/collect-swarm-evidence.ps1) |
| `scripts/p14-deploy.ps1` | [scripts/deploy/deploy-swarm.ps1](../scripts/deploy/deploy-swarm.ps1) |
| `scripts/p14-rollback.ps1` | [scripts/deploy/rollback-swarm-service.ps1](../scripts/deploy/rollback-swarm-service.ps1) |
| `scripts/p14-runtime-smoke.py` | [scripts/verify/swarm-runtime-smoke.py](../scripts/verify/swarm-runtime-smoke.py) |
| `scripts/p16-promote-image.ps1` | [scripts/deploy/promote-workspace-image.ps1](../scripts/deploy/promote-workspace-image.ps1) |
| `scripts/t10-local-runtime-smoke.py` | [scripts/verify/local-runtime-smoke.py](../scripts/verify/local-runtime-smoke.py) |
| `scripts/verify-backend-local.ps1` | [scripts/verify/backend-local.ps1](../scripts/verify/backend-local.ps1) |
| `scripts/redact-playwright-artifacts.py` | [scripts/verify/redact-browser-artifacts.py](../scripts/verify/redact-browser-artifacts.py) |
| `scripts/verify-p00-entry.ps1` | [scripts/verify/portal-entry.ps1](../scripts/verify/portal-entry.ps1) |
| `scripts/verify-p13-a.ps1` | [scripts/verify/analytics-notifications-static.ps1](../scripts/verify/analytics-notifications-static.ps1) |
| `scripts/verify-p13-b.ps1` | [scripts/verify/integrations-static.ps1](../scripts/verify/integrations-static.ps1) |
| `scripts/verify-p13-c.ps1` | [scripts/verify/operations-static.ps1](../scripts/verify/operations-static.ps1) |
| `scripts/verify-p15.ps1` | [scripts/verify/workbench-static.ps1](../scripts/verify/workbench-static.ps1) |
| `scripts/verify-p15-integration.ps1` | [scripts/verify/workbench-integration.ps1](../scripts/verify/workbench-integration.ps1) |
| `scripts/verify-p16-b-docker.ps1` | [scripts/verify/workspace-image.ps1](../scripts/verify/workspace-image.ps1) |
| `scripts/verify-p16-integration.ps1` | [scripts/verify/real-workspace-integration.ps1](../scripts/verify/real-workspace-integration.ps1) |
| `frontend/e2e/p13.spec.ts` | [frontend/e2e/analytics-notifications.spec.ts](../frontend/e2e/analytics-notifications.spec.ts) |
| `scripts/verify-p00.ps1` | [scripts/verify/platform-static.ps1](../scripts/verify/platform-static.ps1) |
| `scripts/verify-p01.ps1` | [scripts/verify/core-static.ps1](../scripts/verify/core-static.ps1) |
| `scripts/verify-p01-integration.ps1` | [scripts/verify/core-integration.ps1](../scripts/verify/core-integration.ps1) |
| `scripts/verify-p02.ps1` | [scripts/verify/accounts-static.ps1](../scripts/verify/accounts-static.ps1) |
| `scripts/verify-p02-integration.ps1` | [scripts/verify/accounts-integration.ps1](../scripts/verify/accounts-integration.ps1) |
| `scripts/verify-p03.ps1` | [scripts/verify/courses-static.ps1](../scripts/verify/courses-static.ps1) |
| `scripts/verify-p03-integration.ps1` | [scripts/verify/courses-integration.ps1](../scripts/verify/courses-integration.ps1) |
| `scripts/verify-p04.ps1` | [scripts/verify/governance-static.ps1](../scripts/verify/governance-static.ps1) |
| `scripts/verify-p04-integration.ps1` | [scripts/verify/governance-integration.ps1](../scripts/verify/governance-integration.ps1) |
| `scripts/verify-p05.ps1` | [scripts/verify/templates-static.ps1](../scripts/verify/templates-static.ps1) |
| `scripts/verify-p05-integration.ps1` | [scripts/verify/templates-integration.ps1](../scripts/verify/templates-integration.ps1) |
| `scripts/verify-p06.ps1` | [scripts/verify/publications-static.ps1](../scripts/verify/publications-static.ps1) |
| `scripts/verify-p06-integration.ps1` | [scripts/verify/publications-integration.ps1](../scripts/verify/publications-integration.ps1) |
| `scripts/verify-p07.ps1` | [scripts/verify/provisioning-static.ps1](../scripts/verify/provisioning-static.ps1) |
| `scripts/verify-p07-integration.ps1` | [scripts/verify/provisioning-integration.ps1](../scripts/verify/provisioning-integration.ps1) |
| `scripts/verify-p08.ps1` | [scripts/verify/workspaces-static.ps1](../scripts/verify/workspaces-static.ps1) |
| `scripts/verify-p08-integration.ps1` | [scripts/verify/workspaces-integration.ps1](../scripts/verify/workspaces-integration.ps1) |
| `scripts/verify-p09.ps1` | [scripts/verify/reports-static.ps1](../scripts/verify/reports-static.ps1) |
| `scripts/verify-p09-integration.ps1` | [scripts/verify/reports-integration.ps1](../scripts/verify/reports-integration.ps1) |
| `scripts/verify-p10.ps1` | [scripts/verify/reviews-static.ps1](../scripts/verify/reviews-static.ps1) |
| `scripts/verify-p10-integration.ps1` | [scripts/verify/reviews-integration.ps1](../scripts/verify/reviews-integration.ps1) |
| `scripts/verify-p11.ps1` | [scripts/verify/archives-static.ps1](../scripts/verify/archives-static.ps1) |
| `scripts/verify-p11-integration.ps1` | [scripts/verify/archives-integration.ps1](../scripts/verify/archives-integration.ps1) |
| `scripts/verify-p12.ps1` | [scripts/verify/agents-static.ps1](../scripts/verify/agents-static.ps1) |
| `scripts/verify-p12-integration.ps1` | [scripts/verify/agents-integration.ps1](../scripts/verify/agents-integration.ps1) |
| `backend/education_experiment_platform/apps/accounts/management/commands/seed_p02_e2e.py` | [backend/apps/accounts/management/commands/seed_accounts_e2e.py](../backend/apps/accounts/management/commands/seed_accounts_e2e.py) |
| `backend/education_experiment_platform/apps/agents/management/commands/seed_p12_e2e.py` | [backend/apps/agents/management/commands/seed_agents_e2e.py](../backend/apps/agents/management/commands/seed_agents_e2e.py) |
| `backend/education_experiment_platform/apps/agents/tests/test_p12_agents.py` | [backend/apps/agents/tests/test_agents.py](../backend/apps/agents/tests/test_agents.py) |
| `backend/education_experiment_platform/apps/analytics/tests/test_p13_analytics.py` | [backend/apps/analytics/tests/test_analytics.py](../backend/apps/analytics/tests/test_analytics.py) |
| `backend/education_experiment_platform/apps/archives/management/commands/reconcile_p11.py` | [backend/apps/archives/management/commands/reconcile_archives.py](../backend/apps/archives/management/commands/reconcile_archives.py) |
| `backend/education_experiment_platform/apps/archives/management/commands/seed_p11_e2e.py` | [backend/apps/archives/management/commands/seed_archives_e2e.py](../backend/apps/archives/management/commands/seed_archives_e2e.py) |
| `backend/education_experiment_platform/apps/archives/tests/test_p11_archives.py` | [backend/apps/archives/tests/test_archives.py](../backend/apps/archives/tests/test_archives.py) |
| `backend/education_experiment_platform/apps/courses/management/commands/seed_p03_e2e.py` | [backend/apps/courses/management/commands/seed_courses_e2e.py](../backend/apps/courses/management/commands/seed_courses_e2e.py) |
| `backend/education_experiment_platform/apps/experiments/management/commands/seed_p06_e2e.py` | [backend/apps/experiments/management/commands/seed_publications_e2e.py](../backend/apps/experiments/management/commands/seed_publications_e2e.py) |
| `backend/education_experiment_platform/apps/experiments/management/commands/seed_p15_e2e.py` | [backend/apps/experiments/management/commands/seed_workbench_e2e.py](../backend/apps/experiments/management/commands/seed_workbench_e2e.py) |
| `backend/education_experiment_platform/apps/experiments/management/commands/seed_p16_e2e.py` | [backend/apps/experiments/management/commands/seed_real_workspace_e2e.py](../backend/apps/experiments/management/commands/seed_real_workspace_e2e.py) |
| `backend/education_experiment_platform/apps/experiments/management/commands/seed_t03_e2e.py` | [backend/apps/experiments/management/commands/seed_local_algorithm_e2e.py](../backend/apps/experiments/management/commands/seed_local_algorithm_e2e.py) |
| `backend/education_experiment_platform/apps/governance/management/commands/seed_p04_e2e.py` | [backend/apps/governance/management/commands/seed_governance_e2e.py](../backend/apps/governance/management/commands/seed_governance_e2e.py) |
| `backend/education_experiment_platform/apps/integrations/tests/test_p13_integrations.py` | [backend/apps/integrations/tests/test_integrations.py](../backend/apps/integrations/tests/test_integrations.py) |
| `backend/education_experiment_platform/apps/labtemplates/management/commands/seed_p05_e2e.py` | [backend/apps/labtemplates/management/commands/seed_templates_e2e.py](../backend/apps/labtemplates/management/commands/seed_templates_e2e.py) |
| `backend/education_experiment_platform/apps/labtemplates/management/commands/verify_p05_asset_rejection.py` | [backend/apps/labtemplates/management/commands/verify_template_asset_rejection.py](../backend/apps/labtemplates/management/commands/verify_template_asset_rejection.py) |
| `backend/education_experiment_platform/apps/notifications/tests/test_p13_notifications.py` | [backend/apps/notifications/tests/test_notifications.py](../backend/apps/notifications/tests/test_notifications.py) |
| `backend/education_experiment_platform/apps/provisioning/management/commands/seed_p07_e2e.py` | [backend/apps/provisioning/management/commands/seed_simulated_experiment.py](../backend/apps/provisioning/management/commands/seed_simulated_experiment.py) |
| `backend/education_experiment_platform/apps/reviews/management/commands/purge_p10_similarity_evidence.py` | [backend/apps/reviews/management/commands/purge_similarity_evidence.py](../backend/apps/reviews/management/commands/purge_similarity_evidence.py) |
| `backend/education_experiment_platform/apps/reviews/management/commands/seed_p10_e2e.py` | [backend/apps/reviews/management/commands/seed_reviews_e2e.py](../backend/apps/reviews/management/commands/seed_reviews_e2e.py) |
| `backend/education_experiment_platform/apps/reviews/tests/test_p10_reviews.py` | [backend/apps/reviews/tests/test_reviews.py](../backend/apps/reviews/tests/test_reviews.py) |
| `backend/education_experiment_platform/apps/workspaces/management/commands/p16_boundary.py` | [backend/apps/workspaces/management/commands/verify_workspace_token_boundary.py](../backend/apps/workspaces/management/commands/verify_workspace_token_boundary.py) |
| `backend/education_experiment_platform/apps/workspaces/management/commands/p16_cleanup.py` | [backend/apps/workspaces/management/commands/cleanup_workspace_e2e.py](../backend/apps/workspaces/management/commands/cleanup_workspace_e2e.py) |
| `backend/education_experiment_platform/apps/workspaces/management/commands/p16_evidence.py` | [backend/apps/workspaces/management/commands/collect_workspace_evidence.py](../backend/apps/workspaces/management/commands/collect_workspace_evidence.py) |
| `backend/education_experiment_platform/apps/workspaces/management/commands/seed_p08_e2e.py` | [backend/apps/workspaces/management/commands/seed_workspaces_e2e.py](../backend/apps/workspaces/management/commands/seed_workspaces_e2e.py) |
| `backend/education_experiment_platform/apps/workspaces/management/commands/seed_t05_e2e.py` | [backend/apps/workspaces/management/commands/seed_workspace_execution_e2e.py](../backend/apps/workspaces/management/commands/seed_workspace_execution_e2e.py) |

## Django 命令对应

从 `backend/` 运行 `python manage.py <命令>`，或通过选定 Compose 环境执行。

| 旧命令 | 当前命令 |
| --- | --- |
| `seed_p02_e2e` | `seed_accounts_e2e` |
| `seed_p03_e2e` | `seed_courses_e2e` |
| `seed_p04_e2e` | `seed_governance_e2e` |
| `seed_p05_e2e` | `seed_templates_e2e` |
| `verify_p05_asset_rejection` | `verify_template_asset_rejection` |
| `seed_p06_e2e` | `seed_publications_e2e` |
| `seed_p07_e2e` | `seed_simulated_experiment` |
| `seed_p08_e2e` | `seed_workspaces_e2e` |
| `seed_p10_e2e` | `seed_reviews_e2e` |
| `seed_p11_e2e` | `seed_archives_e2e` |
| `reconcile_p11` | `reconcile_archives` |
| `seed_p12_e2e` | `seed_agents_e2e` |
| `purge_p10_similarity_evidence` | `purge_similarity_evidence` |
| `seed_p15_e2e` | `seed_workbench_e2e` |
| `seed_p16_e2e` | `seed_real_workspace_e2e` |
| `seed_t03_e2e` | `seed_local_algorithm_e2e` |
| `seed_t05_e2e` | `seed_workspace_execution_e2e` |
| `p16_boundary` | `verify_workspace_token_boundary` |
| `p16_cleanup` | `cleanup_workspace_e2e` |
| `p16_evidence` | `collect_workspace_evidence` |

## 浏览器验收状态

12 个旧浏览器验收入口依赖当前缺失的场景或 npm 命令；已在任何容器操作前增加前置检查。场景清单见 [脚本索引](../scripts/README.md)。改名及语法通过不能替代真实浏览器业务验收。

## 本轮本地验证（2026-10-30）

- 75 个入口文件迁移后的路径存在，当前文档链接和调用引用检查通过；20 个功能命名的 Django 命令可被发现并加载。
- 后端完整入口：406 项测试通过、1 项跳过；Django 检查、迁移一致性、Ruff 和 mypy 通过。OpenAPI 无错误，保留一条现有的 `network_mode` 枚举重名警告。
- 前端类型检查、lint、57 项单测及三个门户构建通过；PowerShell 和 Shell 脚本语法检查通过。
- 12 个缺少材料的浏览器入口，以及依赖真实工作区浏览器场景的镜像晋级入口，均验证了在 Docker 调用前报告缺项。完整浏览器验收仍未恢复。
- 使用新入口的本地运行时回归通过：工作区创建幂等、编辑与快照读取、WebIDE/终端、五类判题结果和资源回收；测试工作区及附属资源均清理为零。
- 本地 `experimental-platform` 已加载重建镜像：18 个服务运行、6 个初始化任务正常退出；三个门户页面及健康接口共 6 项 HTTP 检查均返回 200。四个项目镜像保留四个标签，12 个第三方镜像及原有 10 个数据卷保留，SearXNG/Valkey 容器未替换。

以上结果仅覆盖本地检查范围。Swarm 部署、镜像 Registry 晋级和缺失的浏览器业务场景未在本轮验收。
