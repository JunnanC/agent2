> 历史命令说明（2026-10-30）：本文保留原开发阶段编号及当时执行记录。当前脚本、管理命令和 Compose 配置档已按功能重命名，执行前请查看[现入口迁移表](../../naming-conventions.md)；原命令不作为当前可用性证明。

# Real Local Backend Acceptance Repair Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the backend unit-test gate and the real Docker-local acceptance path reliable without hiding the current frontend deletion or claiming a full repository pass.

**Architecture:** Keep unit tests on the in-memory `DockerLocalProtocolStub` through `settings.test`, while Compose and real local acceptance continue to use `DockerLocalAdapter`. Preserve the safe historical course migration helper and add a forward state migration for the model default drift. Make the local smoke resolve the actual image digest, run the 真实工作区 image contract from inside the created container, and use an isolated Compose project/network for MySQL-backed evidence.

**Tech Stack:** Python 3.14, Django 6.1.1, pytest/pytest-django, MySQL 8.4, Docker Engine 28.5+, Docker Compose v2, PowerShell.

**Spec:** Current findings are recorded in `docs/项目现状快照_2026-10-15.md`, `docs/superpowers/plans/swarm-local-test-fixes.md`, `runtime/algorithm-workspace/README.md`, and `docs/开发任务拆分/00A_本地开发与最终真实部署约定.md`.

## Global Constraints

- Preserve the current uncommitted deletion of `frontend/`; do not restore, rename, fabricate, or conditionally skip frontend source files.
- `LOCAL_RUNTIME_MODE=STUB` is test-only. Compose, integration settings, and real local acceptance must remain `LOCAL_RUNTIME_MODE=REAL`.
- Do not change production requirements: production still requires `RUNTIME_MODE=swarm` and an explicit adapter configuration.
- Keep digest-pinned image selection, managed-resource labels, resource limits, 真实工作区 capability/auth semantics, and cleanup ownership checks.
- Do not rewrite migration `0005` or `0006` merely to silence `makemigrations`; the historical helper is intentionally safe before the generated column exists.
- Do not widen database columns or change business state-machine semantics.
- The full repository/分析与集成-C and frontend Playwright paths remain blocked until the frontend source tree and checked-in frontend OpenAPI artifact are restored.
- Do not overwrite `.env`, commit changes, or create a branch while executing this plan.

## Baseline and Root Causes

Evidence collected on October 15, 2026:

- Backend pytest baseline: `342 passed, 4 failed, 1 skipped`.
- Three provisioning failures resolve `DOCKER_LOCAL` as a real adapter because `settings.test` inherits `LOCAL_RUNTIME_MODE=REAL`; on Windows the default Unix Docker socket is unavailable. The intended in-memory stub tests therefore fail before exercising their service contract.
- One infrastructure-contract failure is `test_frontends_are_independent_build_entries`; the working tree has 103 uncommitted frontend deletions, so the three expected frontend app directories are absent.
- `makemigrations --check --dry-run` proposes `courses/0007_alter_course_term` because the current model serializes `current_term_default` while historical migration `0005` serializes a migration-local helper. The `0005` helper uses `.only("pk")` so it does not query the future `current_slot` column during fresh migrations; reverting it to the model callable is unsafe.
- `scripts/verify/local-runtime-smoke.py` uses a synthetic `sha256:aaaa...` digest, hardcodes `PidsLimit=64` although the adapter default is `128`, and probes `tasks.<container>` from the Windows host. The latter cannot resolve Docker-internal DNS from the host.
- The current 真实工作区 image contract exposes only `/healthz` and authenticated `/webide/`; `/notebook/`, `/terminal/`, and `/preview/` are unsupported and must return `404`. `/webide/` requires `X-Workspace-Upstream-Token`; missing or incorrect tokens must return `403`.
- Docker Engine `28.5.1` is available through `npipe:////./pipe/docker_engine`; the local algorithm-workspace image and an existing runtime network are available.

## File Map

