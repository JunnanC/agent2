# Edu Agent Platform 前端—后端对接指南

## 1. 文档定位

本文档面向前端整体重构与联调，描述当前后端已经提供的门户、认证、请求约定、核心数据对象、业务流程和 API 分组。

本文档不规定页面布局、视觉风格、组件库、动画、颜色、排版或具体渲染方式。前端可以自由组织页面，但必须遵守本文档的接口、权限、状态、并发和安全规则。

### 1.1 契约来源

- 运行时契约：后端 `GET /api/v2/schema`，由 `backend/education_experiment_platform/api_urls.py` 中的 `SpectacularAPIView` 提供。
- 导出脚本：`scripts/dev/export-openapi.ps1`；脚本会生成 `frontend/openapi.json` 并调用 `npm run generate:api` 更新前端类型。
- 基线文件：`frontend/openapi.json`。当前三端源码及此文件均存在；接口变更后仍须重新导出并同步生成类型，不能假设历史导出自动包含最新接口。
- 配置默认修订号：`settings/base.py` 中的 `OPENAPI_REVISION` 默认为 `v2-p15`，可由环境变量覆盖；OpenAPI 格式版本配置为 `3.0.3`。这些配置值不能证明后续改造已经完整反映在历史导出中。
- 历史导出曾包含 315 个 API 操作、342 个 schema；这不是当前工作树重新生成后的统计。源码已增加课程上下文、章节任务、课程镜像和学生运行时停止等接口，见本文及接口目录末尾的源码补充；当前完整数量须在依赖齐备后重新生成并核对。
- 若本文档与在线 schema 或后端实际响应不一致，以在线 schema 和实际响应为准，并记录差异后更新前端类型。

### 1.2 名词

| 名词 | 含义 |
| --- | --- |
| 用户门户 | 学生使用的 USER 门户 |
| 教师门户 | 教师使用的 TEACHING 门户 |
| 平台门户 | 平台管理员使用的 PLATFORM 门户 |
| 课程 | 一个学期中的教学课程实例 |
| 实验模板 | 教师维护的实验定义 |
| 模板版本 | 实验模板在某个时间点的运行规格 |
| 实验镜像 | 已治理、已扫描、可供运行时使用的 Docker 镜像 |
| 资源规格 | CPU、内存、磁盘、网络等运行时配额 |
| 实验发布 | 将模板版本以指定受众和时间窗口发布到课程 |
| 实验任务 | 学生针对某次实验发布生成的个人任务 |
| 工作区 | 学生任务对应的运行时容器/实例和持久化快照 |

## 2. API 基础

### 2.1 地址和门户

所有业务 API 使用 /api/v2 前缀。开发环境由网关根据 Host 注入门户上下文：

| Host | 后端门户 |
| --- | --- |
| student.localhost | USER |
| teacher.localhost | TEACHING |
| admin.localhost | PLATFORM |
| api.localhost | 集成 API 上下文 |

前端应通过对应门户 Host 调用 API，不要自行设置或伪造以下请求头：

- X-Portal
- X-Proxy-Context
- X-Auth-Context

这些头由 Kong/入口网关注入。直接访问 Django 服务、使用错误 Host 或绕过网关，会得到 PROXY_CONTEXT_UNTRUSTED、PORTAL_UNKNOWN 等错误。

开发环境示例：

~~~text
http://student.localhost:8080/api/v2
http://teacher.localhost:8080/api/v2
http://admin.localhost:8080/api/v2
~~~

端口以本地 ENTRY_PORT 配置为准；服务器部署时使用部署域名替换上述 Host。

### 2.2 健康检查和 schema

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /api/v2/health | 进程存活检查，返回版本和 OpenAPI 修订号 |
| GET | /api/v2/health/ready | MySQL 等依赖就绪检查 |
| GET | /api/v2/schema | 获取在线 OpenAPI schema |

健康检查不是业务登录接口；页面初始化不应把健康检查当作当前用户信息接口。

### 2.3 通用响应

单对象或命令类成功响应通常为：

~~~json
{
  "data": {},
  "meta": { "trace_id": "32位 trace id" }
}
~~~

列表响应通常为：

~~~json
{
  "data": [],
  "meta": {
    "page": 1,
    "page_size": 20,
    "total": 0,
    "trace_id": "32位 trace id"
  }
}
~~~

部分内容、治理和聚合接口的 meta 会包含更具体的字段，以 OpenAPI schema 为准。前端不要假设所有列表都支持同一种排序或 cursor 分页。

### 2.4 分页和查询

使用页码分页的列表接口支持：

~~~text
?page=1&page_size=20
~~~

- page 从 1 开始。
- page_size 范围为 1 到 100。
- 默认 page_size 为 20。
- 查询、筛选、状态等参数按具体接口 schema 传递。
- 收到 PAGINATION_INVALID 时不要继续递增重试，应修正参数。

## 3. 认证、会话和 CSRF

### 3.1 Cookie 会话

后端使用 Django session/cookie 认证，不使用前端保存的 Bearer access token 作为普通门户登录方式。浏览器请求必须保留 cookie：

~~~js
fetch(url, {
  credentials: "include",
  headers: { "Content-Type": "application/json" }
});
~~~

生产环境会话 cookie 为 Secure、HttpOnly、SameSite=Lax。不要把 sessionid 读取到 JavaScript，也不要把 cookie 内容写入日志。

### 3.2 登录流程

1. 前端先访问当前门户的 GET /api/v2/auth/csrf。
2. 后端通过响应设置 csrftoken cookie；响应体中的 data.csrf 仅表示 CSRF 已准备好，不是实际 token。
3. 从 csrftoken cookie 读取 token，并在需要 CSRF 的请求中发送 X-CSRFToken。
4. 调用 POST /api/v2/auth/login，请求体为 identifier、password。
5. 登录成功后保存响应中的 data 作为当前用户缓存，并继续使用浏览器 session cookie。
6. 登录、登出前后都应使用同一个门户 Host，不要跨 USER、TEACHING、PLATFORM 复用同一个门户 session。

CSRF 接口响应示例：

~~~json
{
  "data": { "csrf": "ready" },
  "meta": { "trace_id": "..." }
}
~~~

### 3.3 登出和会话失效

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/v2/auth/logout | 注销当前会话 |
| POST | /api/v2/auth/logout-all | 注销当前用户的全部会话 |
| GET | /api/v2/me | 获取当前门户中的当前用户 |

收到以下错误时，前端应清理当前用户缓存并跳转到当前门户登录流程：

- AUTH_REQUIRED
- SESSION_EXPIRED
- SESSION_PORTAL_MISMATCH

