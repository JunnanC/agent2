$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = if (Test-Path "$root\.venv\Scripts\python.exe") { "$root\.venv\Scripts\python.exe" } else { 'python' }
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source

Push-Location "$root\backend\education_experiment_platform"
try {
    $env:DJANGO_SETTINGS_MODULE = 'education_experiment_platform.settings.test'
    $env:APP_VERSION = '0.8.0-p07'
    $env:OPENAPI_REVISION = 'v2-p07'
    & $python manage.py check
    & $python manage.py makemigrations --check --dry-run
    & $python -m pytest
    & $python manage.py spectacular --format openapi-json --validate --file "$root\frontend\openapi.json"
    if ($LASTEXITCODE -ne 0) { throw 'P07 backend verification failed.' }
} finally { Pop-Location }

Push-Location "$root\backend"
try {
    & $python -m ruff check education_experiment_platform
    if ($LASTEXITCODE -ne 0) { throw 'P07 backend static verification failed.' }
} finally { Pop-Location }

Push-Location "$root\frontend"
try {
    & $npm run generate:api
    & $npm run typecheck
    & $npm run lint
    & $npm run test
    & $npm run build
    if ($LASTEXITCODE -ne 0) { throw 'P07 frontend verification failed.' }
} finally { Pop-Location }

& docker compose -f "$root\docker-compose.dev.yml" config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose validation failed.' }
Write-Output 'P07 static verification passed; isolated Compose and Playwright evidence use verify-p07-integration.ps1.'
