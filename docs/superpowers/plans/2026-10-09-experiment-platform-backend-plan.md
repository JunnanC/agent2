# Experiment Platform Backend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不破坏现有 Django 业务的前提下，增加学期/课程上下文、章节/任务结构、镜像双模式、CPU/内存资源预留，以及 Fake → Local Docker → Docker Swarm 的同流程运行时能力。

**Architecture:** 以现有 `courses`、`labtemplates`、`experiments`、`governance`、`provisioning` 和 `workspaces` 为边界，先补齐可独立测试的领域模型和服务，再通过现有 `RuntimeAdapter` 端口接入 Fake、真实本地 Docker 和 Swarm。发布版本冻结章节、任务、镜像 digest 和资源快照；学生启动只创建运行实例，并通过异步 provisioning job 与资源预留保持一致。

**Tech Stack:** Python 3.14, Django 6.1.1, Django REST Framework 3.18.1, Celery 5.6.3, MySQL 8.4, Redis 7, Docker SDK/Swarm, pytest, pytest-django, Ruff, mypy。

**Spec:** `docs/superpowers/specs/2026-10-09-experiment-platform-backend-design.md`

## Global Constraints

- 保留现有 canonical Django 项目：`backend/education_experiment_platform`。
- 不创建平行的 `backend/apps`、`backend/config` 或根目录 `manage.py`。
- 学生请求不得构建镜像、显式 pull 镜像或使用可变 tag；运行引用必须是 `registry/repository@sha256:<digest>`。
- 模板创建不占用运行资源；资源只在学生启动实例时创建并锁定 `QuotaReservation`。
- Fake、Local Docker、Docker Swarm 共享业务服务、状态机和 API，只替换 `RuntimeAdapter` 实现。
- 所有 Swarm/Docker 外部调用必须经过 `provisioning` 端口；API 进程不直接拥有 Docker socket。
- 新数据优先读取；旧数据通过兼容适配器转换为默认章节和默认任务。
- 不提交与本任务无关的工作区修改；不删除已有未提交文件。
- 每个任务先写失败测试，再实现最小代码，任务结束运行针对性测试并提交一个小 commit。

---

## 文件边界总览

- `apps/courses`：`AcademicTerm`、课程学期关联、当前学期/我的课程上下文。
- `apps/labtemplates`：模板版本章节/任务、实验镜像、构建/验证和教师编辑 API。
- `apps/governance`：CPU/内存规格、运行时容量和平台级镜像事实。
- `apps/experiments`：发布章节/任务快照、学生进度和学生运行入口。
- `apps/provisioning`：资源预留、运行时端口、Fake/Local/Swarm adapter、异步 provisioning 和对账。
- `apps/workspaces`：运行实例就绪后的访问会话，不负责创建容器。
- `docker-compose.dev.yml`、`.env.example`、`infrastructure/swarm/stack.yml`：本地和服务器运行时配置。
- 各 app 的 `migrations/` 和 `tests/`：数据库演进与针对性验证。

### Task 1: Freeze the Runtime Port and Add Explicit Runtime Modes

**Files:**
- Modify: `backend/apps/provisioning/ports.py`
- Modify: `backend/apps/provisioning/adapters.py`
- Modify: `backend/apps/provisioning/services.py`
- Modify: `backend/education_experiment_platform/education_experiment_platform/settings/base.py`
- Modify: `.env.example`
- Test: `backend/apps/provisioning/tests/test_adapter_contract.py`
- Test: `backend/apps/provisioning/tests/test_services.py`

**Interfaces:**
- Consumes: existing `RuntimeSpec`, `RuntimeResult`, `RuntimeAdapter`, governance runtime rows.
- Produces: `runtime_adapter_for(code: str) -> RuntimeAdapter`, explicit `RUNTIME_MODE` resolution, and capability payload with `image_build`, `real_container`, `resource_limits`, `workspace_access`.

- [ ] Write failing tests for `fake`, `local`, `swarm`, unknown mode, and missing production configuration.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/provisioning/tests/test_adapter_contract.py -q`; expected failure for missing resolver/capabilities.
- [ ] Implement one resolver outside views using `RUNTIME_MODE`, `RUNTIME_ADAPTER_CODE`, and existing `RUNTIME_ADAPTER_CONFIGS`; preserve current adapter call signatures.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/provisioning/tests/test_adapter_contract.py education_experiment_platform/apps/provisioning/tests/test_services.py -q`; expected PASS.
- [ ] Commit: `git add backend/apps/provisioning backend/education_experiment_platform/education_experiment_platform/settings/base.py .env.example; git commit -m "refactor: define configurable runtime modes"`.