不同门户有不同空闲和绝对过期配置，前端不应自行推断精确过期时间；应以接口返回为准。

### 3.4 个人账户

| 能力 | API |
| --- | --- |
| 读取/修改个人资料 | GET/PATCH /api/v2/me |
| 修改密码 | POST /api/v2/me/password |
| 读取/更新身份认证资料 | GET/PUT /api/v2/me/verification |
| 读取 OIDC 绑定 | GET /api/v2/me/oidc-identities |
| 创建 OIDC 绑定 | POST /api/v2/me/oidc-identities |
| 解除 OIDC 绑定 | POST /api/v2/me/oidc-identities/{identity_id}/unlink |
| 查询通知偏好 | GET /api/v2/notification-preferences |
| 修改通知偏好 | PATCH /api/v2/notification-preferences |
| 查询通知 | GET /api/v2/notifications |
| 标记通知已读 | POST /api/v2/notifications/{notification_id}/read |

## 4. 请求头、并发和重试

### 4.1 基础请求头

业务请求建议统一携带：

~~~text
Content-Type: application/json
Accept: application/json
credentials: include
X-CSRFToken: <csrftoken cookie>
~~~

X-CSRFToken 对安全方法不是全部必需，但前端可以由请求层统一添加；GET 不应修改业务数据。

### 4.2 幂等键

除登录、登出、登出全部会话、集成 OAuth token 等少数例外，大多数 POST，以及以下 PUT，必须携带 Idempotency-Key：

- PUT /api/v2/tasks/{task_id}/report-draft
- PUT /api/v2/teaching/courses/{course_id}/reviews/{review_id}/criterion-scores

要求：

- 每个新的用户业务命令生成新的 key，建议使用 UUID。
- 因网络超时而重试同一个业务命令时，复用原 key，不要生成新 key。
- 请求体、用户、门户或 endpoint 与原 key 不同，会得到 IDEMPOTENCY_KEY_REUSED。
- 相同 key 的请求仍在执行时，会得到 IDEMPOTENCY_REQUEST_IN_PROGRESS；该错误可在短暂延迟后使用同一个 key 重试。
- 缺失 key 会得到 428 IDEMPOTENCY_KEY_REQUIRED。
- 不要因为页面重新渲染而重新提交带副作用的命令。

### 4.3 ETag 与 If-Match

需要修改已有资源时，后端通常要求乐观锁：

1. 从读取或写入响应保存 ETag，格式通常为 "<row_version>"。
2. 修改、状态迁移或撤销操作发送 If-Match: "<row_version>"。
3. 成功响应更新本地对象和新的 ETag。
4. 412 ROW_VERSION_CONFLICT 表示资源已被其他请求更新；前端应重新读取资源、合并或让用户确认后再提交。
5. 缺少 If-Match 会得到 428 PRECONDITION_REQUIRED；格式错误会得到 400 INVALID_PRECONDITION。

row_version 是数据字段，ETag 是响应头；两者通常对应，但请求更新应以响应头中的完整 ETag 为准。

### 4.4 Trace 与诊断

后端响应包含：

- X-Request-ID
- traceparent
- Server-Timing

业务响应的 meta.trace_id 或错误的 error.trace_id 也应保留。前端错误上报至少记录 URL、HTTP 方法、状态码、error.code、error.trace_id 和 X-Request-ID，但不得记录密码、session cookie、CSRF token、workspace token、secret 或完整文件内容。

## 5. 统一错误处理

错误响应统一形态：

~~~json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "面向用户的提示",
    "detail": {},
    "trace_id": "32位 trace id",
    "retryable": false
  }
}
~~~

处理原则：

- 使用 error.code 做业务分支。
- 使用 error.message 作为默认用户提示。
- error.detail 仅在确实需要字段级提示时解析；它不是稳定的全局 schema。
- error.trace_id 用于问题反馈和客服定位。
- 只有 retryable=true，或明确的 429/503 场景，才自动重试。
- 不要只根据 HTTP 状态码推断业务状态。

### 5.1 常见错误码

| 分类 | 错误码 | HTTP | 前端处理 |
| --- | --- | ---: | --- |
| 登录 | INVALID_CREDENTIALS | 401 | 显示登录失败，不自动重试密码 |
| 登录 | AUTH_REQUIRED / SESSION_EXPIRED | 401 | 清理用户状态，重新登录 |
| 门户 | SESSION_PORTAL_MISMATCH | 401 | 切换到正确门户会话 |
| 权限 | PORTAL_ACCESS_DENIED | 403 | 不显示当前门户不可用操作 |
| 资格 | TEACHER_QUALIFICATION_REQUIRED | 403 | 引导完成教师资格流程 |
| 平台 | PLATFORM_ACCESS_REQUIRED | 403 | 提示无平台管理员权限 |
| 安全 | CSRF_FAILED | 403 | 重新获取 CSRF cookie 后重试一次 |
| 参数 | VALIDATION_ERROR / PAGINATION_INVALID | 400 | 展示字段或查询参数错误 |
| 资源 | RESOURCE_NOT_FOUND | 404 | 刷新列表或显示资源不存在 |
| 状态 | STATE_CONFLICT、COURSE_STATE_CONFLICT、CONTENT_STATE_CONFLICT、TEMPLATE_STATE_CONFLICT、PUBLICATION_STATE_CONFLICT、TASK_STATE_CONFLICT、REPORT_STATE_CONFLICT | 409 | 重新读取状态并根据允许操作更新入口 |
| 并发 | ROW_VERSION_CONFLICT | 412 | 重新读取并处理冲突 |
| 前置条件 | PRECONDITION_REQUIRED / INVALID_PRECONDITION | 428/400 | 补充或修正 If-Match |
| 幂等 | IDEMPOTENCY_KEY_REQUIRED | 428 | 生成 key 后重新发起同一命令 |
| 幂等 | IDEMPOTENCY_KEY_REUSED | 422 | 不能复用到不同业务请求 |
| 幂等 | IDEMPOTENCY_REQUEST_IN_PROGRESS | 409 | 使用同一个 key 延迟重试 |
| 限流 | RATE_LIMITED | 429 | 根据提示等待，不连续点击 |
| 运行时 | RUNTIME_UNAVAILABLE | 503 | 按 retryable 和退避策略重试 |
| 发布 | PUBLICATION_VALIDATION_ERROR / PUBLICATION_PREREQUISITE_BLOCKED | 422/409 | 定位发布配置或先修条件 |
| 模板 | TEMPLATE_PRECHECK_FAILED / TEMPLATE_DIGEST_MISMATCH | 422/409 | 重新预检，不能忽略摘要差异 |
| 报告 | REPORT_SNAPSHOT_CONFLICT / REPORT_EXECUTION_CONFLICT | 412 | 先保存工作区或报告草稿，再刷新提交 |
| 评审 | AUTO_CHECK_PENDING / SIMILARITY_UNAVAILABLE | 409 | 等待后台分析或提示暂不支持 |

