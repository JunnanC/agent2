<#
.SYNOPSIS
检查装载表和后台服务，准备模拟运行时数据并调用三个门户的浏览器测试。
.DESCRIPTION
从仓库根目录调用。前置场景缺失：先恢复 scripts/README.md 所列测试文件或命令。
#>
param(
    [string]$ProjectName = 'experimental-platform-provisioning-verify',
    [switch]$KeepEnvironment
)

$ErrorActionPreference = 'Stop'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') { throw 'ProjectName must be a narrow Docker Compose project identifier.' }
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
# Check browser-test prerequisites before creating or changing containers.
if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend/e2e/provisioning.spec.ts'))) {
    throw 'Missing browser scenario frontend/e2e/provisioning.spec.ts; restore that scenario before running this verification. See scripts/README.md.'
}

$compose = @('compose', '-p', $ProjectName, '-f', "$root\docker-compose.dev.yml")
$previous = @{}
foreach ($name in @('ENTRY_PORT', 'OPENAPI_REVISION', 'APP_VERSION', 'APP_NETWORK_SUBNET', 'FLUENTD_HOST_PORT', 'MINIO_API_PORT', 'MINIO_CONSOLE_PORT', 'PROMETHEUS_PORT', 'E2E_SEED_PASSWORD', 'STUDENT_WEB_URL', 'TEACHER_WEB_URL', 'ADMIN_WEB_URL')) {
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
    if ($LASTEXITCODE -ne 0) { throw 'Provisioning dependency services failed to start.' }
    $grantContainer = ''
    for ($attempt = 0; $attempt -lt 60 -and -not $grantContainer; $attempt++) {
        $grantContainer = (& docker @compose ps -aq mysql-grants | Select-Object -Last 1).Trim()
        if (-not $grantContainer) { Start-Sleep -Seconds 2 }
    }
    if (-not $grantContainer) { throw 'Provisioning MySQL grant hardening container did not start.' }
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $grantState = (& docker inspect --format '{{.State.Status}} {{.State.ExitCode}}' $grantContainer).Trim()
        if ($grantState -match '^exited ' -or $grantState -match '^dead ') {
            if ($grantState -notmatch ' 0$') { throw "Provisioning MySQL grant hardening failed: $grantState" }
            break
        }
        Start-Sleep -Seconds 2
        if ($attempt -eq 59) { throw 'Provisioning MySQL grant hardening did not finish.' }
    }
    $tableNames = @('provisioning_instance', 'provisioning_job', 'provisioning_stage_event') -join "','"
    $tableCount = & docker @compose exec -T mysql mysql --host=127.0.0.1 --user=edu_platform_app --password=local-app-password edu_platform --batch --skip-column-names --execute="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('$tableNames')"
    if ($LASTEXITCODE -ne 0 -or ($tableCount | Select-Object -Last 1).Trim() -ne '3') { throw 'Provisioning schema table verification failed.' }
    & docker @compose up --build --detach django celery
    if ($LASTEXITCODE -ne 0) { throw 'Provisioning application or Celery worker failed to start.' }
    & docker @compose exec -T django python manage.py spectacular --format openapi-json --validate --file /tmp/openapi-provisioning.json
    $seedPassword = 'Integration-Disposable-Seed-Only-2026!'
    & docker @compose exec -T -e "PLATFORM_ADMIN_BOOTSTRAP_PASSWORD=$seedPassword" django python manage.py bootstrap_platform_admin --email admin.integration@example.edu --username integration-admin --display-name 'Integration Admin'
    & docker @compose exec -T -e "E2E_SEED_PASSWORD=$seedPassword" django python manage.py seed_accounts_e2e
    & docker @compose exec -T django python manage.py seed_courses_e2e
    & docker @compose exec -T django python manage.py seed_governance_defaults
    & docker @compose exec -T django python manage.py seed_governance_e2e
    & docker @compose exec -T django python manage.py seed_templates_e2e
    & docker @compose exec -T django python manage.py seed_publications_e2e
    & docker @compose exec -T django python manage.py seed_simulated_experiment
    if ($LASTEXITCODE -ne 0) { throw 'Accounts-Provisioning disposable seed chain failed.' }
    & docker @compose up --build --detach
    if ($LASTEXITCODE -ne 0) { throw 'Provisioning full local edge stack failed to start.' }
    $env:E2E_SEED_PASSWORD = $seedPassword
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
    if (-not $ready) { throw 'Provisioning local edge stack did not become ready.' }
    Push-Location "$root\frontend"
    try {
        & npx.cmd playwright test e2e/provisioning.spec.ts --project=student-web --project=teacher-web --project=admin-web --workers=1
        if ($LASTEXITCODE -ne 0) { throw 'Provisioning three-portal Playwright verification failed.' }
    } finally { Pop-Location }
    Write-Output 'Provisioning isolated Compose schema, FakeRuntime seed, edge, Celery, OpenAPI, and three-portal Playwright checks passed; production evidence remains environment-dependent.'
} finally {
    foreach ($name in $previous.Keys) {
        $value = $previous[$name]
        if ($null -eq $value) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue } else { Set-Item "Env:$name" $value }
    }
    if (-not $KeepEnvironment) { & docker @compose down --volumes --remove-orphans }
}