### Task 2: Add Academic Terms and Unified Course Context

**Files:**
- Modify: `backend/apps/courses/models.py`
- Modify: `backend/apps/courses/selectors.py`
- Modify: `backend/apps/courses/services.py`
- Modify: `backend/apps/courses/views.py`
- Modify: `backend/apps/courses/urls.py`
- Create: `backend/apps/courses/migrations/0005_academicterm_course_term.py`
- Test: `backend/apps/courses/tests/test_models.py`
- Test: `backend/apps/courses/tests/test_services.py`
- Test: `backend/apps/courses/tests/test_api.py`

**Interfaces:**
- Consumes: `CourseStaff`, `Enrollment`, `Course`, and existing actor permission helpers.
- Produces: `current_academic_term()`, `teacher_courses_for_term(actor, term_ref)`, `student_courses_for_term(actor, term_ref)`, and `GET /api/v2/context`.

- [ ] Write failing tests for one current term, required course term, active teacher staff, active student enrollment, and exclusion of closed/archived courses.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/courses/tests/test_models.py education_experiment_platform/apps/courses/tests/test_services.py -q`; expected schema/selector failure.
- [ ] Add `AcademicTerm` with `UPCOMING/CURRENT/CLOSED`, date constraints, a current marker, and a transitional course term migration derived from legacy teaching windows.
- [ ] Add term-aware selectors and a compact context endpoint returning user role, current term, course id/code/title/status, and staff/enrollment role.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/courses/tests/test_models.py education_experiment_platform/apps/courses/tests/test_services.py education_experiment_platform/apps/courses/tests/test_api.py -q`; expected PASS.
- [ ] Commit: `git add backend/apps/courses; git commit -m "feat: add academic term and course context"`.

### Task 3: Add Versioned Chapters and Tasks to Lab Templates

**Files:**
- Modify: `backend/apps/labtemplates/models.py`
- Modify: `backend/apps/labtemplates/services.py`
- Modify: `backend/apps/labtemplates/serializers.py`
- Modify: `backend/apps/labtemplates/views.py`
- Modify: `backend/apps/labtemplates/urls.py`
- Create: `backend/apps/labtemplates/migrations/0004_template_chapter_task.py`
- Test: `backend/apps/labtemplates/tests/test_services.py`
- Test: `backend/apps/labtemplates/tests/test_api.py`

**Interfaces:**
- Consumes: `TemplateVersion`, `MANAGE_TEMPLATE`, and existing compare-and-swap row versions.
- Produces: `create_chapter`, `update_chapter`, `create_task`, `update_task`, `reorder_chapters`, `reorder_tasks`, and ordered nested serialization.

- [ ] Write failing tests for draft-only edits, positive unique order, resource inheritance, post-publication lock, and nested order.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/labtemplates/tests/test_services.py education_experiment_platform/apps/labtemplates/tests/test_api.py -q`; expected missing model/service failure.
- [ ] Add `TemplateChapter` and `TemplateTask` with ULIDs, version/parent foreign keys, positive ordering, status checks, JSON policy fields, and protected resource profiles.
- [ ] Implement transactional CRUD and batch reorder using `compare_and_swap`; reject mixed-parent ids and edits after publication.
- [ ] Add teacher routes and ordered nested serializers with effective resource values.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/labtemplates/tests -q`; expected PASS.
- [ ] Commit: `git add backend/apps/labtemplates; git commit -m "feat: add versioned experiment chapters and tasks"`.

### Task 4: Normalize Resource Profiles and Reservation Semantics

**Files:**
- Modify: `backend/apps/governance/models.py`
- Modify: `backend/apps/governance/services.py`
- Modify: `backend/apps/provisioning/models.py`
- Modify: `backend/apps/provisioning/services.py`
- Create: `backend/apps/governance/migrations/0003_resource_request_limits.py`
- Create: `backend/apps/provisioning/migrations/0002_reservation_binding.py`
- Test: `backend/apps/governance/tests/test_services.py`
- Test: `backend/apps/provisioning/tests/test_services.py`

**Interfaces:**
- Consumes: existing `ResourceProfile`, `RuntimeAdapter` capacities, and `QuotaReservation` logic.
- Produces: `validate_resource_profile(profile_data)`, `effective_resource_profile(task)`, `reserve_runtime_capacity(...)`, and idempotent `release_runtime_capacity(...)`.

