$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = 'py'
$pythonArgs = @('-3.14')
foreach ($candidate in @(
    "$root\.venv\Scripts\python.exe",
    "$root\backend\.venv\Scripts\python.exe"
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
    throw 'P13-C requires an available Python 3.14 interpreter.'
}
$env:APP_VERSION = '0.15.0-p15'
$env:OPENAPI_REVISION = 'v2-p15'
$openApiFile = Join-Path ([IO.Path]::GetTempPath()) "edu-platform-openapi-p15-c-$PID.json"

try {
    Push-Location "$root\backend\education_experiment_platform"
    try {
        $env:DJANGO_SETTINGS_MODULE = 'education_experiment_platform.settings.test'
        & $python @pythonArgs manage.py check
        if ($LASTEXITCODE -ne 0) { throw 'P13-C Django system check failed.' }
        & $python @pythonArgs manage.py makemigrations --check --dry-run
        if ($LASTEXITCODE -ne 0) { throw 'P13-C migration drift check failed.' }
        & $python @pythonArgs -m pytest
        if ($LASTEXITCODE -ne 0) { throw 'P13-C backend tests failed.' }
        & $python @pythonArgs manage.py spectacular --format openapi-json --validate --file $openApiFile
        if ($LASTEXITCODE -ne 0) { throw 'P13-C OpenAPI validation failed.' }
        $generatedHash = (Get-FileHash -LiteralPath $openApiFile -Algorithm SHA256).Hash
        $checkedHash = (Get-FileHash -LiteralPath "$root\frontend\openapi.json" -Algorithm SHA256).Hash
        if ($generatedHash -ne $checkedHash) {
            throw 'P13-C checked-in frontend OpenAPI contract is stale.'
        }
    } finally { Pop-Location }

    Push-Location "$root\backend"
    try {
        & $python @pythonArgs -m ruff check education_experiment_platform
        if ($LASTEXITCODE -ne 0) { throw 'P13-C backend Ruff failed.' }
        & $python @pythonArgs -m mypy education_experiment_platform
        if ($LASTEXITCODE -ne 0) { throw 'P13-C backend mypy failed.' }
    } finally { Pop-Location }

    Push-Location "$root\frontend"
    try {
        & npx.cmd eslint apps packages e2e --max-warnings=0
        if ($LASTEXITCODE -ne 0) { throw 'P13-C frontend ESLint failed.' }
        & npx.cmd vitest run
        if ($LASTEXITCODE -ne 0) { throw 'P13-C frontend tests failed.' }
        & npx.cmd tsc -p apps/user-web/tsconfig.json --noEmit
        if ($LASTEXITCODE -ne 0) { throw 'P13-C user-web typecheck failed.' }
        & npx.cmd tsc -p apps/teacher-web/tsconfig.json --noEmit
        if ($LASTEXITCODE -ne 0) { throw 'P13-C teacher-web typecheck failed.' }
        & npx.cmd tsc -p apps/admin-web/tsconfig.json --noEmit
        if ($LASTEXITCODE -ne 0) { throw 'P13-C admin-web typecheck failed.' }
        & npm.cmd run build:user
        if ($LASTEXITCODE -ne 0) { throw 'P13-C user-web build failed.' }
        & npm.cmd run build:teacher
        if ($LASTEXITCODE -ne 0) { throw 'P13-C teacher-web build failed.' }
        & npm.cmd run build:admin
        if ($LASTEXITCODE -ne 0) { throw 'P13-C admin-web build failed.' }
    } finally { Pop-Location }

    & docker compose -f "$root\docker-compose.dev.yml" config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'P13-C Compose configuration validation failed.' }
    Write-Output 'P13-C local gates passed on Python 3.14. Real environment remains pending acceptance.'
} finally {
    Remove-Item -LiteralPath $openApiFile -ErrorAction SilentlyContinue
}