- Modify `backend/education_experiment_platform/education_experiment_platform/settings/test.py` to isolate unit tests.
- Modify `backend/education_experiment_platform/education_experiment_platform/tests/test_settings.py` and the relevant provisioning contract test to lock the isolation boundary.
- Create `backend/apps/courses/migrations/0007_alter_course_term.py` as a forward state migration; do not modify `0005` or `0006` for this repair.
- Modify `scripts/verify/local-runtime-smoke.py` to resolve the real image digest, use 真实工作区 capabilities, and run the HTTP contract inside the created container.
- Modify or extend `backend/apps/provisioning/tests/test_local_adapter.py` for resource/config assertions.
- Create `scripts/verify/backend-local.ps1` with one exact frontend-node deselection.
- Update `README.md` and `docs/项目现状快照_2026-10-15.md` with the bounded backend gate and evidence limitations.
- Create disposable evidence under the concrete `$runId` directory `evidence/backend-local/$runId/` only during the real Compose verification; never record workspace tokens or secrets.

### Task 1: Isolate unit tests from the real local Docker adapter

**Files:**
- Modify `backend/education_experiment_platform/education_experiment_platform/settings/test.py`.
- Modify `backend/education_experiment_platform/education_experiment_platform/tests/test_settings.py`.
- Modify `backend/apps/provisioning/tests/test_adapter_contract.py` only where an explicit real-adapter selection needs to be documented.
- Test `backend/apps/provisioning/tests/test_services.py` and the adapter contract tests.

**Interfaces:**
- Test settings expose `LOCAL_RUNTIME_MODE = "STUB"`.
- `runtime_for_driver("DOCKER_LOCAL")` returns the in-memory protocol stub under test settings.
- Tests that intentionally exercise the real adapter resolver opt into `LOCAL_RUNTIME_MODE="REAL"` and continue to mock `_build_client`; they do not require Docker Desktop.
- `base.py`, `integration.py`, `local.py`, `prod.py`, and Compose defaults remain unchanged.

- [ ] **Step 1: Add the red settings regression test.**

  Add `SettingsTests.test_unit_test_settings_use_the_local_protocol_stub` asserting `settings.LOCAL_RUNTIME_MODE == "STUB"`. Run it from `backend/education_experiment_platform` with the backend interpreter:

  ```powershell
  ..\.venv\Scripts\python.exe -m pytest education_experiment_platform/education_experiment_platform/tests/test_settings.py::SettingsTests::test_unit_test_settings_use_the_local_protocol_stub -q
  ```

  Before the settings change it must fail with the inherited `REAL` value.

- [ ] **Step 2: Set the test-only override.**

  Append `LOCAL_RUNTIME_MODE = "STUB"` to `education_experiment_platform/settings/test.py`. Do not alter the base setting or Compose environment.

- [ ] **Step 3: Make direct real-adapter coverage explicit.**

  Add `LOCAL_RUNTIME_MODE="REAL"` to the existing `test_local_mode_resolves_the_real_local_adapter` override if needed for readability, while retaining its patched `_build_client`. Do not change `runtime_adapter_for` semantics: it is the explicit configured-adapter path, whereas `runtime_for_driver` is the mode-sensitive path under test.