- [ ] Write failing tests for positive CPU/memory, request <= limit, insufficient capacity, no capacity change on template creation, duplicate active reservation reuse, and idempotent release.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/governance/tests/test_services.py education_experiment_platform/apps/provisioning/tests/test_services.py -q`; expected failure for new fields/semantics.
- [ ] Extend `ResourceProfile` with CPU request/limit millicores and memory request/limit MB; preserve legacy fields in a data migration and add database checks.
- [ ] Implement row-locked admission/release: lock runtime and active reservation rows, compare capacity, create/reuse one reservation, decrement once, restore once.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/governance/tests education_experiment_platform/apps/provisioning/tests/test_services.py -q`; expected PASS.
- [ ] Commit: `git add backend/apps/governance backend/apps/provisioning; git commit -m "feat: enforce cpu memory resource reservations"`.

### Task 5: Add Experiment Image Lifecycle for Build and External Reference

**Files:**
- Modify: `backend/apps/governance/models.py`
- Modify: `backend/apps/labtemplates/models.py`
- Create: `backend/apps/labtemplates/image_services.py`
- Modify: `backend/apps/labtemplates/tasks.py`
- Modify: `backend/apps/labtemplates/serializers.py`
- Modify: `backend/apps/labtemplates/views.py`
- Modify: `backend/apps/labtemplates/urls.py`
- Create: `backend/apps/labtemplates/migrations/0005_experiment_image_build_job.py`
- Test: `backend/apps/labtemplates/tests/test_assets.py`
- Test: `backend/apps/labtemplates/tests/test_services.py`

**Interfaces:**
- Consumes: `ImageAsset`, runtime adapter image methods, object assets for build context, and template versions.
- Produces: `create_experiment_image`, `prepare_experiment_image`, `resolve_external_digest`, `validate_experiment_image`, and status serializers.

- [ ] Write failing tests for BUILD_CONTEXT and EXTERNAL_REFERENCE, tag-to-digest before READY, scan/probe failure, and repeated prepare idempotency.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/labtemplates/tests/test_assets.py education_experiment_platform/apps/labtemplates/tests/test_services.py -q`; expected missing lifecycle failure.
- [ ] Add `ExperimentImage` and `ImageBuildJob`, separate requested tag from resolved digest, and validate explicit lifecycle transitions.
- [ ] Implement one Celery preparation task: branch by source, build or resolve, persist digest, update scan state, validate, and mask build args/logs.
- [ ] Add teacher image create/prepare/detail/events/retire routes.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/labtemplates/tests -q`; expected PASS.
- [ ] Commit: `git add backend/apps/governance backend/apps/labtemplates; git commit -m "feat: add experiment image preparation lifecycle"`.

### Task 6: Freeze Publication Chapters, Tasks, Image Digest, and Resources

**Files:**
- Modify: `backend/apps/experiments/models.py`
- Modify: `backend/apps/experiments/services.py`
- Modify: `backend/apps/experiments/serializers.py`
- Modify: `backend/apps/experiments/views.py`
- Create: `backend/apps/experiments/migrations/0003_publication_chapter_task_snapshot.py`
- Test: `backend/apps/experiments/tests/test_services.py`
- Test: `backend/apps/experiments/tests/test_api.py`

**Interfaces:**
- Consumes: versioned chapter/task models, READY experiment images, resource validation, and existing `TaskPublication` workflow.
- Produces: `precheck_template_version`, `publish_template_version`, immutable publication chapter/task rows, and nested publication responses.

- [ ] Write failing tests for missing chapters/tasks, non-READY image, invalid resource, duplicate order, and snapshot immutability after draft edits.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/experiments/tests -q`; expected only new precheck gaps.
- [ ] Add publication chapter/task rows with source ids, digest, resource snapshot, execution snapshot, and immutable constraints.
- [ ] Lock the version, copy ordered content atomically, compute publication/template digest, then preserve audience freeze/idempotency.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/experiments/tests -q`; expected PASS.
- [ ] Commit: `git add backend/apps/experiments; git commit -m "feat: freeze experiment publication snapshots"`.

### Task 7: Make Student Runtime Provisioning Digest-Only and Resource-Aware

**Files:**
- Modify: `backend/apps/experiments/services.py`
- Modify: `backend/apps/experiments/views.py`
- Modify: `backend/apps/provisioning/ports.py`
- Modify: `backend/apps/provisioning/services.py`
- Modify: `backend/apps/provisioning/tasks.py`
- Modify: `backend/apps/provisioning/models.py`
- Modify: `backend/apps/workspaces/services.py`
- Test: `backend/apps/experiments/tests/test_services.py`
- Test: `backend/apps/provisioning/tests/test_services.py`
- Test: `backend/apps/workspaces/tests/test_services.py`

**Interfaces:**
- Consumes: publication task snapshot, resource admission, existing `RuntimeSpec`, and workspace session creation.
- Produces: `start_task_runtime(task_id, actor, context)`, `stop_task_runtime(runtime_id, actor, context)`, and a student path that never builds/pulls images.

