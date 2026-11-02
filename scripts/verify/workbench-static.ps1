<#
.SYNOPSIS
工作台验收用全后端门禁、前端契约/单测及学生端构建。
.DESCRIPTION
从仓库根目录调用。
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = 'py'
$pythonArgs = @('-3.14')
foreach ($candidate in @(
    "$root\backend\.venv\Scripts\python.exe",
    "$root\.venv\Scripts\python.exe"
)) {
    if (-not (Test-Path -LiteralPath $candidate)) { continue }
    $candidateVersion = & $candidate -c 'import sys; import django, mypy, pytest, ruff; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>$null
    if ($LASTEXITCODE -eq 0 -and $candidateVersion -eq '3.14') {
        $python = $candidate
        $pythonArgs = @()
        break
    }
}
$pythonVersion = & $python @pythonArgs -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne '3.14') {
    throw 'Workbench requires an available Python 3.14 interpreter.'
}
$openApiFile = Join-Path ([IO.Path]::GetTempPath()) "experimental-platform-openapi-workbench-$PID.json"
$generatedTypes = Join-Path ([IO.Path]::GetTempPath()) "experimental-platform-schema-workbench-$PID.d.ts"
$previousAppVersion = $env:APP_VERSION
$previousOpenApiRevision = $env:OPENAPI_REVISION
$env:APP_VERSION = '0.15.0-p15'
$env:OPENAPI_REVISION = 'v2-p15'

try {
    Push-Location "$root\backend"
    try {
        $env:DJANGO_SETTINGS_MODULE = 'education_experiment_platform.settings.test'
        & $python @pythonArgs manage.py check
        if ($LASTEXITCODE -ne 0) { throw 'Workbench Django system check failed.' }
        & $python @pythonArgs manage.py makemigrations --check --dry-run
        if ($LASTEXITCODE -ne 0) { throw 'Workbench migration drift check failed.' }
        & $python @pythonArgs -m pytest
        if ($LASTEXITCODE -ne 0) { throw 'Workbench backend tests failed.' }
        & $python @pythonArgs manage.py spectacular --format openapi-json --validate --file $openApiFile
        if ($LASTEXITCODE -ne 0) { throw 'Workbench OpenAPI validation failed.' }
        if ((Get-FileHash $openApiFile -Algorithm SHA256).Hash -ne (Get-FileHash "$root\frontend\openapi.json" -Algorithm SHA256).Hash) {
            throw 'Workbench checked-in frontend OpenAPI contract is stale.'
        }
    } finally { Pop-Location }

    Push-Location "$root\backend"
    try {
        & $python @pythonArgs -m ruff check apps education_experiment_platform
        if ($LASTEXITCODE -ne 0) { throw 'Workbench backend Ruff failed.' }
        & $python @pythonArgs -m mypy apps education_experiment_platform
        if ($LASTEXITCODE -ne 0) { throw 'Workbench backend mypy failed.' }
    } finally { Pop-Location }

    Push-Location "$root\frontend"
    try {
        & npx.cmd openapi-typescript $openApiFile -o $generatedTypes
        if ($LASTEXITCODE -ne 0) { throw 'Workbench generated API type verification failed.' }
        if ((Get-FileHash $generatedTypes -Algorithm SHA256).Hash -ne (Get-FileHash 'packages/api-client/src/generated/schema.d.ts' -Algorithm SHA256).Hash) {
            throw 'Workbench generated frontend API types are stale.'
        }
        & npm.cmd run typecheck
        if ($LASTEXITCODE -ne 0) { throw 'Workbench frontend typecheck failed.' }
        & npm.cmd run lint
        if ($LASTEXITCODE -ne 0) { throw 'Workbench frontend lint failed.' }
        & npx.cmd vitest run --pool=threads --maxWorkers=1
        if ($LASTEXITCODE -ne 0) { throw 'Workbench frontend tests failed.' }
        & npm.cmd run build:student
        if ($LASTEXITCODE -ne 0) { throw 'Workbench student-web build failed.' }
    } finally { Pop-Location }

    & docker compose -f "$root\docker-compose.dev.yml" config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Workbench Compose configuration validation failed.' }
    Write-Output 'Workbench local static gates passed. Run workbench-integration.ps1 for the container journey.'
} finally {
    Remove-Item -LiteralPath $openApiFile, $generatedTypes -ErrorAction SilentlyContinue
    if ($null -eq $previousAppVersion) { Remove-Item Env:APP_VERSION -ErrorAction SilentlyContinue } else { $env:APP_VERSION = $previousAppVersion }
    if ($null -eq $previousOpenApiRevision) { Remove-Item Env:OPENAPI_REVISION -ErrorAction SilentlyContinue } else { $env:OPENAPI_REVISION = $previousOpenApiRevision }
}
