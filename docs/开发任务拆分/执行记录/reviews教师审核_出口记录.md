> 历史命令说明（2026-10-30）：本文保留原开发阶段编号及当时执行记录。当前脚本、管理命令和 Compose 配置档已按功能重命名，执行前请查看[现入口迁移表](../../naming-conventions.md)；原命令不作为当前可用性证明。

# 教师审核 reviews 教师审核与自动检查出口记录

阶段：教师审核 本地 Compose + FakeRuntime

日期：2026-09-24

## 范围与边界

- 在既有 `reviews` 应用内新增审核轮次、逐项评分投影与只追加事件、定位批注与修订、只追加审核决定、自动检查运行、相似度运行与候选证据模型，并完成迁移、约束、索引和运行账号最小权限。
- 审核轮次绑定 publication 冻结的 Rubric 版本和唯一冻结成果；报告提交与审核轮次、自动检查运行记录在同一事务内建立，外部执行在提交后进入 Celery。
- 决定入口锁定 Course、Task 和 Review，校验 TEACHING portal、有效 CourseStaff、`REVIEW_SUBMISSION` grant、If-Match、任务状态、自动检查状态和评分完整性，并原子追加决定、Audit、Outbox 和任务状态事实。
- APPROVE 仅推进任务到 `APPROVED`；REJECT 记录不可变决定后，将报告任务重新开放到 `REPORT_DRAFT`，再次提交生成新的冻结报告版本和审核轮次。
- 自动检查使用 实验环境装载 FakeRuntime 可替换执行器，支持重试、FailureRecord 和证据落库；检查和相似度均不能修改评分、决定或任务状态。
- 相似度限定同 publication 的各任务最新冻结 Markdown 报告，算法为 `char-5gram-jaccard-v1`，展示阈值为 `0.30`，证据保留期为 180 天，并以目标、候选和算法配置生成输入 digest 保证重放不重复。
- 教师审核 不实现 归档与回收 归档或实例销毁，不创建 分析与集成 通知投影，不接入 真实运行环境 真实 checker/runtime，也不实现成绩单或 OJ。

## 接口与前端交付

- TEACHING：课程审核队列、审核详情、逐项评分、批注创建/修订/撤销、通过/退回决定、相似度运行和候选查询。
- USER：本人各轮审核结果、Rubric 得分、批注、反馈和允许动作；退回后复用报告页面修改并重新提交。
- PLATFORM：仅提供待审、已决定、检查失败、相似度运行计数及 trace 的只读监管摘要，不返回报告正文、逐项评分或批注证据。
- teacher-web 新增课程审核队列和审核工作台；user-web 新增任务审核结果页；admin-web 新增只读审核监管页，并覆盖 loading、empty、error、权限/并发错误、异步检查和轮询降级。
- SSE 事件仅触发 Query 失效刷新；教师审核 写入包含 `user_id`、`course_id`、`task_id` 的审核 Outbox 事实，不提前实现通知投影。
- OpenAPI revision 固定为 `v2-p10`，生成的 TypeScript 类型和 review query keys 已同步。

## 本地证据

- `scripts/verify-p10.ps1`：通过。
- Django `check`：通过；`makemigrations --check --dry-run`：通过（No changes detected）。
- 后端 pytest：`164 passed`；其中 教师审核 service/API 测试 `13 passed`，覆盖 CAS、幂等重放、权限隔离、自动检查重试、相似度范围及只追加事实。
- Ruff：通过。
- OpenAPI 生成与校验：0 errors；保留 9 个枚举命名 warning。
- 前端 typecheck 与 ESLint：通过；Vitest：`21 passed`。
- user-web、teacher-web、admin-web production build：通过；Compose 配置校验通过。
- `scripts/verify-p10-integration.ps1 -ProjectName edu-platform-p10-final2`：通过；隔离项目验证完成后已自动清理容器、网络和数据卷。
- 隔离集成验证覆盖 MySQL migration 与最小权限、Redis、MinIO、ClamAV、MongoDB、Celery/FakeRuntime、Nginx -> Kong -> Django、容器 OpenAPI、账号与门户身份-教师审核 种子和健康检查。
- 教师审核 Playwright：`3 passed`；真实旅程完成教师评分与批注、自动检查、相似度、退回、学生重提、第二轮最终通过、教师课程范围队列及管理端只读监管。

## 双门禁与出口

开发环境：本地 Compose + FakeRuntime。

本地门禁：通过。

真实环境门禁：待验收。

真实环境阻塞：真实 checker/runtime、真实节点与 DNS/TLS、Swarm/HA、外部持久化与冗余、节点和依赖故障、生产容量与性能、恢复与 RPO/RTO、分析与集成 持久通知投影及生产回滚证据均未在 教师审核 本地环境验证。

出口结论：**本地通过（真实环境待验收）**。

该结论仅开放 归档与回收 的本地开发，不代表正式生产通过、分析与集成/真实运行环境 已完成或真实基础设施已经验收。
