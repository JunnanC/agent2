# T10 / P14-L 本地 Docker 真运行时出口记录

## 阶段信息

```text
阶段：T10 / P14-L
阶段名称：本地 Docker 真运行时
执行日期：2026-09-27
执行人或任务线程：Codex 当前任务线程
开发环境：本地 Docker Desktop / Compose；Python 3.14；Docker Engine 28.5.1
出口状态：本地通过（真实环境待验收）
```

## 开始条件

```text
上一阶段出口记录：documents/本地修改/修改任务1-容器本地真实适配/执行记录/T09_P13_观测与运维_出口记录.md
上一阶段状态：本地通过（真实环境待验收）
本阶段输入 ID：task_id、student_id、runtime_adapter_id、config_ref、resource_profile_id、execution_run_id、auto_check_run_id、trace_id
本阶段输入 migration head：沿用 T09；T10 未新增 migration
本阶段输入 OpenAPI revision：v2-p14
```

## 本次修改

```text
修改目标：实现真实单机 DockerLocalAdapter、学生工作区容器、一次性 Python judge、受管资源回收、本地算法工作区镜像及真实 Docker/报告审核 E2E。
变更文件：.env.example；docker-compose.dev.yml；backend/education_experiment_platform/education_experiment_platform/settings/base.py；apps/provisioning/adapters.py；apps/provisioning/tests/test_adapter_contract.py；apps/reviews/tests/test_p10_reviews.py
新增文件：runtime/algorithm-workspace/.dockerignore、Dockerfile、contract_server.py、README.md；scripts/t10-local-runtime-smoke.py；evidence/p14/local-20260927-t10/summary.json；本记录文件
删除文件：无
未修改但明确依赖的文件：P04-P13 的治理、模板执行规范、任务冻结、WorkspaceExecutionRun、报告证据、AutoCheckRun、归档补偿和观测契约；FakeRuntime 语义保持不变
```

## 数据库与配置

```text
新增或修改的 migration：无
本地实际 migration head：T10 无新增 migration；真实 Docker 报告审核集成测试完整应用全部 migration；makemigrations --check --dry-run 返回 No changes detected
数据不变量与约束：仅删除 edu.platform.managed=true 且 kind 匹配的资源；工作区创建按 idempotency digest 重放；配置变化触发幂等冲突；judge 只接受服务端生成的 python <entrypoint>；完整测试 payload/期望值不挂入 judge
新增环境变量：LOCAL_RUNTIME_MODE；DOCKER_SOCKET_GID（其余 LOCAL_RUNTIME_IMAGE、LOCAL_RUNTIME_NETWORK、LOCAL_DOCKER_HOST 沿用 T01）
环境变量是否写入 .env.example：是
镜像名称与 digest：edu-platform-algorithm-workspace:local；sha256:b4ffaa3665d3363b7ac3f312f372976b0efb1ce3d6fb759dc83b780267035f67
运行时网络名称：edu-platform-p14_runtime（internal bridge；工作区地址 tasks.<container_name>:8080）
```

## API 与前端

```text
新增或修改的 API：无；沿用 workspace execution、review auto-check、report/review 和 platform operations API
请求幂等键和 If-Match 规则：无变更；工作区底层使用既有 provisioning 幂等键；报告/审核继续使用既有 Idempotency-Key 和 If-Match/CAS
新增错误码：仅内部稳定码，包括 RUNTIME_COMMAND_NOT_ALLOWED、RUNTIME_NETWORK_NOT_ALLOWED、RUNTIME_MEMORY_EXCEEDED、RUNTIME_TIMEOUT、RUNTIME_RESOURCE_NOT_MANAGED、RUNTIME_*_CREATE/QUERY/DESTROY_FAILED
OpenAPI revision：v2-p14；spectacular validate 0 errors、14 个既有 enum naming warnings
前端页面或共享包：无 T10 新增改动；工作区入口继续使用外层实验草稿，运行时镜像只提供约定入口
loading/empty/error/403/409/412/异步状态：沿用 P05-P10 已验证状态机；T10 未修改公共 API 或前端状态契约
```

## Seed 与验证数据

```text
Seed 命令：无新增持久 seed；真实 Docker smoke 使用临时 RuntimeSpec；报告审核 E2E 使用 Django 测试数据库并在结束时销毁
课程 ID：测试运行时临时生成，未持久化
模板版本 ID：测试运行时临时生成，未持久化
任务 ID：t10-local-smoke（容器 smoke）及测试运行时临时 ULID（报告审核 E2E）
学生 ID：t10-student（容器 smoke）及测试运行时临时 ULID
教师 ID：报告审核 E2E 临时生成
运行时 adapter ID：config_ref=runtime/local-docker；driver=DOCKER_LOCAL
执行记录 ID：真实报告审核 E2E 临时生成 AutoCheckRun ULID，测试结束后销毁
```

## 测试证据

