> 历史命令说明（2026-10-30）：本文保留原开发阶段编号及当时执行记录。当前脚本、管理命令和 Compose 配置档已按功能重命名，执行前请查看[现入口迁移表](../../naming-conventions.md)；原命令不作为当前可用性证明。

# 课程助手 agents 受控 Agent 出口记录

阶段：课程助手 本地 Compose + 受控本地 Agent 适配器

日期：2026-09-24

## 范围与边界

- 在既有 `apps.agents` 边界内新增 Agent profile、课程知识库/来源版本/摄取、Prompt、会话/消息、检索引用、工具策略/调用/审批、评测和反馈事实模型及迁移。
- CourseAgentProfile 使用 `DRAFT -> EVALUATING -> ACTIVE -> RETIRED` 状态机；同课程 ACTIVE 通过 MySQL 可执行的生成列唯一约束和服务层行锁共同保证；会话冻结 profile、Prompt、knowledge、tool-policy、model route 和预算版本。
- KnowledgeRetriever 交付可替换接口和确定性关键词基线；索引仅为可重建派生数据，检索前后重新校验课程、来源版本、audience、enrollment、task/workspace scope。
- ModelGateway 和 ToolExecutor 只接入受控本地适配器；LOW/MEDIUM/HIGH/FORBIDDEN 风险、审批有效期、参数 digest、输出上限、脱敏和终态阻断均在执行端复核。
- 评测固定平台强制用例和完整版本快照，未通过门禁的 profile 不得激活；反馈进入待分析队列，不自动成为训练数据。
- user-web、teacher-web、admin-web 增加 课程助手 Agent 页面、引用/无来源降级、工具审批、反馈、报告确认、课程配置、评测、策略和聚合指标；不暴露敏感上下文。
- 不实现真实外部模型、向量/混合检索、真实 Swarm/HA、生产容量或故障恢复验收；这些保持在后续真实环境阶段。

## 本地证据

- `Django check`：通过；`makemigrations --check --dry-run`：通过（No changes detected）。
- 后端 Ruff：通过；后端全量 pytest：`179 passed`；课程助手 定向测试：`6 passed`。
- OpenAPI revision：`v2-p12`；`manage.py spectacular --validate`：`Errors: 0`，保留 11 个既有 enum naming warnings；`frontend/openapi.json` 与 TypeScript schema 已同步生成。
- 前端 `npm run typecheck`：通过；ESLint：通过；Vitest：`23 passed`；user-web、teacher-web、admin-web production build：通过。
- `docker compose -f docker-compose.dev.yml config --quiet`：通过；`git diff --check`：通过（仅 Git 的 LF/CRLF 提示）。
- `scripts/verify-p12-integration.ps1 -ProjectName edu-platform-p12-verify-20260924d`：通过并自动清理隔离环境；覆盖空 MySQL 迁移、应用最小权限、Redis、MinIO、ClamAV、MongoDB、Celery/Beat、Nginx -> Kong -> Django、容器 OpenAPI、账号与门户身份-课程助手 种子和健康检查。
- 课程助手 三门户 Playwright：`3 passed`；覆盖 user 课程 Agent 异步引用会话、teacher profile/知识库/评测/反馈范围、admin 路由/工具策略/强制评测/聚合用量，并验证 1440px、920px、390px 响应式无横向溢出。
- 集成验证首次发现的 MySQL Agent 表授权缺口和条件唯一约束兼容性问题已修复；最终空库迁移和 课程助手 seed 均通过。

## 双门禁与出口

开发环境：本地 Compose + 受控本地 Agent/模型/工具适配器。

本地门禁：通过。

真实环境门禁：待验收。

真实环境阻塞：真实模型网关凭据与路由、真实工具运行时和沙箱、真实对象存储/扫描服务、Swarm/HA 调度与故障转移、生产容量/性能/压测、生产回滚、RPO/RTO、跨区域恢复和外部依赖故障证据尚未在真实环境验证。

出口结论：**本地通过（真实环境待验收）**。

该结论仅表示 课程助手 本地 Definition of Done 已满足并允许进入后续本地阶段，不代表真实模型、真实 Runtime、Swarm、HA、生产就绪或正式通过。
