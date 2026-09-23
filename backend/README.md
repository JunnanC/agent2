# Backend

The only supported Django project is `backend/education_experiment_platform`.
Do not create parallel `backend/apps`, `backend/config`, or root-level backend
`manage.py` trees. Application packages and Django settings live below the
canonical project directory:

```text
backend/
|-- education_experiment_platform/
|   |-- manage.py
|   |-- apps/
|   `-- education_experiment_platform/
|       `-- settings/
|-- requirements/
|-- Dockerfile
`-- pyproject.toml
```

## Local commands

Run Django commands from the canonical project directory:

```powershell
Set-Location backend/education_experiment_platform
$env:DJANGO_SETTINGS_MODULE = "education_experiment_platform.settings.test"
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest
```

Run static checks from `backend`:

```powershell
Set-Location backend
python -m ruff check education_experiment_platform
python -m mypy education_experiment_platform
```

The repository root `.env.example` is the single backend and infrastructure
configuration template. Local integration uses `docker-compose.dev.yml`; the
production-candidate Swarm definition is `infrastructure/swarm/stack.yml` and
remains subject to the P14 real-environment gate.

The backend image uses Python 3.14 and copies only the canonical Django project.
MySQL stores business facts, Redis provides cache and Celery transport, MongoDB
stores runtime logs only, and MinIO stores controlled object content.