## 6. 门户上下文与用户角色

### 6.1 当前用户

GET /api/v2/me 返回 MeData：

~~~text
public_id
email
username
display_name
account_status
row_version
portal
eligible_portals[]
teacher_qualification
platform_admin_assignment
permissions[]
course_scopes[]
~~~

前端应以 portal、eligible_portals、permissions 和资格状态决定当前门户的可用能力，不要仅凭用户名或前端路由判断权限。

### 6.2 当前学期和我的课程

GET /api/v2/context 是当前门户的上下文入口，返回：

~~~json
{
  "data": {
    "user_role": "STUDENT|TEACHER|PLATFORM_ADMIN",
    "current_term": {
      "id": "...",
      "code": "...",
      "name": "...",
      "status": "..."
    },
    "courses": [
      {
        "id": "...",
        "code": "...",
        "title": "...",
        "status": "...",
        "staff_role": "...",
        "enrollment_role": "STUDENT"
      }
    ]
  },
  "meta": { "trace_id": "..." }
}
~~~

- 教师门户返回当前学期教师参与的课程和 staff_role。
- 学生门户返回当前学期有效选课课程和 enrollment_role。
- 该接口路径已由后端提供，但当前 OpenAPI 导出中可能未列出；前端应以实际网关路由和在线 schema 为准。
- 课程列表页仍应使用正式的课程列表接口获取分页、搜索和完整课程数据。

## 7. 核心数据对象

以下只列出前端业务需要稳定理解的字段；完整类型、枚举和写入约束以在线 `GET /api/v2/schema` 或重新生成的 `frontend/openapi.json` 为准。

### 7.1 课程 CourseData

~~~text
public_id, code, title, summary, description
owner_id, owner_name, status, visibility
enrollment_mode, capacity, active_enrollment_count
enrollment_start, enrollment_end
teaching_start, teaching_end
row_version
~~~

### 7.2 选课 EnrollmentData

~~~text
public_id, course_id, course_code, course_title
student_id, student_name, cycle_no, status
application_message, applied_at, reviewed_at, activated_at
ended_at, end_reason, decision_note, events[], row_version
~~~

### 7.3 模板和模板版本

TemplateData：

~~~text
public_id, course_id, name, category, description
owner_id, status, current_version_id, row_version
~~~

TemplateVersionData：

~~~text
public_id, template_id, version_no, status
runtime_type, runtime_adapter_id
image_id, image_digest
resource_profile_id
dependencies, execution_spec, network_policy
workspace_capabilities, material_refs
manual_asset_id, starter_asset_id, report_template_asset_id
report_policy, review_policy, retention_days
spec_digest, rules[], row_version
~~~

模板版本是发布和学生任务的规格来源。发布后，实验发布和学生任务会保存镜像、资源规格、执行规格等快照，前端不能把后续修改后的模板数据覆盖到历史发布或历史任务上。

### 7.4 镜像 ImageData

~~~text
public_id, registry, repository, display_tag, digest
scan_status, approval_status, risk_level, scan_report_ref
scanned_at, approved_at, row_version
~~~

教师创建实验模板时应选择已准备且已通过治理的镜像。Docker Swarm 资源运行遵循“教师先准备镜像，学生开始任务时创建对应容器/实例”的业务约定；学生端不应设计为重新构建或重新拉取实验镜像的流程。

### 7.5 资源规格 ResourceProfileData

~~~text
public_id, code, name, runtime_type, status
cpu_millicores, memory_mb
cpu_request_millicores, cpu_limit_millicores
memory_request_mb, memory_limit_mb
disk_gb, network_mode
cost_minor_per_hour, currency_code, row_version
~~~

教师选择资源规格时至少要明确展示 CPU、内存、磁盘、网络模式；不要只展示一个模糊的“规格名称”。最终可选项由模板选项、运行时状态和平台治理结果共同决定。

### 7.6 运行时 RuntimeAdapterData

~~~text
public_id, code, name, runtime_type, driver, status
config_ref, health_status, node_count
capacity_cpu_millicores, available_cpu_millicores
capacity_memory_mb, available_memory_mb
last_health_at, row_version
~~~

运行时连接信息中的 config_ref 可能是内部引用，前端只展示后端允许展示的值，不展示密钥或内部连接详情。

### 7.7 实验发布 PublicationData

~~~text
public_id, course_id, template_version_id, rubric_version_id
template_spec_digest, execution_spec
runtime_adapter_id, runtime_adapter_driver, runtime_adapter_config_ref
image_id, image_digest, resource_profile_id, resource_profile_snapshot
title, description, audience_mode, late_enrollment_policy
window_start, window_end, assignment_deadline
report_required, review_mode, status, audience_count
prerequisites, publication_error, row_version
~~~

发布失败时优先读取 publication_error 和错误响应的 detail、trace_id，不要只展示“请求失败，服务暂时无法处理请求”。

### 7.8 学生任务 TaskData

~~~text
public_id, course_id, publication_id, enrollment_id
student_id, student_name, title
template_version_id, template_name, template_spec_digest
runtime_type, execution_spec
runtime_adapter_id, runtime_adapter_driver, runtime_adapter_config_ref
image_id, image_digest, resource_profile_id, resource_profile_snapshot
report_required, status, terminal_target, progress
window_start, window_end, effective_deadline
allowed_actions, blockers, current_failure, provisioning, row_version
~~~

任务详情中的 allowed_actions 和 blockers 是学生端操作入口的主要依据。前端不要仅根据 status 猜测按钮是否可用。

### 7.9 工作区对象

WorkspaceSession：

~~~text
public_id, task_id, course_id, instance_id, portal
status, capabilities, workspace_urls, expires_at, revoked_at
current_version, latest_client_seq, row_version, workspace_token
~~~

workspace_token 只用于后端规定的工作区连接过程，不得写入日志、URL 查询参数或普通埋点。

WorkspaceSnapshot：

~~~text
public_id, task_id, session_id, version_no, client_seq
base_version, digest_sha256, size_bytes, media_type, saved_at
~~~

WorkspaceExecutionRun：

~~~text
public_id, task_id, session_id, snapshot_id, status
error_code, result_summary, started_at, finished_at
duration_ms, trace_id
~~~

### 7.10 报告和评审

