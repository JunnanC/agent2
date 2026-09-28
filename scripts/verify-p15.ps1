$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = if (Test-Path "$root\.venv\Scripts\python.exe") { "$root\.venv\Scripts\python.exe" } else { 'python' }
$openApiFile = Join-Path ([IO.Path]::GetTempPath()) "edu-platform-openapi-p15-$PID.json"
$generatedTypes = Join-Path ([IO.Path]::GetTempPath()) "edu-platform-schema-p15-$PID.d.ts"
$previousAppVersion = $env:APP_VERSION
$previousOpenApiRevision = $env:OPENAPI_REVISION
$env:APP_VERSION = '0.15.0-p15'
$env:OPENAPI_REVISION = 'v2-p15'

try {
    Push-Location "$root\backend\education_experiment_platform"
    try {
        $env:DJANGO_SETTINGS_MODULE = 'education_experiment_platform.settings.test'
        & $python manage.py check
        if ($LASTEXITCODE -ne 0) { throw 'P15 Django system check failed.' }
        & $python manage.py makemigrations --check --dry-run
        if ($LASTEXITCODE -ne 0) { throw 'P15 migration drift check failed.' }
        & $python -m pytest
        if ($LASTEXITCODE -ne 0) { throw 'P15 backend tests failed.' }
        & $python manage.py spectacular --format openapi-json --validate --file $openApiFile
        if ($LASTEXITCODE -ne 0) { throw 'P15 OpenAPI validation failed.' }
        if ((Get-FileHash $openApiFile -Algorithm SHA256).Hash -ne (Get-FileHash "$root\frontend\openapi.json" -Algorithm SHA256).Hash) {
            throw 'P15 checked-in frontend OpenAPI contract is stale.'
        }
    } finally { Pop-Location }

    Push-Location "$root\backend"
    try {
        & $python -m ruff check education_experiment_platform
        if ($LASTEXITCODE -ne 0) { throw 'P15 backend Ruff failed.' }
        & $python -m mypy education_experiment_platform
        if ($LASTEXITCODE -ne 0) { throw 'P15 backend mypy failed.' }
    } finally { Pop-Location }

    Push-Location "$root\frontend"
    try {
        & npx.cmd openapi-typescript $openApiFile -o $generatedTypes
        if ($LASTEXITCODE -ne 0) { throw 'P15 generated API type verification failed.' }
        if ((Get-FileHash $generatedTypes -Algorithm SHA256).Hash -ne (Get-FileHash 'packages/api-client/src/generated/schema.d.ts' -Algorithm SHA256).Hash) {
            throw 'P15 generated frontend API types are stale.'
        }
        & npm.cmd run typecheck
        if ($LASTEXITCODE -ne 0) { throw 'P15 frontend typecheck failed.' }
        & npm.cmd run lint
        if ($LASTEXITCODE -ne 0) { throw 'P15 frontend lint failed.' }
        & npx.cmd vitest run --pool=threads --maxWorkers=1 --minWorkers=1
        if ($LASTEXITCODE -ne 0) { throw 'P15 frontend tests failed.' }
        & npm.cmd run build:user
        if ($LASTEXITCODE -ne 0) { throw 'P15 user-web build failed.' }
    } finally { Pop-Location }

    & docker compose -f "$root\docker-compose.dev.yml" config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'P15 Compose configuration validation failed.' }
    Write-Output 'P15 local static gates passed. Run verify-p15-integration.ps1 for the container journey.'
} finally {
    Remove-Item -LiteralPath $openApiFile, $generatedTypes -ErrorAction SilentlyContinue
    if ($null -eq $previousAppVersion) { Remove-Item Env:APP_VERSION -ErrorAction SilentlyContinue } else { $env:APP_VERSION = $previousAppVersion }
    if ($null -eq $previousOpenApiRevision) { Remove-Item Env:OPENAPI_REVISION -ErrorAction SilentlyContinue } else { $env:OPENAPI_REVISION = $previousOpenApiRevision }
}
