param(
    [string]$ProjectName = 'edu-platform-p08-verify',
    [switch]$KeepEnvironment
)

$ErrorActionPreference = 'Stop'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') { throw 'ProjectName must be a narrow Docker Compose project identifier.' }
$root = Split-Path -Parent $PSScriptRoot
$compose = @('compose', '--profile', 'p14', '-p', $ProjectName, '-f', "$root\docker-compose.dev.yml")
$previous = @{}
foreach ($name in @('ENTRY_PORT', 'OPENAPI_REVISION', 'APP_VERSION', 'APP_NETWORK_SUBNET', 'FLUENTD_HOST_PORT', 'MINIO_API_PORT', 'MINIO_CONSOLE_PORT', 'PROMETHEUS_PORT', 'P02_E2E_PASSWORD', 'STUDENT_WEB_URL', 'TEACHER_WEB_URL', 'ADMIN_WEB_URL')) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name)
}
$env:ENTRY_PORT = '18088'
$env:OPENAPI_REVISION = 'v2-p08'
$env:APP_VERSION = '0.8.0-p08'
$env:APP_NETWORK_SUBNET = '172.33.208.0/24'
$env:FLUENTD_HOST_PORT = '24230'
$env:MINIO_API_PORT = '19019'
$env:MINIO_CONSOLE_PORT = '19020'
$env:PROMETHEUS_PORT = '19098'

try {
    & docker @compose up --build --detach mysql redis mysql-users migrate mysql-grants minio clamav minio-init runtime-reference
    if ($LASTEXITCODE -ne 0) { throw 'P08 dependency services failed to start.' }
    & docker @compose up --build --detach django celery runtime-worker workspace-gateway runtime-reference
    if ($LASTEXITCODE -ne 0) { throw 'P08 application or Celery worker failed to start.' }
    & docker @compose exec -T django python manage.py spectacular --format openapi-json --validate --file /tmp/openapi-p08.json
    $seedPassword = 'P08-Disposable-Seed-Only-2026!'
    & docker @compose exec -T -e "PLATFORM_ADMIN_BOOTSTRAP_PASSWORD=$seedPassword" django python manage.py bootstrap_platform_admin --email admin.integration@example.edu --username integration-admin --display-name 'Integration Admin'
    & docker @compose exec -T -e "P02_E2E_PASSWORD=$seedPassword" django python manage.py seed_p02_e2e
    if ($LASTEXITCODE -ne 0) { throw 'P02 disposable seed failed.' }
    & docker @compose exec -T django python manage.py seed_p03_e2e
    & docker @compose exec -T django python manage.py seed_governance_defaults
    & docker @compose exec -T django python manage.py seed_p04_e2e
    & docker @compose exec -T django python manage.py seed_p05_e2e
    & docker @compose exec -T django python manage.py seed_p06_e2e
    & docker @compose exec -T django python manage.py seed_p07_e2e
    & docker @compose exec -T django python manage.py seed_p08_e2e
    if ($LASTEXITCODE -ne 0) { throw 'P02-P08 disposable seed chain failed.' }
    & docker @compose up --build --detach django celery runtime-worker workspace-gateway runtime-reference nginx
    if ($LASTEXITCODE -ne 0) { throw 'P08 full local edge stack failed to start.' }
    $env:P02_E2E_PASSWORD = $seedPassword
    $env:STUDENT_WEB_URL = 'http://student.localhost:18088'
    $env:TEACHER_WEB_URL = 'http://teacher.localhost:18088'
    $env:ADMIN_WEB_URL = 'http://admin.localhost:18088'
    $ready = $false
    $lastProbe = 'no response'
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $healthResponse = Invoke-WebRequest -Uri "http://student.localhost:18088/api/v2/health" -TimeoutSec 5 -NoProxy
            $lastProbe = "status=$($healthResponse.StatusCode) body=$($healthResponse.Content)"
            if ($healthResponse.StatusCode -eq 200 -and $healthResponse.Content -match '"openapi_revision"\s*:\s*"v2-p08"') { $ready = $true; break }
        } catch { $lastProbe = $_.Exception.Message }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw "P08 local edge stack did not become ready. Last probe: $lastProbe" }
    Push-Location "$root\frontend"
    try {
        & npx.cmd playwright test e2e/p08.spec.ts --project=student-web --project=teacher-web --project=admin-web --workers=1
        if ($LASTEXITCODE -ne 0) { throw 'P08 three-portal Playwright verification failed.' }
    } finally { Pop-Location }
    Write-Output 'P08 isolated Compose, schema, FakeRuntime seed, edge, Celery, OpenAPI, and Playwright checks passed; production evidence remains environment-dependent.'
} finally {
    foreach ($name in $previous.Keys) {
        $value = $previous[$name]
        if ($null -eq $value) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue } else { Set-Item "Env:$name" $value }
    }
    if (-not $KeepEnvironment) { & docker @compose down --volumes --remove-orphans }
}