ReportDraftData：

~~~text
public_id, task_id, body_markdown, snapshot_digest
status, attachments[], row_version, updated_at
~~~

ReviewDetailData：

~~~text
public_id, task_id, publication_id, publication_title
student_id, student_name, round_no, status, target_kind
created_at, row_version, rubric_version_id
scores, annotations, auto_checks, similarity_runs
decision, submission
~~~

## 8. 学生端接口

### 8.1 课程、学期和选课

| 能力 | API |
| --- | --- |
| 当前门户上下文 | GET /api/v2/context |
| 浏览可见课程 | GET /api/v2/courses |
| 课程详情 | GET /api/v2/courses/{course_id} |
| 申请加入课程 | POST /api/v2/courses/{course_id}/enrollments |
| 我的选课列表 | GET /api/v2/me/enrollments |
| 我的选课详情 | GET /api/v2/me/enrollments/{enrollment_id} |
| 退出前检查 | GET /api/v2/me/enrollments/{enrollment_id}/drop-check |
| 放弃/退出选课 | POST /api/v2/me/enrollments/{enrollment_id}/drop 或 withdraw |
| 课程资源摘要 | GET /api/v2/me/courses/{course_id}/resource-summary |
| 学生仪表盘 | GET /api/v2/me/dashboard |

课程内容使用通用资源路径：

| resource | API | 说明 |
| --- | --- | --- |
| chapters | GET /api/v2/courses/{course_id}/chapters | 章节列表，按课程结构展示 |
| materials | GET /api/v2/courses/{course_id}/materials | 课程材料 |
| announcements | GET /api/v2/courses/{course_id}/announcements | 公告 |
| calendar-events | GET /api/v2/courses/{course_id}/calendar-events | 日历事件 |
| questions | GET /api/v2/courses/{course_id}/questions | 问答 |

学生提问：POST /api/v2/courses/{course_id}/questions/create；回答问题：POST /api/v2/questions/{question_id}/answers。

### 8.2 我的实验任务

| 能力 | API |
| --- | --- |
| 任务列表 | GET /api/v2/tasks |
| 任务详情 | GET /api/v2/tasks/{task_id} |
| 任务可用状态迁移 | GET /api/v2/tasks/{task_id}/transitions |
| 开始任务 | POST /api/v2/tasks/{task_id}/start |
| 进入工作区 | POST /api/v2/tasks/{task_id}/enter |
| 任务归档信息 | GET /api/v2/tasks/{task_id}/archive |
| 申请延期 | POST /api/v2/tasks/{task_id}/extension-requests |
| 查询延期 | GET /api/v2/tasks/{task_id}/extensions |
| 重试失败任务 | POST /api/v2/tasks/{task_id}/retry |
| 完成任务 | POST /api/v2/tasks/{task_id}/complete |
| 取消装载 | POST /api/v2/tasks/{task_id}/provisioning-job/cancel |
| 查看装载作业 | GET /api/v2/tasks/{task_id}/provisioning-job |

进入任务前检查：

1. 读取任务详情。
2. 检查 allowed_actions 是否包含目标操作。
3. 检查 blockers 是否为空。
4. 调用 POST /enter；不要在前端先假设容器已经存在。
5. 依据响应中的任务和 WorkspaceSession 进入工作区。

### 8.3 工作区和快照

| 能力 | API |
| --- | --- |
| 获取工作台聚合数据 | GET /api/v2/tasks/{task_id}/workbench |
| 创建工作区 session | POST /api/v2/tasks/{task_id}/workspace-sessions |
| 续期 session | POST /api/v2/workspace-sessions/{session_id}/renew |
| 撤销 session | POST /api/v2/workspace-sessions/{session_id}/revoke |
| 保存工作区快照 | PUT /api/v2/tasks/{task_id}/workspace-snapshot |
| 创建 checkpoint | POST /api/v2/tasks/{task_id}/checkpoints |
| 查询 checkpoint | GET /api/v2/tasks/{task_id}/checkpoints |
| 恢复 checkpoint | POST /api/v2/tasks/{task_id}/checkpoints/{checkpoint_id}/restore |
| 创建存储作业 | POST /api/v2/tasks/{task_id}/workspace-storage-jobs |
| 查询存储作业 | GET /api/v2/workspace-storage-jobs/{job_id} |
| 查询执行列表 | GET /api/v2/tasks/{task_id}/execution-runs |
| 查询执行详情 | GET /api/v2/tasks/{task_id}/execution-runs/{execution_id} |
| 操作回放 | GET /api/v2/tasks/{task_id}/operation-replay |

工作区客户端应维护以下本地状态：

- 当前 session_id 和 session 过期时间。
- 最新 version_no、client_seq、base_version。
- 最近一次成功保存的 snapshot_id 和 digest_sha256。
- 当前保存/执行作业的 job id。
- 最近一次失败的 trace_id 和错误码。

保存快照时必须遵守后端返回的版本和序列号。遇到版本冲突时先重新获取最新快照/工作台，不要静默覆盖其他版本。

### 8.4 报告、附件和评审结果

| 能力 | API |
| --- | --- |
| 读取报告草稿 | GET /api/v2/tasks/{task_id}/report-draft |
| 保存报告草稿 | PUT /api/v2/tasks/{task_id}/report-draft |
| 上传报告附件 | POST /api/v2/tasks/{task_id}/attachments |
| 查询附件状态 | GET /api/v2/tasks/{task_id}/attachments/{asset_id} |
| 完成附件上传 | POST /api/v2/tasks/{task_id}/attachments/{asset_id}/complete |
| 提交报告 | POST /api/v2/tasks/{task_id}/submit-report |
| 报告版本 | GET /api/v2/tasks/{task_id}/report-versions |
| 查看评审结果 | GET /api/v2/tasks/{task_id}/review-result |
| 创建文件下载授权 | POST /api/v2/files/{asset_id}/download-grants |
| 撤销下载授权 | POST /api/v2/files/download-grants/{grant_id}/revoke |
| 文件下载 | GET /files/{token} |

报告提交前应确认：

- 报告草稿已保存。
- 必要附件已完成上传且安全扫描通过。
- 当前工作区快照与报告的 snapshot_digest 对齐。
- 必要执行已完成。

## 9. 教师端接口

### 9.1 当前学期和我的课程

