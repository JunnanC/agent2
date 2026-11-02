<#
.SYNOPSIS
实验装载与模拟运行时验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。
.DESCRIPTION
从仓库根目录调用。
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = if (Test-Path "$root\backend\.venv\Scripts\python.exe") { "$root\backend\.venv\Scripts\python.exe" } elseif (Test-Path "$root\.venv\Scripts\python.exe") { "$root\.venv\Scripts\python.exe" } else { 'python' }
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source

Push-Location "$root\backend"
try {
    $env:DJANGO_SETTINGS_MODULE = 'education_experiment_platform.settings.test'
    $env:APP_VERSION = '0.8.0-p07'
    $env:OPENAPI_REVISION = 'v2-p07'
    & $python manage.py check
    & $python manage.py makemigrations --check --dry-run
    & $python -m pytest
    & $python manage.py spectacular --format openapi-json --validate --file "$root\frontend\openapi.json"
    if ($LASTEXITCODE -ne 0) { throw 'Provisioning backend verification failed.' }
} finally { Pop-Location }

Push-Location "$root\backend"
try {
    & $python -m ruff check apps education_experiment_platform
    if ($LASTEXITCODE -ne 0) { throw 'Provisioning backend static verification failed.' }
} finally { Pop-Location }

Push-Location "$root\frontend"
try {
    & $npm run generate:api
    & $npm run typecheck
    & $npm run lint
    & $npm run test
    & $npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Provisioning frontend verification failed.' }
} finally { Pop-Location }

& docker compose -f "$root\docker-compose.dev.yml" config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose validation failed.' }
Write-Output 'Provisioning static verification passed; isolated Compose and Playwright evidence use provisioning-integration.ps1.'