- [ ] Write failing tests for rejecting client image/resource overrides, digest-only `RuntimeSpec`, active-instance reuse, insufficient capacity, and reservation release on create failure.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/experiments/tests/test_services.py education_experiment_platform/apps/provisioning/tests/test_services.py -q`; expected missing snapshot/admission integration.
- [ ] Construct `RuntimeSpec` only from publication fields; reject image, registry, digest, CPU, memory, and adapter in student payload; preserve task transition events.
- [ ] On adapter failure mark job/instance/task failed and release capacity; on success persist external id and create `WorkspaceSession`; reconcile adapter success/database failure via managed labels.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/experiments/tests education_experiment_platform/apps/provisioning/tests education_experiment_platform/apps/workspaces/tests -q`; expected PASS.
- [ ] Commit: `git add backend/apps/experiments backend/apps/provisioning backend/apps/workspaces; git commit -m "feat: provision student runtimes from published digests"`.

### Task 8: Implement Real Local Docker Adapter Behind the Existing Contract

**Files:**
- Modify: `backend/apps/provisioning/adapters.py`
- Modify: `backend/apps/provisioning/ports.py`
- Modify: `backend/apps/provisioning/services.py`
- Modify: `backend/requirements/base.in`
- Modify: `backend/requirements/base.txt`
- Create: `backend/apps/provisioning/tests/test_local_adapter.py`

**Interfaces:**
- Consumes: existing adapter contract and normalized `RuntimeSpec`.
- Produces: `DockerLocalAdapter` that creates/stops/removes real local containers while preserving `RuntimeResult`, idempotency, resource limits, managed labels, endpoint and inventory behavior.

- [ ] Write fake-client contract tests for digest-pinned image, CPU nano-CPU conversion, memory limit, managed labels, idempotent create, stop/destroy, and unmanaged-resource rejection.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/provisioning/tests/test_local_adapter.py -q`; expected failure because local implementation is a protocol stub.
- [ ] Implement a small Docker client boundary using create/start, inspect, stop, remove, and labels; keep SDK imports out of views and use immutable image references.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/provisioning/tests -q`; expected PASS without Docker daemon in CI.
- [ ] Commit: `git add backend/apps/provisioning backend/requirements; git commit -m "feat: add real local docker runtime adapter"`.

### Task 9: Wire Local Compose and Swarm Deployment Configuration

**Files:**
- Modify: `docker-compose.dev.yml`
- Modify: `.env.example`
- Modify: `infrastructure/swarm/stack.yml`
- Modify: `backend/education_experiment_platform/education_experiment_platform/settings/local.py`
- Modify: `backend/education_experiment_platform/education_experiment_platform/settings/prod.py`
- Test: `backend/education_experiment_platform/education_experiment_platform/tests/test_infrastructure_contract.py`
- Test: `backend/education_experiment_platform/education_experiment_platform/tests/test_settings.py`

**Interfaces:**
- Consumes: runtime resolver/capabilities, Local Docker adapter, existing runtime-worker.
- Produces: Fake default local configuration, opt-in Local Docker configuration, and Swarm configuration with runtime-only Docker access, registry settings, node constraints, and immutable-image policy.

