param(
    [string]$ProjectName = 'edu-platform-p07-verify',
    [switch]$KeepEnvironment
)

$ErrorActionPreference = 'Stop'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') { throw 'ProjectName must be a narrow Docker Compose project identifier.' }
$root = Split-Path -Parent $PSScriptRoot
$compose = @('compose', '-p', $ProjectName, '-f', "$root\docker-compose.dev.yml")
$previous = @{}
foreach ($name in @('ENTRY_PORT', 'OPENAPI_REVISION', 'APP_VERSION', 'APP_NETWORK_SUBNET', 'FLUENTD_HOST_PORT', 'MINIO_API_PORT', 'MINIO_CONSOLE_PORT', 'PROMETHEUS_PORT', 'P02_E2E_PASSWORD', 'STUDENT_WEB_URL', 'TEACHER_WEB_URL', 'ADMIN_WEB_URL')) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name)
}
$env:ENTRY_PORT = '18087'
$env:OPENAPI_REVISION = 'v2-p07'
$env:APP_VERSION = '0.8.0-p07'
$env:APP_NETWORK_SUBNET = '172.33.207.0/24'
$env:FLUENTD_HOST_PORT = '24229'
$env:MINIO_API_PORT = '19017'
$env:MINIO_CONSOLE_PORT = '19018'
$env:PROMETHEUS_PORT = '19097'

try {
    & docker @compose up --build --detach mysql redis mysql-users migrate mysql-grants minio clamav minio-init
    if ($LASTEXITCODE -ne 0) { throw 'P07 dependency services failed to start.' }
    $grantContainer = ''
    for ($attempt = 0; $attempt -lt 60 -and -not $grantContainer; $attempt++) {
        $grantContainer = (& docker @compose ps -aq mysql-grants | Select-Object -Last 1).Trim()
        if (-not $grantContainer) { Start-Sleep -Seconds 2 }
    }
    if (-not $grantContainer) { throw 'P07 MySQL grant hardening container did not start.' }
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $grantState = (& docker inspect --format '{{.State.Status}} {{.State.ExitCode}}' $grantContainer).Trim()
        if ($grantState -match '^exited ' -or $grantState -match '^dead ') {
            if ($grantState -notmatch ' 0$') { throw "P07 MySQL grant hardening failed: $grantState" }
            break
        }
        Start-Sleep -Seconds 2
        if ($attempt -eq 59) { throw 'P07 MySQL grant hardening did not finish.' }
    }
    $tableNames = @('provisioning_instance', 'provisioning_job', 'provisioning_stage_event') -join "','"
    $tableCount = & docker @compose exec -T mysql mysql --host=127.0.0.1 --user=edu_platform_app --password=local-app-password edu_platform --batch --skip-column-names --execute="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('$tableNames')"
    if ($LASTEXITCODE -ne 0 -or ($tableCount | Select-Object -Last 1).Trim() -ne '3') { throw 'P07 provisioning schema table verification failed.' }
    & docker @compose up --build --detach django celery
    if ($LASTEXITCODE -ne 0) { throw 'P07 application or Celery worker failed to start.' }
    & docker @compose exec -T django python manage.py spectacular --format openapi-json --validate --file /tmp/openapi-p07.json
    $seedPassword = 'P07-Disposable-Seed-Only-2026!'
    & docker @compose exec -T -e "PLATFORM_ADMIN_BOOTSTRAP_PASSWORD=$seedPassword" django python manage.py bootstrap_platform_admin --email admin.integration@example.edu --username integration-admin --display-name 'Integration Admin'
    & docker @compose exec -T -e "P02_E2E_PASSWORD=$seedPassword" django python manage.py seed_p02_e2e
    & docker @compose exec -T django python manage.py seed_p03_e2e
    & docker @compose exec -T django python manage.py seed_governance_defaults
    & docker @compose exec -T django python manage.py seed_p04_e2e
    & docker @compose exec -T django python manage.py seed_p05_e2e
    & docker @compose exec -T django python manage.py seed_p06_e2e
    & docker @compose exec -T django python manage.py seed_p07_e2e
    if ($LASTEXITCODE -ne 0) { throw 'P02-P07 disposable seed chain failed.' }
    & docker @compose up --build --detach
    if ($LASTEXITCODE -ne 0) { throw 'P07 full local edge stack failed to start.' }
    $env:P02_E2E_PASSWORD = $seedPassword
    $env:STUDENT_WEB_URL = 'http://student.localhost:18087'
    $env:TEACHER_WEB_URL = 'http://teacher.localhost:18087'
    $env:ADMIN_WEB_URL = 'http://admin.localhost:18087'
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri "$($env:STUDENT_WEB_URL)/api/v2/health" -TimeoutSec 5 -NoProxy
            if ($health.data.openapi_revision -eq 'v2-p07') { $ready = $true; break }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw 'P07 local edge stack did not become ready.' }
    Push-Location "$root\frontend"
    try {
        & npx.cmd playwright test e2e/p07.spec.ts --project=student-web --project=teacher-web --project=admin-web --workers=1
        if ($LASTEXITCODE -ne 0) { throw 'P07 three-portal Playwright verification failed.' }
    } finally { Pop-Location }
    Write-Output 'P07 isolated Compose schema, FakeRuntime seed, edge, Celery, OpenAPI, and three-portal Playwright checks passed; production evidence remains environment-dependent.'
} finally {
    foreach ($name in $previous.Keys) {
        $value = $previous[$name]
        if ($null -eq $value) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue } else { Set-Item "Env:$name" $value }
    }
    if (-not $KeepEnvironment) { & docker @compose down --volumes --remove-orphans }
}