| 能力 | API |
| --- | --- |
| 当前门户上下文 | GET /api/v2/context |
| 教师课程列表 | GET /api/v2/teaching/courses |
| 创建课程 | POST /api/v2/teaching/courses |
| 课程详情 | GET /api/v2/teaching/courses/{course_id} |
| 修改课程 | PATCH /api/v2/teaching/courses/{course_id} |
| 发布课程 | POST /api/v2/teaching/courses/{course_id}/publish |
| 关闭课程 | POST /api/v2/teaching/courses/{course_id}/close |
| 归档检查 | GET /api/v2/teaching/courses/{course_id}/archive-check |
| 归档课程 | POST /api/v2/teaching/courses/{course_id}/archive |
| 课程治理信息 | GET /api/v2/teaching/courses/{course_id}/governance |

课程内容统一使用：

~~~text
GET/POST /api/v2/teaching/courses/{course_id}/{resource}
~~~

当前资源包括：chapters、materials、announcements、calendar-events、questions、prerequisites。章节是课程内容树的上层对象；材料可以归属于章节。章节状态通过：

~~~text
POST /api/v2/teaching/courses/{course_id}/chapters/{chapter_id}/{status}
~~~

章节先修关系使用：

~~~text
GET/PUT /api/v2/teaching/courses/{course_id}/chapters/{chapter_id}/prerequisites
~~~

材料版本和公告状态使用 OpenAPI 中对应的路径，不要通过修改列表响应中的 status 字段来模拟发布。

### 9.2 课程成员和选课审核

| 能力 | API |
| --- | --- |
| 课程成员 | GET/POST /api/v2/teaching/courses/{course_id}/staff |
| 成员授权 | GET/POST /api/v2/teaching/courses/{course_id}/staff/{staff_id}/grants |
| 撤销成员授权 | POST .../grants/{grant_id}/revoke |
| 撤销成员 | POST .../staff/{staff_id}/revoke |
| 选课列表 | GET /api/v2/teaching/courses/{course_id}/enrollments |
| 选课详情 | GET /api/v2/teaching/courses/{course_id}/enrollments/{enrollment_id} |
| 审核选课 | POST .../enrollments/{enrollment_id}/review |
| 移除前检查 | GET .../enrollments/{enrollment_id}/removal-check |
| 移除选课 | POST .../enrollments/{enrollment_id}/remove |
| 邀请 | GET/POST /api/v2/teaching/courses/{course_id}/invitations |
| 批量导入预检 | POST .../enrollment-imports/precheck |
| 批量导入执行/查询 | POST/GET .../enrollment-imports/{job_id} |

### 9.3 实验模板、章节和任务

模板基础接口：

| 能力 | API |
| --- | --- |
| 模板列表/创建 | GET/POST /api/v2/teaching/courses/{course_id}/templates |
| 模板详情/修改 | GET/PATCH .../templates/{template_id} |
| 模板版本列表/创建 | GET/POST .../templates/{template_id}/versions |
| 模板版本详情/修改 | GET/PATCH .../template-versions/{version_id} |
| 克隆模板版本 | POST .../template-versions/{version_id}/clone |
| 模板版本发布 | POST .../template-versions/{version_id}/publish |
| 模板版本撤回 | POST .../template-versions/{version_id}/withdraw |
| 自动检查规则 | GET/PUT .../template-versions/{version_id}/auto-check-rules |
| 模板选项 | GET /api/v2/teaching/courses/{course_id}/template-options |

模板章节和任务的前端职责：

- 章节属于课程内容结构，不要把章节标题硬编码到模板 JSON。
- 每章可以组织相关材料和实验任务；任务实际生成于实验发布后。
- 模板版本保存运行时、镜像、资源规格、网络策略、工作区能力、报告策略和评审策略。
- 修改已被发布或引用的模板版本时，优先创建/克隆新版本，不要覆盖历史版本事实。

模板版本章节和任务使用以下接口。章节、任务的排序会更新模板版本的 row_version，因此每次写入都要发送该版本最新的 ETag：

| 能力 | API |
| --- | --- |
| 模板版本章节列表/创建 | GET/POST /api/v2/teaching/courses/{course_id}/template-versions/{version_id}/chapters |
| 章节修改 | PATCH /api/v2/teaching/courses/{course_id}/template-chapters/{chapter_id} |
| 章节排序 | POST /api/v2/teaching/courses/{course_id}/template-versions/{version_id}/chapters/reorder |
| 章节下任务列表/创建 | GET/POST /api/v2/teaching/courses/{course_id}/template-chapters/{chapter_id}/tasks |
| 任务修改 | PATCH /api/v2/teaching/courses/{course_id}/template-tasks/{task_id} |
| 任务排序 | POST /api/v2/teaching/courses/{course_id}/template-chapters/{chapter_id}/tasks/reorder |

章节对象主要包含 public_id、title、description、learning_objectives、sort_order、status、resource_profile_id、effective_resource_profile_id、row_version 和嵌套 tasks。任务对象主要包含 public_id、title、description、instructions、task_type、sort_order、status、execution_spec、resource_profile_id、effective_resource_profile_id、submission_policy、grading_policy 和 row_version。

章节写入字段包括 title、description、learning_objectives、sort_order、status、resource_profile_id；任务写入字段包括 title、description、instructions、task_type、sort_order、status、execution_spec、resource_profile_id、submission_policy、grading_policy。创建任务还需要 Idempotency-Key；章节和任务更新/排序需要 If-Match。

### 9.4 镜像、资源和 Docker Swarm 运行时

教师模板配置需要先选择：

1. 已创建并治理的实验镜像。
2. 已激活、匹配运行时类型的资源规格。
3. 可用且健康的运行时适配器。
4. 执行规格、网络策略和工作区能力。

模板资源资产接口：

~~~text
POST /api/v2/teaching/courses/{course_id}/templates/{template_id}/assets
GET  /api/v2/teaching/courses/{course_id}/templates/{template_id}/assets/{asset_id}
POST /api/v2/teaching/courses/{course_id}/templates/{template_id}/assets/{asset_id}/complete
~~~

教师实验镜像的课程级接口如下。它们与平台管理员的全局镜像治理接口不同：

~~~text
GET/POST  /api/v2/teaching/courses/{course_id}/experiment-images
GET       /api/v2/teaching/courses/{course_id}/experiment-images/{image_id}
POST      /api/v2/teaching/courses/{course_id}/experiment-images/{image_id}/prepare
GET       /api/v2/teaching/courses/{course_id}/experiment-images/{image_id}/events
POST      /api/v2/teaching/courses/{course_id}/experiment-images/{image_id}/retire
~~~

创建镜像时使用 template_version_id、source_type、registry、repository、requested_tag 等字段；响应中的 resolved_digest、status、scan_status、validation_detail、error_code 和 row_version 用于显示镜像准备过程。prepare 需要 If-Match 和 Idempotency-Key，retire 需要 If-Match。镜像准备是异步操作，应读取镜像事件或轮询详情，不要在请求返回 202 时直接认为镜像已可发布。

