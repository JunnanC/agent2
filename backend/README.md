# Backend

The only supported Django project is `backend`.
Application packages, the management entry point, and Django settings live
directly below this directory:

```text
backend/
|-- manage.py
|-- apps/
|-- education_experiment_platform/
|   `-- settings/
|-- requirements/
|-- Dockerfile
`-- pyproject.toml
```

## Local commands

Run Django commands from the canonical project directory:

```powershell
Set-Location backend
$env:DJANGO_SETTINGS_MODULE = "education_experiment_platform.settings.test"
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest
```

Run static checks from `backend`:

```powershell
Set-Location backend
python -m ruff check apps education_experiment_platform
python -m mypy apps education_experiment_platform
```

The repository root `.env.example` is the single backend and infrastructure
configuration template. Local integration uses `docker-compose.dev.yml`; the
production-candidate Swarm definition is `infrastructure/swarm/stack.yml` and
requires separate acceptance in a real deployment environment.

Current management commands use functional names, such as `seed_accounts_e2e`,
`seed_simulated_experiment`, `reconcile_archives`, and `verify_workspace_token_boundary`.
In disposable local/integration/test environments, `python manage.py rename_seed_labels`
updates old seed display names through CAS without changing identifiers or relations.
See the
[command migration table](../docs/naming-conventions.md) and
[script inventory](../scripts/README.md) for their scope and prerequisites.

The backend image uses Python 3.14 and copies only the canonical Django project.
MySQL stores business facts, Redis provides cache and Celery transport, MongoDB
stores runtime logs only, and MinIO stores controlled object content.
