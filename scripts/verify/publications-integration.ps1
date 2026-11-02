<#
.SYNOPSIS
检查发布表、Celery 队列与 OpenAPI，准备发布数据并调用三个门户的浏览器测试。
.DESCRIPTION
从仓库根目录调用。前置场景缺失：先恢复 scripts/README.md 所列测试文件或命令。
#>
param(
    [string]$ProjectName = 'experimental-platform-publications-verify',
    [switch]$KeepEnvironment
)

$ErrorActionPreference = 'Stop'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') { throw 'ProjectName must be a narrow Docker Compose project identifier.' }
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
# Check browser-test prerequisites before creating or changing containers.
if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend/e2e/publications.spec.ts'))) {
    throw 'Missing browser scenario frontend/e2e/publications.spec.ts; restore that scenario before running this verification. See scripts/README.md.'
}

$compose = @('compose', '-p', $ProjectName, '-f', "$root\docker-compose.dev.yml")
$previous = @{}
foreach ($name in @('ENTRY_PORT', 'OPENAPI_REVISION', 'APP_VERSION', 'APP_NETWORK_SUBNET', 'FLUENTD_HOST_PORT', 'MINIO_API_PORT', 'MINIO_CONSOLE_PORT', 'PROMETHEUS_PORT', 'E2E_SEED_PASSWORD', 'STUDENT_WEB_URL', 'TEACHER_WEB_URL', 'ADMIN_WEB_URL')) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name)
}
$env:ENTRY_PORT = '18086'
$env:OPENAPI_REVISION = 'v2-p06'
$env:APP_VERSION = '0.7.0-p06'
$env:APP_NETWORK_SUBNET = '172.33.206.0/24'
$env:FLUENTD_HOST_PORT = '24228'
$env:MINIO_API_PORT = '19007'
$env:MINIO_CONSOLE_PORT = '19008'
$env:PROMETHEUS_PORT = '19096'

try {
    & docker @compose up --build --detach mysql redis mysql-users migrate mysql-grants minio clamav minio-init
    if ($LASTEXITCODE -ne 0) { throw 'Publications dependency services failed to start.' }
    $grantContainer = ''
    for ($attempt = 0; $attempt -lt 60 -and -not $grantContainer; $attempt++) {
        $grantContainer = (& docker @compose ps -aq mysql-grants | Select-Object -Last 1).Trim()
        if (-not $grantContainer) { Start-Sleep -Seconds 2 }
    }
    if (-not $grantContainer) { throw 'Publications MySQL grant hardening container did not start.' }
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $grantState = (& docker inspect --format '{{.State.Status}} {{.State.ExitCode}}' $grantContainer).Trim()
        if ($grantState -match '^exited ' -or $grantState -match '^dead ') {
            if ($grantState -notmatch ' 0$') { throw "Publications MySQL grant hardening failed: $grantState" }
            break
        }
        Start-Sleep -Seconds 2
        if ($attempt -eq 59) { throw 'Publications MySQL grant hardening did not finish.' }
    }
    $tableNames = @(
        'experiments_task_publication',
        'experiments_publication_audience',
        'experiments_publication_prerequisite',
        'experiments_experiment_task',
        'experiments_task_state_transition',
        'experiments_task_extension_request',
        'experiments_task_extension_decision'
    ) -join "','"
    $tableCount = & docker @compose exec -T mysql mysql --host=127.0.0.1 --user=edu_platform_app --password=local-app-password edu_platform --batch --skip-column-names --execute="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('$tableNames')"
    if ($LASTEXITCODE -ne 0 -or ($tableCount | Select-Object -Last 1).Trim() -ne '7') { throw 'Publications schema table verification failed.' }
    & docker @compose up --build --detach django celery
    if ($LASTEXITCODE -ne 0) { throw 'Publications application or Celery worker failed to start.' }
    $workerLog = & docker @compose logs --no-color --tail=200 celery
    if ($workerLog -notmatch 'q_default') { throw 'Celery worker is not configured for q_default.' }
    & docker @compose exec -T django python manage.py spectacular --format openapi-json --validate --file /tmp/openapi-publications.json
    if ($LASTEXITCODE -ne 0) { throw 'Publications OpenAPI validation failed.' }
    $seedPassword = 'Integration-Disposable-Seed-Only-2026!'
    & docker @compose exec -T -e "PLATFORM_ADMIN_BOOTSTRAP_PASSWORD=$seedPassword" django python manage.py bootstrap_platform_admin --email admin.integration@example.edu --username integration-admin --display-name 'Integration Admin'
    & docker @compose exec -T -e "E2E_SEED_PASSWORD=$seedPassword" django python manage.py seed_accounts_e2e
    & docker @compose exec -T django python manage.py seed_courses_e2e
    & docker @compose exec -T django python manage.py seed_governance_defaults
    & docker @compose exec -T django python manage.py seed_governance_e2e
    & docker @compose exec -T django python manage.py seed_templates_e2e
    & docker @compose exec -T django python manage.py seed_publications_e2e
    if ($LASTEXITCODE -ne 0) { throw 'Accounts-Publications disposable seed chain failed.' }
    & docker @compose up --build --detach
    if ($LASTEXITCODE -ne 0) { throw 'Publications full local edge stack failed to start.' }
    $env:E2E_SEED_PASSWORD = $seedPassword
    $env:STUDENT_WEB_URL = 'http://student.localhost:18086'
    $env:TEACHER_WEB_URL = 'http://teacher.localhost:18086'
    $env:ADMIN_WEB_URL = 'http://admin.localhost:18086'
    $edgeReady = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $userHealth = Invoke-RestMethod -Uri "$($env:STUDENT_WEB_URL)/api/v2/health" -TimeoutSec 5 -NoProxy
            $teacherHealth = Invoke-RestMethod -Uri "$($env:TEACHER_WEB_URL)/api/v2/health" -TimeoutSec 5 -NoProxy
            $adminHealth = Invoke-RestMethod -Uri "$($env:ADMIN_WEB_URL)/api/v2/health" -TimeoutSec 5 -NoProxy
            if ($userHealth.data.openapi_revision -eq 'v2-p06' -and $teacherHealth.data.openapi_revision -eq 'v2-p06' -and $adminHealth.data.openapi_revision -eq 'v2-p06') {
                $edgeReady = $true
                break
            }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $edgeReady) { throw 'Publications local edge stack did not become ready.' }
    Push-Location "$root\frontend"
    try {
        & npx.cmd playwright test e2e/publications.spec.ts --project=student-web --project=teacher-web --project=admin-web --workers=1
        if ($LASTEXITCODE -ne 0) { throw 'Publications three-portal Playwright verification failed.' }
    } finally { Pop-Location }
    Write-Output 'Publications isolated Compose schema, seed, edge, Celery, OpenAPI, and three-portal Playwright checks passed; production evidence remains environment-dependent.'
} finally {
    foreach ($name in $previous.Keys) {
        $value = $previous[$name]
        if ($null -eq $value) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue } else { Set-Item "Env:$name" $value }
    }
    if (-not $KeepEnvironment) { & docker @compose down --volumes --remove-orphans }
}
