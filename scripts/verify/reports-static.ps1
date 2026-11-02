<#
.SYNOPSIS
报告与成果验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。
.DESCRIPTION
从仓库根目录调用。
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = if (Test-Path "$root\backend\.venv\Scripts\python.exe") { "$root\backend\.venv\Scripts\python.exe" } elseif (Test-Path "$root\.venv\Scripts\python.exe") { "$root\.venv\Scripts\python.exe" } else { 'py' }
$pythonArgs = if ($python -eq 'py') { @('-3.14') } else { @() }
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
$env:APP_VERSION = '0.9.0-p09'
$env:OPENAPI_REVISION = 'v2-p09'

Push-Location "$root\backend"
try {
    $env:DJANGO_SETTINGS_MODULE = 'education_experiment_platform.settings.test'
    & $python @pythonArgs manage.py check
    if ($LASTEXITCODE -ne 0) { throw 'Reports Django system checks failed.' }
    & $python @pythonArgs manage.py makemigrations --check --dry-run
    if ($LASTEXITCODE -ne 0) { throw 'Reports migration check failed.' }
    & $python @pythonArgs -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Reports backend tests failed.' }
    & $python @pythonArgs manage.py spectacular --format openapi-json --validate --file "$root\frontend\openapi.json"
    if ($LASTEXITCODE -ne 0) { throw 'Reports OpenAPI validation failed.' }
} finally { Pop-Location }

Push-Location "$root\backend"
try {
    & $python @pythonArgs -m ruff check apps education_experiment_platform
    if ($LASTEXITCODE -ne 0) { throw 'Reports backend static verification failed.' }
} finally { Pop-Location }

Push-Location "$root\frontend"
try {
    & $npm run generate:api
    if ($LASTEXITCODE -ne 0) { throw 'Reports API type generation failed.' }
    & $npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'Reports frontend typecheck failed.' }
    & $npm run lint
    if ($LASTEXITCODE -ne 0) { throw 'Reports frontend lint failed.' }
    & $npm run test
    if ($LASTEXITCODE -ne 0) { throw 'Reports frontend tests failed.' }
    & $npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Reports frontend build failed.' }
} finally { Pop-Location }

& docker compose -f "$root\docker-compose.dev.yml" config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Reports Compose configuration validation failed.' }
Write-Output 'Reports local static gates passed. Isolated Compose and Playwright evidence use reports-integration.ps1.'
