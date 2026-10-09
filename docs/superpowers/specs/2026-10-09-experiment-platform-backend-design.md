# 实验平台后端重设计

- 日期：2026-10-09
- 状态：设计已确认，待制定实现计划
- 范围：实验模板、章节/任务、镜像生命周期、CPU/内存资源配额、本地测试到 Docker Swarm 迁移

## 1. 背景与目标

当前项目已有 `courses`、`labtemplates`、`experiments`、`governance`、`provisioning` 和 `workspaces` 模块，并已有模板版本、镜像资产、资源规格、运行适配器、任务发布、配额预留和工作区会话等基础能力。本次设计不另起一套平行系统，而是在现有模块边界上重组领域模型与服务流程。

目标：

1. 教师先准备并验证实验镜像，学生启动任务时只创建基于已发布镜像 digest 的运行实例。
2. 资源按照 CPU 与内存 request/limit 管理；模板创建不占用运行资源，学生启动时才预留。
3. 实验模板支持章节，每章包含多个任务；发布后内容与镜像、资源规格不可变。
4. 教师和学生都有当前学期、我的课程上下文。
5. 本地 Fake、Local Docker 与服务器 Docker Swarm 使用同一套业务服务、状态机和 API，只替换运行时适配器。
6. 旧数据和旧接口可分阶段迁移，不一次性破坏现有业务。

非目标：本阶段不实现前端页面、不立即删除旧模型、不迁移正在运行的容器或 Swarm Service。

## 2. 核心领域边界

```text
courses
├── Course / Enrollment / CourseStaff
├── AcademicTerm
└── 当前学期与我的课程查询

labtemplates
├── Template / TemplateVersion
├── TemplateChapter
└── TemplateTask

images（可先落在 labtemplates/governance，后续独立 app）
├── ExperimentImage
├── ImageBuildJob
└── 镜像 digest、扫描、验证与生命周期

governance
├── RuntimeAdapter
├── ResourceProfile
└── 平台容量、运行时能力和安全策略

experiments
├── TaskPublication
├── PublicationChapter / PublicationTask
├── ExperimentTask / StudentTaskProgress
└── 提交、评分与学生任务状态

provisioning
├── QuotaReservation
├── ProvisioningJob
├── ProvisioningInstance
└── RuntimeAdapterPort 实现

workspaces
└── WorkspaceSession（只负责访问会话，不负责创建容器）
```

模板版本、发布快照、镜像版本和学生运行实例必须是独立边界。

## 3. 学期与课程上下文

新增 `AcademicTerm`：

```text
public_id, code, name, starts_at, ends_at, status, is_current
```

`Course` 增加 `term_id`。同一时间最多一个当前学期；课程必须归属学期。教师“我的课程”使用 `CourseStaff`，学生“我的课程”使用有效 `Enrollment`，均支持 `term=current`。

建议接口：

```text
GET /api/v2/context
GET /api/v2/terms/current
GET /api/v2/teacher/courses?term=current
GET /api/v2/student/courses?term=current
```

`/context` 一次返回用户身份、当前学期、课程列表、课程角色和默认课程信息，减少前端初始化请求。

## 4. 模板、章节与任务

保留现有 `Template` / `TemplateVersion` 数据库表和迁移兼容性，提升其领域语义：

```text
Template
├── course_id
├── owner_id
├── name / description
├── status
└── current_version_id

TemplateVersion
├── template_id
├── version_no
├── status
├── image / resource_profile / execution_spec
└── spec_digest

TemplateChapter
├── template_version_id
├── title / description
├── learning_objectives
├── sort_order
└── status

TemplateTask
├── chapter_id
├── title / description / instructions
├── task_type
├── sort_order
├── execution_spec
├── resource_profile_id
├── submission_policy
└── grading_policy
```

章节和任务在模板版本内编辑；发布后不能原地修改，修改创建新版本。排序约束为同一版本内章节序号唯一、同一章节内任务序号唯一。

资源继承顺序：

```text
任务配置 > 章节默认配置 > 模板默认配置 > 平台默认配置
```

发布前必须至少有一个章节、每章至少一个任务、所有任务配置合法。

## 5. 镜像双模式

平台支持两种来源：

1. `BUILD_CONTEXT`：教师上传构建上下文和 Dockerfile，由后台异步构建。
2. `EXTERNAL_REFERENCE`：教师填写已有 registry/repository/tag，由后台解析、扫描和验证。

新增实验镜像关联模型：

```text
ExperimentImage
├── template_version_id
├── source_type
├── image_asset_id
├── requested_registry / repository / tag
├── resolved_digest
├── status / validation_status
├── build_config / validation_report
├── created_by / ready_at
```

继续使用 `governance.ImageAsset` 保存平台级镜像事实：registry、repository、display tag、digest、扫描状态、批准状态和风险等级。

镜像状态：

```text
DRAFT → PREPARING → SCANNING → VALIDATING → READY
```