平台治理侧提供镜像、资源规格和运行时选项：

~~~text
GET/POST   /api/v2/platform/images
GET/PATCH  /api/v2/platform/images/{image_id}
POST       /api/v2/platform/images/{image_id}/decide
GET/POST   /api/v2/platform/resource-profiles
GET/PATCH  /api/v2/platform/resource-profiles/{profile_id}
POST       /api/v2/platform/resource-profiles/{profile_id}/activate
POST       /api/v2/platform/resource-profiles/{profile_id}/retire
GET/POST   /api/v2/platform/runtime-adapters
GET/PATCH  /api/v2/platform/runtime-adapters/{adapter_id}
~~~

教师端不应直接调用平台治理接口创建镜像或修改全局配额；教师端通过 template-options 获取可选择项。学生启动任务时后端依据发布快照和资源规格创建对应工作区实例，不应重新设计为学生再次选择 CPU/内存或拉取镜像。

### 9.5 模板预检和实验发布

| 能力 | API |
| --- | --- |
| 发起模板预检 | POST /api/v2/teaching/courses/{course_id}/template-versions/{version_id}/precheck |
| 查看预检历史 | GET .../template-versions/{version_id}/precheck-runs |
| 创建实验发布草稿 | POST /api/v2/teaching/courses/{course_id}/experiments |
| 发布详情/修改 | GET/PATCH .../experiments/{publication_id} |
| 发布实验 | POST .../experiments/{publication_id}/publish |
| 撤回实验 | POST .../experiments/{publication_id}/withdraw |
| 关闭实验 | POST .../experiments/{publication_id}/close |
| 发布任务列表 | GET .../experiments/{publication_id}/tasks |

推荐前端流程：

1. 获取教师当前门户、课程、模板和 template-options。
2. 创建或选择模板版本。
3. 配置章节关联、材料引用、实验说明和任务规则。
4. 选择已通过治理的镜像，确认 digest；不要只保存 tag。
5. 选择资源规格，明确显示 CPU、内存、磁盘和网络模式。
6. 发起模板预检并读取 PrecheckRunData。
7. 只有预检成功且摘要未变化时，发布模板版本。
8. 创建实验发布草稿，设置受众、先修条件、时间窗口、截止时间、报告和评审策略。
9. 发送实验发布命令。
10. 轮询发布详情或订阅 SSE，直到 status 进入成功、失败或可继续处理的状态。
11. 失败时显示 publication_error、错误码和 trace id，并允许用户回到具体配置步骤修正。

模板预检结果包含阶段、重试信息、阶段结果、错误码和 retryable。预检通过后如果模板版本被修改，应重新预检。

### 9.6 Rubric、评审和分析

| 能力 | API |
| --- | --- |
| Rubric 列表/创建 | GET/POST /api/v2/teaching/courses/{course_id}/rubrics |
| Rubric 版本 | GET/POST .../rubrics/{rubric_id}/versions |
| Rubric 版本详情/修改 | GET/PATCH .../rubric-versions/{version_id} |
| 发布 Rubric 版本 | POST .../rubric-versions/{version_id}/publish |
| 评审列表/详情 | GET .../reviews、GET .../reviews/{review_id} |
| 评分 | GET/PUT .../reviews/{review_id}/criterion-scores |
| 批注 | GET/POST .../reviews/{review_id}/annotations |
| 批注修订/撤回 | POST .../annotations/{annotation_id}/revisions、revoke |
| 评审决策 | POST .../reviews/{review_id}/decide |
| 相似度检测 | POST/GET .../similarity-runs、GET .../similarity-runs/{run_id}/matches |
| 提交预览 | GET .../tasks/{task_id}/submission-preview |
| 学生工作区查看 | GET .../tasks/{task_id}/workspace |
| 操作回放 | GET .../tasks/{task_id}/operation-replay |
| 教学分析 | GET .../analytics/overview、quality、resource-costs |
| 风险信号 | GET .../analytics/risk-signals、POST .../risk-signals/{signal_id}/resolve |
| 实验进度 | GET .../progress |

评分保存和评审命令需要遵守 Idempotency-Key 与 If-Match。AUTO_CHECK_PENDING 表示自动检查尚未完成，不应被前端转换成“评分失败”。

## 10. 平台管理员端接口

平台端按能力分组如下，具体请求体和响应 schema 以 OpenAPI 为准。

| 能力 | API 前缀/路径 |
| --- | --- |
| 用户和资格 | /api/v2/platform/users、/platform/teacher-qualifications、/platform/admin-assignments、/platform/verifications |
| 课程治理 | /api/v2/platform/courses、/platform/governance/alerts、/platform/governance/usage |
| 镜像治理 | /api/v2/platform/images |
| 资源规格 | /api/v2/platform/resource-profiles |
| 运行时适配器 | /api/v2/platform/runtime-adapters |
| 配额 | /api/v2/platform/quotas |
| 资源扩缩容策略 | /api/v2/platform/resource-scaling-policies |
| 安全策略 | /api/v2/platform/security-policies、/platform/network-allowlists |
| 运行实例 | /api/v2/platform/instances |
| 异常任务 | /api/v2/platform/tasks/anomalies |
| 报告扫描异常 | /api/v2/platform/reports/scan-anomalies |
| 模板预检汇总 | /api/v2/platform/template-prechecks/summary |
| 运行和操作概览 | /api/v2/platform/operations/overview、/operations/logs |
| 评审汇总 | /api/v2/platform/reviews/summary |
| Agent 路由和策略 | /api/v2/platform/agent/model-routes、tool-policies、usage-costs |
| Agent 评测 | /api/v2/platform/agent/eval-suites、eval-runs |
| 集成 | /api/v2/platform/integrations/... |
| 工作区监控 | /api/v2/platform/workspaces/sessions |

平台端操作通常涉及全局状态、密钥、资源和安全策略。前端必须根据 MeData.permissions 控制入口，并对写入操作使用幂等键和版本控制；不要把平台密钥、OIDC client secret、Webhook secret、config_ref 具体内容暴露给普通用户。

## 11. Agent、通知、分析和外部集成

### 11.1 学生/课程 Agent

~~~text
GET  /api/v2/courses/{course_id}/agent-profile
POST /api/v2/courses/{course_id}/agent-sessions
POST /api/v2/tasks/{task_id}/agent-sessions
GET  /api/v2/agent-sessions/{session_id}
GET  /api/v2/agent-sessions/{session_id}/messages
POST /api/v2/agent-sessions/{session_id}/messages
POST /api/v2/agent-sessions/{session_id}/tool-calls
POST /api/v2/agent-tool-calls/{call_id}/decide
POST /api/v2/agent-messages/{message_id}/feedback
~~~

