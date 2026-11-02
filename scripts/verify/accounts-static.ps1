<#
.SYNOPSIS
账号与门户身份验收时使用的累计静态门禁；会检查整个后端和前端，并非只测该模块。
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
    & $python manage.py check
    if ($LASTEXITCODE -ne 0) { throw 'Django check failed.' }
    & $python manage.py makemigrations --check --dry-run
    if ($LASTEXITCODE -ne 0) { throw 'Uncommitted model changes detected.' }
    & $python -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
    & $python manage.py spectacular --format openapi-json --file "$root\frontend\openapi.json"
    if ($LASTEXITCODE -ne 0) { throw 'OpenAPI export failed.' }
} finally { Pop-Location }

Push-Location "$root\backend"
try {
    & $python -m ruff check apps education_experiment_platform
    if ($LASTEXITCODE -ne 0) { throw 'Backend lint failed.' }
    & $python -m mypy apps education_experiment_platform
    if ($LASTEXITCODE -ne 0) { throw 'Backend typecheck failed.' }
} finally { Pop-Location }

Push-Location "$root\frontend"
try {
    & $npm run generate:api
    if ($LASTEXITCODE -ne 0) { throw 'OpenAPI TypeScript generation failed.' }
    & $npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'Frontend typecheck failed.' }
    & $npm run lint
    if ($LASTEXITCODE -ne 0) { throw 'Frontend lint failed.' }
    & $npm run test
    if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed.' }
    & $npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }

& docker compose -f "$root\docker-compose.dev.yml" config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose validation failed.' }
& docker stack config -c "$root\infrastructure\swarm\stack.yml" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Swarm stack validation failed.' }

Push-Location $root
try {
    & git diff --check
    if ($LASTEXITCODE -ne 0) { throw 'Git whitespace validation failed.' }
} finally { Pop-Location }

Write-Output 'Accounts static verification passed.'
