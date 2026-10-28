$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = if (Test-Path "$root\.venv\Scripts\python.exe") { "$root\.venv\Scripts\python.exe" } else { 'py' }
$pythonArgs = if ($python -eq 'py') { @('-3.14') } else { @() }
$env:APP_VERSION = '0.13.0-p13'
$env:OPENAPI_REVISION = 'v2-p13'

Push-Location "$root\backend\education_experiment_platform"
try {
    $env:DJANGO_SETTINGS_MODULE = 'education_experiment_platform.settings.test'
    & $python @pythonArgs manage.py check
    & $python @pythonArgs manage.py makemigrations --check --dry-run
    & $python @pythonArgs -m pytest apps/integrations/tests/test_p13_integrations.py
    & $python @pythonArgs manage.py spectacular --format openapi-json --validate --file "$root\backend\openapi-p13-b.json"
    if ($LASTEXITCODE -ne 0) { throw 'P13-B backend gates failed.' }
} finally { Pop-Location }

Push-Location "$root\backend"
try { & $python @pythonArgs -m ruff check education_experiment_platform/apps/integrations; if ($LASTEXITCODE -ne 0) { throw 'P13-B Ruff failed.' } } finally { Pop-Location }

Push-Location "$root\frontend"
try {
    & npm.cmd run generate:api
    & npx.cmd tsc -p apps/student-web/tsconfig.json --noEmit
    & npx.cmd tsc -p apps/teacher-web/tsconfig.json --noEmit
    & npx.cmd tsc -p apps/admin-web/tsconfig.json --noEmit
    if ($LASTEXITCODE -ne 0) { throw 'P13-B frontend typecheck failed.' }
} finally { Pop-Location }

& docker compose -f "$root\docker-compose.dev.yml" config --quiet
if ($LASTEXITCODE -ne 0) { throw 'P13-B Compose configuration validation failed.' }
Write-Output 'P13-B local gates passed. Real environment remains pending acceptance.'