Agent 工具调用可能需要用户决策；前端应根据响应状态等待或展示决策入口，不能把工具调用默认为已执行。

### 11.2 通知、风险和推荐

~~~text
GET /api/v2/notifications
POST /api/v2/notifications/{notification_id}/read
GET /api/v2/analytics/risk-signals
GET /api/v2/analytics/recommendations
~~~

### 11.3 外部集成

机器 API 使用 api.localhost 或服务器对应的 API 域名，由网关注入 INTEGRATION 上下文：

~~~text
POST /api/v2/integrations/oauth/token
GET  /api/v2/integrations/open/courses
GET  /api/v2/integrations/open/courses/{course_id}/experiments
GET  /api/v2/integrations/open/courses/{course_id}/progress
~~~

普通门户前端不要把集成 OAuth token 流程和 Django session 登录流程混用。

## 12. 文件上传、扫描和下载

文件类接口通常是“创建上传/授权 → 上传到对象存储 → complete → 等待扫描 → 使用”。前端应：

1. 先调用对应业务的上传创建接口。
2. 按响应提供的上传目标和字段上传，不自行拼接 MinIO 内部地址。
3. 调用对应的 complete 接口。
4. 轮询资源状态或等待事件，直到安全扫描通过。
5. 只有在状态允许时创建下载 grant。
6. 使用返回的短期下载 token 调用 /files/{token}。
7. 不在 URL、日志或埋点中长期保存下载 token。

模板资产、报告附件、Agent 源文件、课程材料的上传接口和对象不同，不能交叉使用 asset id。

## 13. SSE 事件流

入口：

~~~text
GET /api/v2/events/stream
Accept: text/event-stream
~~~

事件流按门户和当前用户权限过滤。事件结构：

~~~text
id: <occurred_at>|<event_uuid>
event: <event_type>
data: {"...":"...", "trace_id":"..."}
~~~

前端应：

- 保存最后一个 id，重连时发送 Last-Event-ID。
- 处理注释行 : heartbeat 和 : stream-ready，不要把它们当业务事件。
- 收到 resync.required 时重新拉取相关列表/详情，不要只依赖事件补齐状态。
- 处理 SSE_RESYNC_REQUIRED 和 SSE_CURSOR_EXPIRED，重新建立无 cursor 连接并主动刷新页面状态。
- 事件仅用于实时提示和刷新触发；最终事实以 REST 查询结果为准。

实验发布相关事件包括发布成功、失败、关闭和撤回；发布失败事件中的 payload 与发布详情中的 publication_error 都应保留 trace 信息。

## 14. 端到端业务流程

### 14.1 教师创建并发布实验

~~~text
获取教师 context/me
  → 获取当前课程
  → 创建/选择模板
  → 创建模板版本
  → 配置章节、材料、任务规则
  → 选择已治理镜像
  → 选择 CPU/内存/磁盘/网络资源规格
  → 模板预检
  → 发布模板版本
  → 创建实验发布草稿
  → 设置受众、先修条件、时间窗口、截止时间、报告/评审策略
  → 发布实验
  → 轮询详情或订阅 SSE
~~~

必须在发布前固定以下快照：

- template_spec_digest
- image_digest
- resource_profile_snapshot
- execution_spec
- runtime adapter 信息

如果收到“请求失败”类通用提示，先读取 HTTP 响应 JSON；常见根因包括模板预检失败、镜像未准备、资源规格不可用、先修条件阻断、版本冲突和运行时不可用。

### 14.2 学生开始实验

~~~text
获取 USER context/me
  → 获取当前课程和任务
  → 检查 allowed_actions/blockers
  → POST /tasks/{task_id}/enter
  → 创建或取得 WorkspaceSession
  → GET workbench
  → 按 client_seq 保存 workspace snapshot/checkpoint
  → 执行并查询 execution run
  → 保存 report draft
  → 上传并完成附件扫描
  → submit-report
  → 查询 review-result
~~~

学生开始任务时，后端根据实验发布保存的镜像 digest、资源规格和执行规格创建对应容器/工作区；前端不需要也不应要求学生重新构建或重新拉取镜像。

### 14.3 教师评审

~~~text
获取课程实验进度
  → 获取 reviews / submission-preview
  → 获取自动检查与相似度结果
  → 写入 criterion-scores
  → 添加/修订/撤回 annotations
  → POST /reviews/{review_id}/decide
~~~

评审页面应区分“自动检查处理中”“待教师评审”“已保存评分”“已完成决策”等后端状态，不要把所有非完成状态统一显示为失败。

## 15. API 完整索引

以下索引按业务域列出当前 OpenAPI 路径的主要入口；每个路径下的具体方法、operationId、请求体、响应体和枚举请直接读取在线 schema、后端对应 `urls.py`/serializer，或恢复后重新生成的 `frontend/openapi.json`。

### 15.1 认证、用户、学生端、工作区和集成