- [ ] **Step 4: Run the focused regression set.**

  ```powershell
  ..\.venv\Scripts\python.exe -m pytest `
    education_experiment_platform/education_experiment_platform/tests/test_settings.py `
    education_experiment_platform/apps/provisioning/tests/test_adapter_contract.py `
    education_experiment_platform/apps/provisioning/tests/test_services.py -q
  ```

  The three current stub-resolution/socket failures must disappear. The focused tests must not require a live Docker socket.

- [ ] **Step 5: Verify production-mode rejection is unchanged.**

  Run the settings suite and retain the assertions that production rejects fake runtime configuration without the required adapter setup. Do not weaken production validation to make test settings pass.

### Task 2: Repair migration state drift with a forward migration

**Files:**
- Create `backend/apps/courses/migrations/0007_alter_course_term.py`.
- Test `backend/apps/courses/tests/test_models.py`.
- Verify, but do not rewrite, `backend/apps/courses/migrations/0005_academicterm_course_term.py` and `0006_academicterm_current_slot.py`.

**Interfaces:**
- `AcademicTerm.current_slot` remains a nullable persisted generated field.
- `courses_term_one_current_uniq` remains the normal unique constraint on `current_slot`.
- The safe `0005` migration-local helper remains stable for historical execution before `0006` adds `current_slot`.
- The current model state is aligned through a new forward `0007` state migration.

- [ ] **Step 1: Capture the drift with explicit test settings.**

  From `backend/education_experiment_platform`, run:

  ```powershell
  $env:DJANGO_SETTINGS_MODULE = 'education_experiment_platform.settings.test'
  ..\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --verbosity=3
  ```

  Confirm the proposed operation is exactly `courses/0007_alter_course_term`, depending on `0006_academicterm_current_slot`, and changes only `Course.term` to the model callable `apps.courses.models.current_term_default`.

- [ ] **Step 2: Add the generated forward migration.**

  Create `0007_alter_course_term.py` with the exact Django-generated `AlterField` operation and dependency on `0006_academicterm_current_slot`. Do not import the current callable into `0005`; do not remove the `.only("pk")` helper; do not change the generated-column or uniqueness operations in `0006`.

- [ ] **Step 3: Prove the drift is gone.**

  Re-run `manage.py makemigrations --check --dry-run` with `settings.test`; it must exit `0` and report no changes. Run `showmigrations courses` and confirm `0005`, `0006`, and `0007` are ordered and present.

- [ ] **Step 4: Run course regression tests.**

  ```powershell
  ..\.venv\Scripts\python.exe -m pytest `
    apps/courses/tests/test_models.py `
    apps/courses/tests/test_services.py `
    apps/courses/tests/test_api.py -q
  ```

  Confirm the current-term generated-slot tests still prove one current term and unlimited non-current `NULL` slots.

- [ ] **Step 5: Verify fresh historical migration behavior in disposable MySQL.**

  In the Compose task, create a brand-new MySQL volume and run the full migration chain from `0001` through `0007`. The migration must complete without querying a missing `current_slot` column. This is the acceptance proof for preserving the `0005` helper; a SQLite-only migration check is not sufficient.

### Task 3: Make the real local runtime smoke match the 真实工作区 image contract

**Files:**
- Modify `scripts/verify/local-runtime-smoke.py`.
- Modify or extend `backend/apps/provisioning/tests/test_local_adapter.py`.
- Reuse, without weakening, `runtime/algorithm-workspace/tests/smoke.py` for the inside-container HTTP/image contract.

**Interfaces:**
- `T10_RUNTIME_IMAGE` defaults to `edu-platform-algorithm-workspace:local`.
- The script inspects that tag through the Docker API, extracts an immutable `RepoDigests` `sha256` value, and builds `RuntimeSpec.image_digest` from it. No synthetic digest or mutable `:latest` reference is allowed.
- The smoke resource contract defaults to `memory_mb=768`, `cpu_millicores=1000`, and `pids_limit=128`, matching the current 真实工作区 hardened image gate; `T10_PIDS_LIMIT` may override only the explicit PID assertion.
- The created runtime advertises `webide=true`, `notebook=false`, `terminal=false`, and `preview=false`.
- HTTP assertions run inside the created runtime through Docker exec, never through the host’s `tasks.<container>` DNS name.

- [ ] **Step 1: Add adapter-level resource coverage.**

  Extend the local adapter test fixture to assert that the configured `pids_limit` reaches Docker host configuration and that local image specs become `<repository>@<sha256 digest>`. Keep the existing fake-client tests isolated from Docker Desktop.

- [ ] **Step 2: Resolve the actual local image digest.**

  In the smoke script, construct the `DockerLocalAdapter` first, call `inspect_image(T10_RUNTIME_IMAGE)`, select the first `RepoDigests` value containing `@sha256:`, and derive the repository from the selected repo-digest rather than by splitting a tag. Fail clearly if no immutable digest is available. Use the adapter’s `LOCAL_DOCKER_HOST` client, which is `npipe:////./pipe/docker_engine` on Windows.