失败状态：`BUILD_FAILED`、`SCAN_FAILED`、`VALIDATION_FAILED`；READY 镜像可变为 `RETIRED`。

进入 READY 必须满足：存在不可变 digest、registry 在允许范围、安全扫描通过、Swarm/Local Docker 启动探针通过、入口命令和端口有效、与运行时适配器兼容。

教师侧构建/验证为异步流程；学生请求不构建镜像、不显式 pull、不使用 tag，只使用发布快照中的：

```text
registry/repository@sha256:<digest>
```

Swarm 节点是否因本地不存在镜像而从 registry 获取，属于基础设施层；生产环境必须通过 registry 认证、镜像缓存或预热降低该风险。应用层不得在学生请求内主动 pull。

## 6. 资源模型

扩展现有 `ResourceProfile`：

```text
cpu_request_millicores
cpu_limit_millicores
memory_request_mb
memory_limit_mb
storage_request_mb
max_runtime_minutes
max_concurrency
```

约束：`0 < request <= limit`。模板创建不扣减运行资源；镜像构建/验证使用构建配额；学生启动任务时创建 `QuotaReservation`：

```text
runtime_adapter_id, course_id, task_id, student_id,
cpu_millicores, memory_mb, instance_count,
status, reserved_at, expires_at, released_at
```

预留状态：`ACTIVE`、`RELEASED`、`EXPIRED`、`COMPENSATING`。Swarm 创建成功后绑定运行实例；失败、停止、销毁和过期均幂等释放。资源容量操作必须有预留记录，不能只改可用容量字段。

## 7. 发布与学生运行实例

现有 `TaskPublication` 继续作为面向学生的发布聚合，并补充不可变快照：

```text
PublicationChapter
├── publication_id
├── source_chapter_id
├── title / sort_order
└── snapshot

PublicationTask
├── publication_chapter_id
├── source_task_id
├── title / sort_order
├── image_digest
├── resource_snapshot
└── execution_snapshot
```

发布必须冻结章节、任务、image digest、资源规格、执行配置、网络策略和评分规则。

学生启动流程：

```text
校验课程/发布/任务/学生权限
→ 锁定任务进度
→ 读取发布快照 image_digest
→ 检查已有 ACTIVE 实例
→ 创建资源预留
→ 创建 ProvisioningJob
→ 异步创建运行实例
→ 创建 WorkspaceSession
```

同一学生同一任务默认一个 ACTIVE 实例。`WorkspaceSession` 只负责访问令牌、能力和会话，不负责创建容器。

## 8. API 设计

新增 `/api/v2`，旧接口通过兼容适配器保留。

教师：

```text
POST   /teacher/courses/{course_id}/templates
GET    /teacher/courses/{course_id}/templates
GET    /teacher/templates/{template_id}
POST   /teacher/template-versions/{version_id}/chapters
POST   /teacher/chapters/{chapter_id}/tasks
POST   /teacher/chapters/{chapter_id}/tasks/reorder
POST   /teacher/template-versions/{version_id}/images
POST   /teacher/experiment-images/{image_id}/prepare
POST   /teacher/template-versions/{version_id}/precheck
POST   /teacher/template-versions/{version_id}/publish
```

学生：

```text
GET  /student/courses
GET  /student/courses/{course_id}/experiments
GET  /student/publications/{publication_id}
GET  /student/publications/{publication_id}/progress
POST /student/tasks/{task_id}/runtime
GET  /student/task-runtimes/{runtime_id}
POST /student/task-runtimes/{runtime_id}/restart
POST /student/task-runtimes/{runtime_id}/stop
```

学生不可提交或覆盖 image、digest、CPU、内存、runtime adapter 等发布字段。

## 9. 服务层与运行时适配器

应用服务：

```text
TemplateApplicationService
ImageApplicationService
PublicationApplicationService
RuntimeApplicationService
ResourceAdmissionService
```

所有服务通过 `RuntimeAdapterPort` 调用外部运行时：

```python
class RuntimeAdapterPort(Protocol):
    def build_image(self, request): ...
    def resolve_image(self, request): ...
    def validate_image(self, request): ...
    def create_runtime(self, request): ...
    def inspect_runtime(self, runtime_id): ...
    def stop_runtime(self, runtime_id): ...
    def destroy_runtime(self, runtime_id): ...
```

实现：

```text
FakeRuntimeAdapter
DockerLocalAdapter
DockerSwarmAdapter
```

业务服务不直接依赖 Docker SDK。数据库事务和 Docker 操作通过异步 job + 补偿机制衔接；孤儿 Service 通过 labels 对账并进入受控清理流程。

## 10. 三种运行模式

### Fake

用于单元测试、CI 和无 Docker 环境开发。模拟镜像构建、验证、资源容量和运行实例，但仍写入真实业务状态和预留记录；可注入资源不足、镜像失败、Service 创建失败。

### Local Docker

用于本地真实容器联调。使用 Docker Engine 创建普通 Container，使用与 Swarm 相同的资源规格、镜像 digest、任务状态和工作区流程；不用于生产。

