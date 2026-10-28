# Education Agent Platform

Greenfield implementation of the teaching cloud experiment platform. The repository contains the P00-P13 business capabilities, P14 runtime adaptation, and follow-on P15/P16 work. Local Compose and single-node runtime checks are available; production-candidate HA, recovery, performance, external dependencies, and full-journey acceptance still require the real staging environment.

The documentation entry point is [`documents/项目资料索引.md`](documents/项目资料索引.md). The dated status summary is [`documents/项目现状快照_2026-10-15.md`](documents/项目现状快照_2026-10-15.md).

## Local prerequisites

- Docker Desktop 28+ with Compose v2
- Node.js 24+ for host-side frontend commands
- Python 3.14 for host-side backend commands

## Start

> 当前工作树的 `frontend/` 目录处于删除状态，因此下面的 Compose 构建命令在恢复前端源码前不能作为“当前可执行”入口；Git 基线仍包含旧的 `user-web` 前端，Nginx 工作区则已改为 `student-web`。请先阅读 [`documents/项目现状快照_2026-10-15.md`](documents/项目现状快照_2026-10-15.md)。

```powershell
Copy-Item .env.example .env
docker compose --profile p14 -f docker-compose.dev.yml up --build
```

The edge entry point listens on port `8080`. Use the hostnames below so portal cookies and trusted host mapping remain isolated:

- `http://student.localhost:8080`
- `http://teacher.localhost:8080`
- `http://admin.localhost:8080`
- `http://api.localhost:8080` (machine API only; no web application)

Run `./scripts/verify-p13-c.ps1` for the P13 local gate after the required source tree is present. P12 and earlier isolated integration gates remain available as `verify-pXX-integration.ps1`. P14 deployment, rollback, evidence collection, and bounded runtime smoke commands are under `scripts/p14-*.ps1` and `scripts/p14-runtime-smoke.py`; P15 and P16 entry points are listed in the project status snapshot. Architecture and stage requirements live under `documents/`.

## Demo data（演示数据集）

`seed_demo_full` generates a complete, disposable demo dataset for all three portals (accounts, courses, enrollment, content, governance, templates, publications, full task lifecycle, reports, reviews, archives, agents, notifications, analytics). It only runs when `APP_ENV ∈ {local, integration, test}` or `DEBUG=True`, is idempotent (fixed `demo-*`/`DEMO-*` namespace), and can be fully purged without touching `P03-DEMO-001` or other seed data:

```powershell
# inside the Compose stack (one-shot tool service)
docker compose --profile tools run --rm --no-deps core-check python manage.py seed_demo_full
# --scale small|demo|large (default demo), also demo accounts listing

# purge only demo rows (keeps every other seed and the platform quota).
# The runtime app user has no DELETE grant by design; purge must run as the
# migration principal (compose default: local-migration-password).
docker exec -e MYSQL_USER=edu_platform_migration -e MYSQL_PASSWORD=local-migration-password `
  edu-platform-p14-django-1 python manage.py seed_demo_full --purge
```

Demo accounts (password from `DEMO_SEED_PASSWORD`, default `Demo-Seed-Only-2026!`; change it via `--password` or `.env`):

| Portal | Login | Username |
|---|---|---|
| `admin.localhost` | `admin.demo@example.edu` | `demo-admin` |
| `teacher.localhost` | `teacher-01.demo@example.edu` | `demo-teacher-01` … |
| `student.localhost` | `student-001.demo@example.edu` | `demo-student-001` … |

Task states cover the full experiment lifecycle: ASSIGNED → PROVISIONING → READY → IN_PROGRESS → REPORT_DRAFT → UNDER_REVIEW → APPROVED/REJECTED → ARCHIVING → COMPLETED, plus CANCELLED/EXPIRED/FAILED samples, extension requests, agent sessions with a pending tool approval, and analytics projections rebuilt from the seeded facts. Nightly scale presets: `small` (unit tests), `demo` (default), `large` (parameterized). See `backend/education_experiment_platform/apps/core/demo/` for the builder layout.

For the backend-only local boundary, run `./scripts/verify-backend-local.ps1` with Python 3.14. The current gate passes with only the known frontend-source contract node deselected; it does not certify the missing frontend or the full Nginx-to-Kong browser journey. The bounded real Docker/MySQL evidence from 2026-10-15 is under `evidence/backend-local/20261015-195717/`.

The backend has one canonical Django project at `backend/education_experiment_platform`.
All applications, settings, migrations, tests, and management commands belong under that
directory; parallel `backend/apps` or `backend/config` trees are not supported.

## Development and deployment workflow

Business development may continue locally after the P00 local gate passes. P01-P13 must still proceed in order and use the real local APIs and Compose data services; a local pass is not a production or HA certification.

Real DNS/TLS, three-manager Swarm, external persistent services, failure recovery, and production-candidate validation remain environment-gated. The authoritative execution rules and status labels are documented in [`documents/开发任务拆分/00A_本地开发与最终真实部署约定.md`](documents/开发任务拆分/00A_本地开发与最终真实部署约定.md).
