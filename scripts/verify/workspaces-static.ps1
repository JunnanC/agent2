<#
.SYNOPSIS
工作区与执行生命周期验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。
.DESCRIPTION
从仓库根目录调用。
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = if (Test-Path "$root\backend\.venv\Scripts\python.exe") { "$root\backend\.venv\Scripts\python.exe" } elseif (Test-Path "$root\.venv\Scripts\python.exe") { "$root\.venv\Scripts\python.exe" } else { 'py' }
$pythonArgs = if ($python -eq 'py') { @('-3.14') } else { @() }
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source

Push-Location "$root\backend"
try {
    $env:DJANGO_SETTINGS_MODULE = 'education_experiment_platform.settings.test'
    $env:APP_VERSION = '0.8.0-p08'
    $env:OPENAPI_REVISION = 'v2-p08'
    & $python @pythonArgs manage.py check
    & $python @pythonArgs manage.py makemigrations --check --dry-run
    & $python @pythonArgs -m pytest
    & $python @pythonArgs manage.py spectacular --format openapi-json --validate --file "$root\frontend\openapi.json"
    if ($LASTEXITCODE -ne 0) { throw 'Workspaces backend verification failed.' }
} finally { Pop-Location }

Push-Location "$root\backend"
try {
    & $python @pythonArgs -m ruff check apps education_experiment_platform
    if ($LASTEXITCODE -ne 0) { throw 'Workspaces backend static verification failed.' }
} finally { Pop-Location }

Push-Location "$root\frontend"
try {
    & $npm run generate:api
    & $npm run typecheck
    & $npm run lint
    & $npm run test
    & $npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Workspaces frontend verification failed.' }
} finally { Pop-Location }

& docker compose -f "$root\docker-compose.dev.yml" config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose validation failed.' }
Write-Output 'Workspaces static verification passed; isolated Compose and Playwright evidence use workspaces-integration.ps1.'
