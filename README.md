# Education Agent Platform

Greenfield implementation of the teaching cloud experiment platform. The working tree contains the P00-P13 business capabilities and the P14 Docker Swarm runtime adapter. P13 local gates and the single-node runtime contract can be verified locally; P14 production-candidate HA, recovery, performance, and full-journey acceptance still require the real staging environment.

## Local prerequisites

- Docker Desktop 28+ with Compose v2
- Node.js 24+ for host-side frontend commands
- Python 3.14 for host-side backend commands

## Start

```powershell
Copy-Item .env.example .env
docker compose --profile p14 -f docker-compose.dev.yml up --build
```

The edge entry point listens on port `8080`. Use the hostnames below so portal cookies and trusted host mapping remain isolated:

- `http://student.localhost:8080`
- `http://teacher.localhost:8080`
- `http://admin.localhost:8080`
- `http://api.localhost:8080` (machine API only; no web application)

Run `./scripts/verify-p13-c.ps1` for the current local static gate. P12 and earlier isolated integration gates remain available as `verify-pXX-integration.ps1`; P13 browser coverage is in `frontend/e2e/p13.spec.ts`. P14 deployment, rollback, evidence collection, and bounded runtime smoke commands are under `scripts/p14-*.ps1` and `scripts/p14-runtime-smoke.py`. Architecture and stage requirements live under `documents/`.

The backend has one canonical Django project at `backend/education_experiment_platform`.
All applications, settings, migrations, tests, and management commands belong under that
directory; parallel `backend/apps` or `backend/config` trees are not supported.

## Development and deployment workflow

Business development may continue locally after the P00 local gate passes. P01-P13 must still proceed in order and use the real local APIs and Compose data services; a local pass is not a production or HA certification.

Real DNS/TLS, three-manager Swarm, external persistent services, failure recovery, and production-candidate validation are deferred to the final deployment window and closed by P14. The authoritative execution rules and status labels are documented in [`documents/开发任务拆分/00A_本地开发与最终真实部署约定.md`](documents/开发任务拆分/00A_本地开发与最终真实部署约定.md).