- [ ] **Step 3: Replace the obsolete capability and resource assertions.**

  Set the `RuntimeSpec` capability map to WebIDE-only, assert `HostConfig.PidsLimit == 128` by default, and keep read-only rootfs, `CapDrop=ALL`, `no-new-privileges`, memory, CPU, managed-label, idempotent-create, judge-status, and cleanup assertions. Use a unique per-run `config_ref` and task id so cleanup and inventory checks cannot consume or judge unrelated pre-existing managed resources.

- [ ] **Step 4: Execute the existing 真实工作区 HTTP probe inside the runtime.**

  After the adapter creates the container, stage `runtime/algorithm-workspace/tests/smoke.py` into its writable `/tmp` tmpfs using Docker `put_archive`, then run `python /tmp/workspace-smoke.py` using Docker `exec_create`/`exec_start` and inspect the exec exit code. Parse its JSON result without printing the upstream token. This probe must prove:

  - `/healthz` returns `200` and `ok`;
  - `/webide` redirects to `/webide/`;
  - missing and incorrect `X-Workspace-Upstream-Token` return `403`;
  - the correct token returns code-server HTML, a static asset, and a WebSocket `101` upgrade;
  - `/notebook/`, `/terminal/`, and `/preview/` return `404`;
  - the runtime has no published host port and retains the 真实工作区 UID, listener, and read-only-rootfs checks.

- [ ] **Step 5: Retain judge and idempotency coverage.**

  Keep the correct, wrong, timeout, suite-timeout, and resource-exceeded judge cases with expected statuses `PASSED`, `FAILED`, `TIMEOUT`, `TIMEOUT`, and `RESOURCE_EXCEEDED`. Destroy the workspace twice, then assert zero owned workspaces, judge containers, workspace volumes, and secret volumes for the unique smoke `config_ref`.

- [ ] **Step 6: Run the real smoke with the correct interpreter and Windows socket.**

  From the repository root, use the backend Python 3.14 interpreter, not the root Python 3.13 environment:

  ```powershell
  $env:PYTHONPATH = "$PWD\backend\education_experiment_platform"
  $env:LOCAL_DOCKER_HOST = 'npipe:////./pipe/docker_engine'
  $env:T10_RUNTIME_IMAGE = 'edu-platform-algorithm-workspace:local'
  $env:T10_RUNTIME_NETWORK = 'edu-platform-p14_runtime'
  .\backend\.venv\Scripts\python.exe scripts\verify\local-runtime-smoke.py
  ```

  The result must include the inside-container 真实工作区 probe, the five judge statuses, and zero owned resources after cleanup. The smoke is bounded backend/runtime evidence; it is not a proof of the full Nginx-to-Kong-to-Django browser journey.

### Task 4: Add a backend-only local gate with a precise frontend boundary

**Files:**
- Create `scripts/verify/backend-local.ps1`.
- Modify `README.md`.
- Modify `docs/项目现状快照_2026-10-15.md`.

**Interfaces:**
- The gate runs Django checks, migration drift, backend pytest, OpenAPI schema validation, Ruff, mypy, and Compose config validation.
- It deselects exactly this missing-source node and nothing else:
  `education_experiment_platform/education_experiment_platform/tests/test_infrastructure_contract.py::test_frontends_are_independent_build_entries`.
- It validates generated OpenAPI but does not compare it to missing `frontend/openapi.json`.
- It reports that a backend-only pass is not a full repository/frontend pass.

- [ ] **Step 1: Implement robust Python 3.14 resolution.**

  Prefer `backend\.venv\Scripts\python.exe`; validate that candidate imports Django, pytest, Ruff, and mypy and reports Python `3.14`. Fall back to `py -3.14`. Do not select the root `.venv` merely because it exists; the observed root interpreter is Python `3.13.9`.

- [ ] **Step 2: Implement the backend checks with cleanup.**

  Set `DJANGO_SETTINGS_MODULE=education_experiment_platform.settings.test`, run `manage.py check`, `manage.py makemigrations --check --dry-run`, pytest with the one exact `--deselect` node, and `manage.py spectacular --format openapi-json --validate --file $openApiFile`. From `backend`, run Ruff and mypy. Run `docker compose -f docker-compose.dev.yml config --quiet`. Save and restore all environment variables and delete `$openApiFile` in `finally`.