### Docker Swarm

用于测试服务器、预发布和生产。创建 Swarm Service，使用 reservations/limits、node label、registry 和镜像预热策略。

配置由环境变量驱动：

```text
RUNTIME_MODE=fake|local|swarm
RUNTIME_ADAPTER_CODE=...
LOCAL_DOCKER_HOST=...
SWARM_MANAGER_URL=...
SWARM_REGISTRY=...
SWARM_NETWORK=...
SWARM_NODE_LABEL=...
```

本地 Compose 中 Docker socket 只挂载给 `runtime-worker`，不挂载给 API 和普通 Celery worker。

## 11. 迁移策略

### 阶段一：新增模型与服务

新增 AcademicTerm、章节/任务、ExperimentImage、ImageBuildJob、发布章节/任务和学生任务进度；补充资源预留字段。不改变旧 API 行为。

### 阶段二：历史数据转换

旧模板自动生成默认章节“实验内容”和默认任务“实验任务”；旧镜像 tag 解析为 digest，无法解析的标记为 `MIGRATION_REQUIRED`；旧资源字段转换为默认资源快照。迁移脚本必须幂等、可重复、支持 dry-run、分批执行并记录失败。

### 阶段三：双读

新数据优先；无新数据时由 Legacy Adapter 组装默认章节/任务。旧接口不直接读取新表内部细节。

### 阶段四：双写

新接口写新模型，必要时同步旧字段；旧接口通过新服务和适配器写入，不再直接修改旧字段。双写必须在同一事务中完成。

### 阶段五：切换与清理

迁移率和镜像验证达标后切换前端；停止旧字段写入；保留只读兼容期；确认运行实例、资源释放和 Swarm 对账稳定后再清理旧字段。

本地到服务器迁移不迁移容器 ID、Service ID、网络 ID、临时 endpoint、资源预留和 workspace session。可迁移课程、模板、章节、任务、发布、镜像元数据、评分和历史提交。镜像推送到服务器 registry 后必须重新解析 digest 并重新验证。

## 12. 错误码与用户体验

统一错误码包括：

```text
CURRENT_TERM_NOT_CONFIGURED
COURSE_NOT_ACCESSIBLE
TEMPLATE_VERSION_LOCKED
IMAGE_NOT_READY
IMAGE_DIGEST_REQUIRED
IMAGE_SCAN_FAILED
IMAGE_VALIDATION_FAILED
RESOURCE_PROFILE_INVALID
RESOURCE_LIMIT_EXCEEDED
RESOURCE_CAPACITY_INSUFFICIENT
TASK_RUNTIME_ALREADY_ACTIVE
SWARM_SERVICE_CREATE_FAILED
RUNTIME_EXPIRED
```

资源不足返回 requested、available 和 retry_after_seconds；教师可以看到镜像、资源和发布检查结果；学生可以看到章节进度、运行状态、过期时间、失败原因和重试动作。

## 13. 测试与验收

单元测试覆盖资源继承、request/limit、tag-to-digest、发布前检查、权限、排序、预留幂等释放和重复启动。

集成测试覆盖两类镜像来源、发布冻结、Swarm 创建成功/失败、资源补偿、孤儿 Service 对账、任务过期销毁和课程关闭。

API 测试覆盖教师课程边界、学生课程边界、已发布可见性、旧接口兼容和幂等响应。

运行时验收顺序：

```text
Fake Runtime → Local Docker → 测试 Swarm → 生产 Swarm
```

四种环境共享 Django 代码、数据库模型、API、应用服务、状态机和资源预留逻辑，仅替换 RuntimeAdapter、Docker 连接、registry、容量和网络约束。

## 14. 实施顺序

1. 提取/稳定 RuntimeAdapterPort 和 FakeRuntimeAdapter。
2. 新增 AcademicTerm、模板章节/任务和发布快照模型。
3. 补充镜像构建/外部镜像验证工作流，并固化 digest。
4. 补充资源 profile 校验、预留与释放的统一服务。
5. 新增教师和学生 v2 API。
6. 接入 DockerLocalAdapter。
7. 接入 DockerSwarmAdapter 和 registry/节点预热检查。
8. 实施历史数据迁移、双读和双写。
9. 运行 Fake、Local Docker、测试 Swarm 验收。
10. 前端切换后进入旧模型只读和清理阶段。

## 15. 设计决策

- 教师可以构建镜像，也可以引用已有镜像；两者最终必须进入统一 READY 状态。
- 发布版本固定 image digest，tag 仅用于展示和追踪。
- 学生启动任务只创建运行实例，不构建镜像、不主动 pull。
- CPU/内存资源按 request/limit 管理，创建模板不占用运行容量。
- 章节和任务属于模板版本，发布后生成不可变快照。
- 本地 Fake/Local Docker/服务器 Swarm 共享业务流程，通过适配器切换。
- 旧模型和旧接口通过迁移、双读、双写和兼容层平滑退出。
