<#
.SYNOPSIS
第三方集成专项后端测试、OpenAPI、前端类型及 Compose 检查。
.DESCRIPTION
从仓库根目录调用。
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = if (Test-Path "$root\backend\.venv\Scripts\python.exe") { "$root\backend\.venv\Scripts\python.exe" } elseif (Test-Path "$root\.venv\Scripts\python.exe") { "$root\.venv\Scripts\python.exe" } else { 'py' }
$pythonArgs = if ($python -eq 'py') { @('-3.14') } else { @() }
$env:APP_VERSION = '0.13.0-p13'
$env:OPENAPI_REVISION = 'v2-p13'

Push-Location "$root\backend"
try {
    $env:DJANGO_SETTINGS_MODULE = 'education_experiment_platform.settings.test'
    & $python @pythonArgs manage.py check
    & $python @pythonArgs manage.py makemigrations --check --dry-run
    & $python @pythonArgs -m pytest apps/integrations/tests/test_integrations.py
    & $python @pythonArgs manage.py spectacular --format openapi-json --validate --file "$root\backend\openapi-integrations.json"
    if ($LASTEXITCODE -ne 0) { throw 'Integrations backend gates failed.' }
} finally { Pop-Location }

Push-Location "$root\backend"
try { & $python @pythonArgs -m ruff check apps apps/integrations; if ($LASTEXITCODE -ne 0) { throw 'Integrations Ruff failed.' } } finally { Pop-Location }

Push-Location "$root\frontend"
try {
    & npm.cmd run generate:api
    & npx.cmd tsc -p apps/student-web/tsconfig.json --noEmit
    & npx.cmd tsc -p apps/teacher-web/tsconfig.json --noEmit
    & npx.cmd tsc -p apps/admin-web/tsconfig.json --noEmit
    if ($LASTEXITCODE -ne 0) { throw 'Integrations frontend typecheck failed.' }
} finally { Pop-Location }

& docker compose -f "$root\docker-compose.dev.yml" config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Integrations Compose configuration validation failed.' }
Write-Output 'Integrations local gates passed. Real environment remains pending acceptance.'