- [ ] **Step 3: Prove the exclusion is narrow before using the gate.**

  Run the infrastructure contract module directly and record the existing `22 passed, 1 failed` result. Do not edit that test, skip the entire module, or fabricate frontend directories.

- [ ] **Step 4: Run and document the backend-only gate.**

  ```powershell
  .\scripts\verify\backend-local.ps1
  ```

  The script must exit successfully only when every backend check passes and the single known frontend node is deselected. Its final output must explicitly name the remaining full-gate limitation.

### Task 5: Verify against isolated real Compose/MySQL services and record evidence

**Files:**
- Create `evidence/backend-local/$runId/summary.json`.
- Create `evidence/backend-local/$runId/compose-ps.txt`.
- Create `evidence/backend-local/$runId/runtime-smoke.json`.
- Create `evidence/backend-local/$runId/reconcile-report.json`.
- Modify `docs/项目现状快照_2026-10-15.md` with the bounded result.

**Interfaces:**
- The database under test is disposable MySQL 8.4, not SQLite.
- The runtime worker uses `LOCAL_RUNTIME_MODE=REAL`, the Linux Docker socket mounted by Compose, an explicitly isolated runtime network, and an adapter config whose `runtime_network` matches that network.
- Reconciliation is report-only; never pass `--apply`.
- A reconciliation result is valid evidence only when it contains the expected adapter row and has no skipped-adapter error; an empty adapter list or exit code `0` alone is not a pass.

- [ ] **Step 1: Allocate isolated names, ports, subnet, and evidence directory.**

  In PowerShell, set `$root = (Get-Location).Path`, `$runId = Get-Date -Format 'yyyyMMdd-HHmmss'`, `$project = "edu-platform-backend-local-$PID"`, `$runtimeNetwork = "${project}_runtime"`, and `$evidenceRoot = Join-Path $root "evidence/backend-local/$runId"`. Choose an unused `APP_NETWORK_SUBNET` after checking Docker networks, and choose an unused `FLUENTD_HOST_PORT` because the selected Django/Celery slice starts `fluent-bit` with a host port. Save every overridden environment variable and restore it in `finally`; do not edit `.env`.