```text
数据库检查：Django system check 通过；完整 migration 在真实 Docker 报告审核测试中应用成功；makemigrations --check --dry-run 返回 No changes detected
后端测试命令与数量：py -3.14 -m pytest -q；234 passed、1 个显式 Docker 集成用例默认跳过、12 subtests passed；DockerLocalAdapter 契约专项 12 passed、2 subtests passed
前端测试命令与数量：T10 未修改前端；沿用 T09 前端门禁，未重复生成前端产物
OpenAPI 校验：manage.py spectacular --format openapi-json --validate；0 errors、14 个既有 enum naming warnings
Compose 配置校验：docker compose -f docker-compose.dev.yml config --quiet 通过；修复 runtime-reference deploy 缩进
安全/越权测试：非 root、read-only rootfs、cap_drop=ALL、no-new-privileges、pids=64、judge network=none、无宿主端口；非法命令/非 DENY_ALL 网络被拒绝；非 managed 容器拒绝删除；跨学生/跨课程访问由全量既有测试覆盖
幂等/并发测试：真实工作区同幂等键返回同一 external_id；双次 destroy 成功；并发竞态沿用既有 provisioning 补偿契约，未执行专门的真实 Docker 并发压测
失败/重试/补偿测试：真实错误输出、单用例超时、测试套件总超时、内存超限均得到稳定终态；创建失败卷清理和 judge finally 清理有单元覆盖；Engine outage/补偿由既有全量测试覆盖
Docker 或 Swarm 集成测试：Docker Engine 28.5.1 ping 通过；真实工作区 READY；/healthz、/webide/、/terminal/、/preview/ 均为 200；正确/错误/超时/内存超限通过；运行后 managed 容器和卷均为 0；Swarm HA 不属于 T10
Playwright 或完整业务 E2E：显式 T10_DOCKER_INTEGRATION=1 的 Django 集成测试通过：报告事实 -> 真实 Docker judge PASSED -> AutoCheckRun 审计事实 -> 教师 APPROVE；未新增 Playwright
证据目录：evidence/p14/local-20260927-t10/summary.json
```

## 结果与问题

```text
正常路径结果：DockerLocalAdapter 完成 preflight、镜像检查、internal network、工作区创建/健康探针/endpoint/销毁；工作区四个入口返回 200；真实算法正确用例 PASSED；完整报告审核链路通过
越权路径结果：只处理 managed labels；非 managed 容器不会删除；judge 无网络；无宿主端口；完整隐藏测试 payload 和期望值只留在 runtime-worker 侧比较，不挂入 judge 容器
状态冲突结果：同幂等键同规范重放成功；规范 digest 不一致返回 RUNTIME_IDEMPOTENCY_CONFLICT；公共业务 CAS/If-Match 无回归
资源限制结果：工作区 CPU 250m、内存 192MiB、pids 64；judge 独立 CPU/内存限制；48MiB OOM 用例得到 RESOURCE_EXCEEDED；单用例和套件总时限均得到 TIMEOUT
回收和对账结果：judge、stager、judge 临时卷在 finally 中删除；工作区双次销毁成功；真实 smoke 结束 managed workspaces=0、judge=0、volumes=0
日志、trace 和指标结果：真实报告审核 E2E 输出脱敏结构化 runtime.judge 日志并关联 trace/task/execution/resource；沿用 T09 指标
敏感信息泄漏检查：证据仅含版本、digest、状态、计数和安全布尔值；不含密码、Token、Cookie、签名 URL、完整源码或隐藏测试正文
已知限制：本地单机 Docker 不是生产/HA 验收；第一版只支持 Python 单文件和 token comparator；工作区页面是契约占位入口；未做真实 Docker 并发压测、UI Playwright、Swarm 节点故障/恢复与性能门禁
未解决阻塞：无 T10 本地代码阻塞；生产镜像仓库、digest 固定、overlay 网络、Swarm HA/恢复/容量/性能仍待 T11 真实环境验收
```

## 下一阶段交接

```text
下一阶段编号：T11 / P14-S
下一阶段名称：服务器真实适配
下一阶段必须使用的 ID：driver=DOCKER_SWARM、task_id、student_id、runtime_adapter_id、config_ref、resource_profile_id、execution_run_id、auto_check_run_id、trace_id
下一阶段必须使用的 API：既有 workspace execution、review auto-check、report/review、platform operations、archives reconcile/purge API；不改变业务 API
下一阶段必须使用的配置：私有镜像 registry+digest；Swarm overlay 网络；节点标签；Secrets/Configs；managed labels；资源限制；mTLS Docker Engine 配置
下一阶段必须先复核的风险：runtime-worker Docker 权限、服务幂等/回滚、overlay 隔离、judge hidden-tests 边界、TTL/孤儿回收、三 Manager quorum、节点故障恢复、容量和性能
下一阶段开始条件是否满足：是（仅本地通过；真实环境待验收）
```

## 结论

```text
本地门禁：通过
真实环境门禁：待验收
出口结论：本地通过（真实环境待验收）
```
