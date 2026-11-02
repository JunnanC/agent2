<#
.SYNOPSIS
归档与资源回收验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。
.DESCRIPTION
从仓库根目录调用。
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = if (Test-Path "$root\backend\.venv\Scripts\python.exe") { "$root\backend\.venv\Scripts\python.exe" } elseif (Test-Path "$root\.venv\Scripts\python.exe") { "$root\.venv\Scripts\python.exe" } else { 'py' }
$pythonArgs = if ($python -eq 'py') { @('-3.14') } else { @() }
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
$env:APP_VERSION = '0.11.0-p11'
$env:OPENAPI_REVISION = 'v2-p11'

Push-Location "$root\backend"
try {
    $env:DJANGO_SETTINGS_MODULE = 'education_experiment_platform.settings.test'
    & $python @pythonArgs manage.py check
    if ($LASTEXITCODE -ne 0) { throw 'Archives Django system checks failed.' }
    & $python @pythonArgs manage.py makemigrations --check --dry-run
    if ($LASTEXITCODE -ne 0) { throw 'Archives migration check failed.' }
    & $python @pythonArgs -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Archives backend tests failed.' }
    & $python @pythonArgs manage.py spectacular --format openapi-json --validate --file "$root\frontend\openapi.json"
    if ($LASTEXITCODE -ne 0) { throw 'Archives OpenAPI validation failed.' }
} finally { Pop-Location }

Push-Location "$root\backend"
try {
    & $python @pythonArgs -m ruff check apps education_experiment_platform
    if ($LASTEXITCODE -ne 0) { throw 'Archives backend static verification failed.' }
} finally { Pop-Location }

Push-Location "$root\frontend"
try {
    & $npm run generate:api
    if ($LASTEXITCODE -ne 0) { throw 'Archives API type generation failed.' }
    & $npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'Archives frontend typecheck failed.' }
    & $npm run lint
    if ($LASTEXITCODE -ne 0) { throw 'Archives frontend lint failed.' }
    & $npm run test
    if ($LASTEXITCODE -ne 0) { throw 'Archives frontend tests failed.' }
    & $npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Archives frontend build failed.' }
} finally { Pop-Location }

& docker compose -f "$root\docker-compose.dev.yml" config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Archives Compose configuration validation failed.' }
Write-Output 'Archives local static gates passed. Isolated Compose and Playwright evidence use archives-integration.ps1.'