- [ ] **Step 2: Start only the backend/runtime Compose slice.**

  Set `LOCAL_RUNTIME_NETWORK=$runtimeNetwork`, `RUNTIME_ADAPTER_CONFIGS` to compact JSON containing `runtime/local-docker` with that network and `pids_limit=128`, `LOCAL_RUNTIME_MODE=REAL`, and `LOCAL_DOCKER_HOST=unix:///var/run/docker.sock`. Start the disposable project with a fresh volume:

  ```powershell
  docker compose --profile runtime -p $project -f docker-compose.dev.yml up --build -d `
    migrate mysql-grants django celery celery-beat runtime-worker workspace-gateway
  ```

  This intentionally omits `nginx` and the frontend build. Verify `docker compose ... ps` shows the selected services healthy/completed and that the project runtime network has the expected isolated name and subnet.

- [ ] **Step 3: Prove fresh MySQL migration and Django health.**

  Run inside the disposable `django` container and save output under `$evidenceRoot`:

  ```powershell
  docker compose --profile runtime -p $project -f docker-compose.dev.yml exec -T django python manage.py check
  docker compose --profile runtime -p $project -f docker-compose.dev.yml exec -T django python manage.py makemigrations --check --dry-run
  docker compose --profile runtime -p $project -f docker-compose.dev.yml exec -T django curl -fsS http://127.0.0.1:8000/api/v2/health
  docker compose --profile runtime -p $project -f docker-compose.dev.yml exec -T workspace-gateway curl -fsS http://127.0.0.1:8080/healthz
  ```

  Require successful migration/check commands, HTTP `200` health responses, and the expected API revision where the response exposes it. A brand-new MySQL volume must have applied `courses.0007` without a missing-column error.

- [ ] **Step 4: Seed exactly one real local adapter row for reconciliation.**

  In the disposable database, create/update one enabled `DOCKER_LOCAL` container adapter with code `LOCAL-DOCKER-ACCEPTANCE`, `config_ref=runtime/local-docker`, healthy metadata, and the isolated Compose runtime network represented by the environment configuration. Do not rely on a fresh database accidentally containing adapters. Do not seed frontend data or claim a complete 真实工作区 business journey from this row. Use the exact disposable shell seed below:

  ```powershell
  $adapterCode = 'LOCAL-DOCKER-ACCEPTANCE'
  $seed = "from django.utils import timezone; from apps.governance.models import RuntimeAdapter; RuntimeAdapter.objects.update_or_create(code='$adapterCode', defaults={'name':'Disposable local Docker acceptance','runtime_type':'CONTAINER','driver':'DOCKER_LOCAL','status':'ENABLED','config_ref':'runtime/local-docker','health_status':'HEALTHY','node_count':1,'capacity_cpu_millicores':8000,'available_cpu_millicores':8000,'capacity_memory_mb':16384,'available_memory_mb':16384,'last_health_at':timezone.now(),'change_reason':'backend local acceptance'})"
  docker compose --profile runtime -p $project -f docker-compose.dev.yml exec -T django python manage.py shell -c $seed
  ```

- [ ] **Step 5: Run report-only reconciliation and assert meaningful evidence.**

  ```powershell
  docker compose --profile runtime -p $project -f docker-compose.dev.yml exec -T runtime-worker `
    python manage.py reconcile_runtime_resources --adapter-code $adapterCode
  ```

  Save the JSON to `reconcile-report.json`; assert `apply=false`, the expected adapter/config reference is present, `errors=[]`, and the report is valid JSON. Confirm no database/runtime mutation occurred.

- [ ] **Step 6: Run the corrected host-driven smoke against the Compose runtime network.**

  From the host, run `scripts/verify/local-runtime-smoke.py` with `LOCAL_DOCKER_HOST=npipe:////./pipe/docker_engine`, the backend interpreter, the local image, and `$runtimeNetwork`; save stdout as `runtime-smoke.json`. The smoke must use Docker exec for 真实工作区 HTTP checks and must leave zero resources for its unique config reference. Do not use host `urllib` against `tasks.<container>` and do not print the token.

- [ ] **Step 7: Tear down and verify ownership cleanup.**

  After evidence is copied, run:

  ```powershell
  docker compose --profile runtime -p $project -f docker-compose.dev.yml down --remove-orphans --volumes
  ```

  Verify no containers, networks, or volumes labeled with the disposable Compose project remain. Restore all PowerShell environment variables in `finally`. If cleanup fails, record exact remaining resource names and mark the acceptance run failed; do not report a pass.

- [ ] **Step 8: Record the bounded conclusion.**

  Mark the backend local acceptance as `本地通过（真实环境待验收）` only when the backend-only gate, fresh MySQL migration, internal service health, meaningful reconciliation, real Docker smoke, and ownership cleanup all pass. Keep the repository-wide/full-journey status blocked until frontend sources and `frontend/openapi.json` are restored and the full `scripts/verify/operations-static.ps1` plus Playwright path is rerun.

## Final Verification Checklist

- [ ] Unit settings use `STUB`; Compose/integration remains `REAL`.
- [ ] Migration drift is resolved by forward `0007`; `0005` remains safe for historical execution before `current_slot` exists.
- [ ] Focused provisioning tests and the backend-only gate pass with exactly one frontend node deselected.
- [ ] Real smoke proves digest-pinned creation, readiness, 真实工作区 authenticated WebIDE/unsupported-capability behavior, judge outcomes, idempotent replay, and complete owned-resource cleanup.
- [ ] Fresh MySQL applies the complete migration chain and report-only reconciliation proves a real configured adapter with no skipped errors.
- [ ] The final report distinguishes bounded backend/local evidence from the still-blocked frontend and full repository journey.
