# Education Agent Platform

Greenfield implementation of the teaching cloud experiment platform. The current deliverable is P06: experiment publications, frozen audiences, prerequisites, personal tasks, state transitions, and extension decisions on top of the P00-P05 foundation.

## Local prerequisites

- Docker Desktop 28+ with Compose v2
- Node.js 24+ for host-side frontend commands
- Python 3.14 for host-side backend commands

## Start

```powershell
Copy-Item .env.example .env
docker compose -f docker-compose.dev.yml up --build
```

The edge entry point listens on port `8080`. Use the hostnames below so portal cookies and trusted host mapping remain isolated:

- `http://user.localhost:8080`
- `http://teacher.localhost:8080`
- `http://admin.localhost:8080`
- `http://api.localhost:8080` (machine API only; no web application)

Run `./scripts/verify-p06.ps1` for the P06 static checks and `./scripts/verify-p06-integration.ps1` for isolated MySQL/Redis/MinIO/ClamAV and real-entry checks. Architecture and stage requirements live under `documents/`.

The backend has one canonical Django project at `backend/education_experiment_platform`.
All applications, settings, migrations, tests, and management commands belong under that
directory; parallel `backend/apps` or `backend/config` trees are not supported.

## Development and deployment workflow

Business development may continue locally after the P00 local gate passes. P01-P13 must still proceed in order and use the real local APIs and Compose data services; a local pass is not a production or HA certification.

Real DNS/TLS, three-manager Swarm, external persistent services, failure recovery, and production-candidate validation are deferred to the final deployment window and closed by P14. The authoritative execution rules and status labels are documented in [`documents/开发任务拆分/00A_本地开发与最终真实部署约定.md`](documents/开发任务拆分/00A_本地开发与最终真实部署约定.md).