| 方法 | 路径 |
| --- | --- |
| GET/POST | /api/v2/auth/*、/api/v2/me*、/api/v2/notification-preferences、/api/v2/notifications* |
| GET | /api/v2/courses、/api/v2/courses/{course_id} |
| GET/POST | /api/v2/courses/{course_id}/{resource} |
| POST | /api/v2/courses/{course_id}/enrollments、/api/v2/courses/{course_id}/questions/create |
| GET | /api/v2/tasks、/api/v2/tasks/{task_id}、/api/v2/tasks/{task_id}/transitions |
| POST | /api/v2/tasks/{task_id}/start、enter、complete、retry、submit-report |
| GET/PUT/POST | /api/v2/tasks/{task_id}/report-draft、workspace-snapshot、checkpoints、workspace-storage-jobs |
| GET/POST | /api/v2/tasks/{task_id}/attachments*、execution-runs*、extensions*、operation-replay |
| GET/POST | /api/v2/tasks/{task_id}/workbench、workspace-sessions、/api/v2/workspace-sessions/* |
| GET/POST | /api/v2/agent-*、/api/v2/courses/{course_id}/agent-* |
| GET | /api/v2/events/stream、/api/v2/analytics/* |
| POST/GET | /api/v2/files/*、/files/{token} |
| GET/POST | /api/v2/integrations/open/*、/api/v2/integrations/oauth/token |

### 15.2 教师端

| 业务域 | 路径 |
| --- | --- |
| 课程 | /api/v2/teaching/courses* |
| 内容 | /api/v2/teaching/courses/{course_id}/{resource} |
| 章节先修 | /api/v2/teaching/courses/{course_id}/chapters/{chapter_id}/prerequisites |
| 章节状态 | /api/v2/teaching/courses/{course_id}/chapters/{chapter_id}/{status} |
| 材料版本 | /api/v2/teaching/courses/{course_id}/materials/*、material-versions/* |
| 选课 | /api/v2/teaching/courses/{course_id}/enrollments*、invitations*、enrollment-imports* |
| 实验发布 | /api/v2/teaching/courses/{course_id}/experiments* |
| 模板 | /api/v2/teaching/courses/{course_id}/templates*、template-versions*、template-options |
| Rubric | /api/v2/teaching/courses/{course_id}/rubrics*、rubric-versions* |
| 评审 | /api/v2/teaching/courses/{course_id}/reviews*、similarity-runs* |
| 任务工作区 | /api/v2/teaching/courses/{course_id}/tasks/* |
| 分析 | /api/v2/teaching/courses/{course_id}/analytics/*、progress、governance |
| Agent | /api/v2/teaching/courses/{course_id}/agent-* |

### 15.3 平台端

| 业务域 | 路径 |
| --- | --- |
| 用户资格 | /api/v2/platform/users*、teacher-qualifications*、admin-assignments*、verifications* |
| 课程治理 | /api/v2/platform/courses*、governance/* |
| 运行时 | /api/v2/platform/runtime-adapters*、instances* |
| 镜像与资源 | /api/v2/platform/images*、resource-profiles*、quotas* |
| 策略 | /api/v2/platform/security-policies、network-allowlists*、resource-scaling-policies |
| 运维分析 | /api/v2/platform/operations/*、analytics/*、tasks/anomalies、reports/scan-anomalies |
| Agent 平台 | /api/v2/platform/agent/* |
| 集成管理 | /api/v2/platform/integrations/* |
| 工作区监控 | /api/v2/platform/workspaces/sessions |

### 15.4 源码已注册但当前 OpenAPI 导出缺失的接口

历史导出的 `frontend/openapi.json` 覆盖了主要契约，但以下接口曾在后端 URL 配置和视图中注册、而导出文件未完整覆盖。当前工作树没有该导出文件；前端联调应先以在线 schema、后端 URL 配置和视图 serializer 复核：

| 方法 | 路径 | operationId |
| --- | --- | --- |
| GET | /api/v2/context | context_retrieve |
| POST | /api/v2/student/task-runtimes/{runtime_id}/stop | student_task_runtime_stop |
| GET/POST | /api/v2/teaching/courses/{course_id}/experiment-images | teaching_experiment_images_list / teaching_experiment_images_create |
| GET | /api/v2/teaching/courses/{course_id}/experiment-images/{image_id} | teaching_experiment_images_retrieve |
| POST | /api/v2/teaching/courses/{course_id}/experiment-images/{image_id}/prepare | teaching_experiment_images_prepare |
| GET | /api/v2/teaching/courses/{course_id}/experiment-images/{image_id}/events | teaching_experiment_images_events |
| POST | /api/v2/teaching/courses/{course_id}/experiment-images/{image_id}/retire | teaching_experiment_images_retire |
| GET/POST | /api/v2/teaching/courses/{course_id}/template-versions/{version_id}/chapters | teaching_template_chapters_list / teaching_template_chapters_create |
| POST | /api/v2/teaching/courses/{course_id}/template-versions/{version_id}/chapters/reorder | teaching_template_chapters_reorder |
| PATCH | /api/v2/teaching/courses/{course_id}/template-chapters/{chapter_id} | teaching_template_chapters_update |
| GET/POST | /api/v2/teaching/courses/{course_id}/template-chapters/{chapter_id}/tasks | teaching_template_tasks_list / teaching_template_tasks_create |
| POST | /api/v2/teaching/courses/{course_id}/template-chapters/{chapter_id}/tasks/reorder | teaching_template_tasks_reorder |
| PATCH | /api/v2/teaching/courses/{course_id}/template-tasks/{task_id} | teaching_template_tasks_update |

## 16. 前端联调检查清单

### 请求层

- [ ] 所有门户 API 使用正确 Host，未在前端伪造 X-Portal 等网关头。
- [ ] 浏览器请求启用 credentials: include。
- [ ] 首次写请求前已获得 csrftoken，并发送 X-CSRFToken。
- [ ] 所有要求幂等的命令带 Idempotency-Key。
- [ ] 更新已有对象时从最新响应保存 ETag 并发送 If-Match。
- [ ] 请求失败保留 trace_id 和 X-Request-ID。

### 业务状态

- [ ] 操作按钮根据 allowed_actions、blockers 和权限决定，而不是只看前端本地状态。
- [ ] 模板版本、发布、任务、报告、评审均按后端状态机处理。
- [ ] 发布失败读取 publication_error，展示可定位信息。
- [ ] 任务启动展示装载进度和可重试性，不把异步装载当同步成功。
- [ ] 工作区保存维护 client_seq、base_version 和快照摘要。
- [ ] 报告提交前校验快照、执行结果和附件扫描状态。

### 安全

- [ ] 不记录 session cookie、CSRF token、workspace token、下载 token、密钥或密码。
- [ ] 不把内部 config_ref 当作可公开连接信息。
- [ ] 文件下载使用短期 grant，不长期缓存 token。
- [ ] SSE 断线重连使用 Last-Event-ID，收到 resync 事件后主动刷新 REST 数据。

### 类型和契约

- [ ] 前端目录恢复后，从在线 schema 重新生成 `frontend/openapi.json` 和类型，并校验生成结果与后端路由一致。
- [ ] 对可空字段保留 null 语义，不用空字符串替代。
- [ ] 时间字段按 ISO 8601 date-time 处理并统一时区显示策略。
- [ ] cpu_millicores、memory_mb、disk_gb 等资源字段按数值处理，不从展示字符串反解析。
- [ ] 发现契约差异时记录 endpoint、请求、响应、trace id 和 schema 版本。

## 17. 版本和迁移约定

当前后端以 /api/v2 为主，前端重构可先按本文档完成 API client、类型层、缓存层、错误层、权限层和业务模块拆分，再逐步替换页面。不要在前端建立与后端不一致的“兼容状态机”，也不要把历史模板数据直接迁移为当前模板版本。

后续后端接口扩展应优先：

1. 更新 OpenAPI schema。
2. 保留已有状态和错误码语义。
3. 对新命令声明幂等和并发要求。
4. 对异步作业提供可查询状态或事件。
5. 同步更新本文档的业务分组和端到端流程。