- [ ] Write failing tests asserting Fake local default, Docker socket only on runtime-worker, configured local socket, Swarm runtime node label/registry, and production rejection of missing runtime configuration.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/education_experiment_platform/tests/test_infrastructure_contract.py education_experiment_platform/education_experiment_platform/tests/test_settings.py -q`; expected failure for new mode assertions.
- [ ] Implement environment examples and Compose services; keep local registry optional and mount `/var/run/docker.sock` only on runtime-worker.
- [ ] Add Swarm runtime-worker environment injection, node placement constraints, secrets references, and no socket on API/Celery; keep credentials deployment-injected.
- [ ] Run the two infrastructure test files again; expected PASS.
- [ ] Commit: `git add docker-compose.dev.yml infrastructure/swarm/stack.yml .env.example backend/education_experiment_platform/education_experiment_platform/settings; git commit -m "ops: configure local and swarm runtime modes"`.

### Task 10: Add Legacy Conversion, Dual Read/Write, and Migration Commands

**Files:**
- Create: `backend/apps/labtemplates/migrations/0006_legacy_template_content.py`
- Create: `backend/apps/labtemplates/management/commands/migrate_experiment_templates.py`
- Create: `backend/apps/labtemplates/management/commands/revalidate_experiment_images.py`
- Create: `backend/apps/labtemplates/legacy.py`
- Modify: `backend/apps/labtemplates/selectors.py`
- Modify: `backend/apps/experiments/selectors.py`
- Test: `backend/apps/labtemplates/tests/test_migrations.py`
- Test: `backend/apps/labtemplates/tests/test_services.py`
- Test: `backend/apps/experiments/tests/test_api.py`

**Interfaces:**
- Consumes: new models/services from Tasks 2–7 and legacy `TemplateVersion` data.
- Produces: idempotent dry-run migration, `LegacyTemplateAdapter`, default chapter/task generation, and image digest revalidation report.

- [ ] Write tests for no-chapter legacy template, tag-only image, missing image, repeated command execution, and old API reads; assert defaults `实验内容` and `实验任务`.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/labtemplates/tests/test_migrations.py education_experiment_platform/apps/experiments/tests/test_api.py -q`; expected missing conversion/adapter failure.
- [ ] Implement a source/target migration record keyed by legacy public id, bounded batches, `--dry-run`, migrated/skipped/failed counts, default tree creation only when absent, and `MIGRATION_REQUIRED` for unresolved images.
- [ ] Implement new-first selectors and legacy fallback assembly; route legacy writes through new services and synchronize old fields only during the compatibility window.
- [ ] Run the migration and API tests; expected PASS.
- [ ] Commit: `git add backend/apps/labtemplates backend/apps/experiments; git commit -m "feat: add legacy experiment template migration"`.

### Task 11: Add End-to-End Runtime Matrix and Reconciliation Checks

**Files:**
- Create: `backend/apps/provisioning/management/commands/reconcile_runtime_resources.py`
- Modify: `backend/apps/provisioning/tasks.py`
- Create: `backend/apps/provisioning/tests/test_runtime_matrix.py`
- Modify: `backend/apps/experiments/tests/test_api.py`
- Modify: `backend/apps/courses/tests/test_api.py`
- Modify: `backend/education_experiment_platform/education_experiment_platform/tests/test_infrastructure_contract.py`

**Interfaces:**
- Consumes: context, template, image, publication, reservation, runtime, and adapter flows from Tasks 1–10.
- Produces: repeatable end-to-end scenario and reconciliation safe in Fake, Local Docker, and Swarm.

- [ ] Write a parameterized fixture for term → course → teacher/student → template → chapter/task → image → publication → start/stop runtime; vary only adapter implementation and keep business assertions identical.
- [ ] Run: `Set-Location backend; python -m pytest education_experiment_platform/apps/provisioning/tests/test_runtime_matrix.py -q`; expected failure until all flows connect.
- [ ] Implement reconciliation by managed labels: repair uniquely mapped external ids, mark unknown resources `ORPHANED`, release only reservations attached to terminal instances, report-only by default with `--apply` for cleanup.
- [ ] Run: `Set-Location backend/education_experiment_platform; $env:DJANGO_SETTINGS_MODULE='education_experiment_platform.settings.test'; python manage.py check; python manage.py makemigrations --check --dry-run; python -m pytest`; expected checks pass and full tests pass.
- [ ] Run: `Set-Location backend; python -m ruff check education_experiment_platform; python -m mypy education_experiment_platform`; expected no new errors.
- [ ] Commit: `git add backend/apps/provisioning backend/apps/experiments backend/apps/courses; git commit -m "test: verify experiment runtime migration flow"`.

## Verification and Release Gates

1. `Fake Runtime`: 验证完整业务流程和错误状态，不需要 Docker。
2. `Local Docker`: 使用真实镜像和容器验证入口命令、CPU/内存限制、workspace gateway 和销毁释放。
3. `Test Swarm`: 验证 registry digest、节点约束、Service labels、resource reservation/limit 和孤儿资源对账。
4. `Production Swarm`: 只部署与本地测试相同的应用镜像和迁移脚本，替换连接、registry、容量和网络配置。

禁止把本地 container/service id、临时 endpoint、资源预留或 workspace session 直接迁移到服务器；服务器必须重新验证镜像 digest 并创建新的运行实例。

## Plan Self-Review

- 学期/我的课程：Task 2。
- 章节/任务：Task 3。
- CPU/内存资源 profile 与预留：Task 4。
- 构建镜像/已有镜像、扫描、digest：Task 5。
- 发布快照：Task 6。
- 学生只创建 digest 运行实例：Task 7。
- Fake/Local Docker/Swarm：Tasks 1、8、9、11。
- 旧模型迁移与双读/双写：Task 10。
- 测试与本地到服务器验收：Task 11 和 Verification gates。

No placeholder steps remain; every task identifies concrete files, interfaces, tests, commands, and commit boundaries.
