<#
.SYNOPSIS
检查模板表、MinIO 策略、ClamAV 和附件拒绝链，再调用教师与管理端浏览器测试。
.DESCRIPTION
从仓库根目录调用。前置场景缺失：先恢复 scripts/README.md 所列测试文件或命令。
#>
param(
    [string]$ProjectName = 'experimental-platform-templates-verify',
    [switch]$KeepEnvironment
)

$ErrorActionPreference = 'Stop'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') { throw 'ProjectName must be a narrow Docker Compose project identifier.' }
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
# Check browser-test prerequisites before creating or changing containers.
if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend/e2e/templates.spec.ts'))) {
    throw 'Missing browser scenario frontend/e2e/templates.spec.ts; restore that scenario before running this verification. See scripts/README.md.'
}

$compose = @('compose', '-p', $ProjectName, '-f', "$root\docker-compose.dev.yml")
$previous = @{}
foreach ($name in @('ENTRY_PORT', 'OPENAPI_REVISION', 'APP_VERSION', 'APP_NETWORK_SUBNET', 'FLUENTD_HOST_PORT', 'MINIO_API_PORT', 'MINIO_CONSOLE_PORT', 'PROMETHEUS_PORT', 'E2E_SEED_PASSWORD', 'TEACHER_WEB_URL', 'ADMIN_WEB_URL')) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name)
}
$env:ENTRY_PORT = '18085'
$env:OPENAPI_REVISION = 'v2-p05'
$env:APP_VERSION = '0.6.0-p05'
$env:APP_NETWORK_SUBNET = '172.33.205.0/24'
$env:FLUENTD_HOST_PORT = '24227'
$env:MINIO_API_PORT = '19005'
$env:MINIO_CONSOLE_PORT = '19006'
$env:PROMETHEUS_PORT = '19095'

try {
    & docker @compose up --build --detach mysql redis mysql-users migrate mysql-grants minio clamav minio-init
    if ($LASTEXITCODE -ne 0) { throw 'Templates data, object storage, or antivirus services failed to start.' }
    $grantContainer = ''
    for ($attempt = 0; $attempt -lt 60 -and -not $grantContainer; $attempt++) {
        $grantContainer = (& docker @compose ps -aq mysql-grants | Select-Object -Last 1).Trim()
        if (-not $grantContainer) { Start-Sleep -Seconds 2 }
    }
    if (-not $grantContainer) { throw 'Templates MySQL grant hardening container did not start.' }
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $grantState = (& docker inspect --format '{{.State.Status}} {{.State.ExitCode}}' $grantContainer).Trim()
        if ($grantState -match '^exited ' -or $grantState -match '^dead ') {
            if ($grantState -notmatch ' 0$') { throw "Templates MySQL grant hardening failed: $grantState" }
            break
        }
        Start-Sleep -Seconds 2
        if ($attempt -eq 59) { throw 'Templates MySQL grant hardening did not finish.' }
    }

    $tableNames = @(
        'labtemplates_template',
        'labtemplates_template_version',
        'labtemplates_auto_check_rule',
        'labtemplates_template_precheck_run',
        'reviews_rubric',
        'reviews_rubric_version',
        'reviews_rubric_criterion'
    ) -join "','"
    $tableCount = & docker @compose exec -T mysql mysql --host=127.0.0.1 --user=edu_platform_app --password=local-app-password edu_platform --batch --skip-column-names --execute="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('$tableNames')"
    if ($LASTEXITCODE -ne 0 -or ($tableCount | Select-Object -Last 1).Trim() -ne '7') { throw 'Templates schema table verification failed.' }

    $bucket = & docker @compose run --rm --no-deps --entrypoint /bin/sh minio-init -ec 'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"; mc ls "local/edu-platform/template-assets"' 2>&1
    if ($LASTEXITCODE -ne 0 -or ($bucket -match 'AccessDenied')) { throw 'MinIO bucket or app policy verification failed.' }
    & docker @compose exec -T clamav sh -c "printf 'PING\n' | nc 127.0.0.1 3310 | grep PONG"
    if ($LASTEXITCODE -ne 0) { throw 'ClamAV INSTREAM endpoint is not ready.' }

    & docker @compose up --build --detach django celery
    if ($LASTEXITCODE -ne 0) { throw 'Templates application or Celery worker failed to start.' }
    $workerLog = & docker @compose logs --no-color --tail=200 celery
    if ($workerLog -notmatch 'q_provision') { throw 'Celery worker is not configured for q_provision.' }
    & docker @compose exec -T django python manage.py spectacular --format openapi-json --validate --file /tmp/openapi-templates.json
    if ($LASTEXITCODE -ne 0) { throw 'Templates OpenAPI validation failed.' }
    $seedPassword = 'Integration-Disposable-Seed-Only-2026!'
    & docker @compose exec -T -e "PLATFORM_ADMIN_BOOTSTRAP_PASSWORD=$seedPassword" django python manage.py bootstrap_platform_admin --email admin.integration@example.edu --username integration-admin --display-name 'Integration Admin'
    if ($LASTEXITCODE -ne 0) { throw 'Disposable platform admin seed failed.' }
    & docker @compose exec -T -e "E2E_SEED_PASSWORD=$seedPassword" django python manage.py seed_accounts_e2e
    if ($LASTEXITCODE -ne 0) { throw 'Accounts disposable identity seed failed.' }
    & docker @compose exec -T django python manage.py seed_courses_e2e
    if ($LASTEXITCODE -ne 0) { throw 'Courses disposable course seed failed.' }
    & docker @compose exec -T django python manage.py seed_governance_defaults
    & docker @compose exec -T django python manage.py seed_governance_e2e
    if ($LASTEXITCODE -ne 0) { throw 'Governance disposable governance seed failed.' }
    & docker @compose exec -T django python manage.py seed_templates_e2e
    if ($LASTEXITCODE -ne 0) { throw 'Templates disposable seed failed.' }
    & docker @compose run --rm --no-deps django python manage.py verify_template_asset_rejection
    if ($LASTEXITCODE -ne 0) { throw 'Templates asset rejection chain failed.' }
    & docker @compose up --build --detach
    if ($LASTEXITCODE -ne 0) { throw 'Templates full local edge stack failed to start.' }
    $env:E2E_SEED_PASSWORD = $seedPassword
    $env:TEACHER_WEB_URL = 'http://teacher.localhost:18085'
    $env:ADMIN_WEB_URL = 'http://admin.localhost:18085'
    $edgeReady = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $teacherHealth = Invoke-RestMethod -Uri "$($env:TEACHER_WEB_URL)/api/v2/health" -TimeoutSec 5 -NoProxy
            $adminHealth = Invoke-RestMethod -Uri "$($env:ADMIN_WEB_URL)/api/v2/health" -TimeoutSec 5 -NoProxy
            if ($teacherHealth.data.openapi_revision -eq 'v2-p05' -and $adminHealth.data.openapi_revision -eq 'v2-p05') {
                Invoke-RestMethod -Uri "$($env:TEACHER_WEB_URL)/api/v2/auth/csrf" -TimeoutSec 5 -NoProxy | Out-Null
                Invoke-RestMethod -Uri "$($env:ADMIN_WEB_URL)/api/v2/auth/csrf" -TimeoutSec 5 -NoProxy | Out-Null
                $edgeReady = $true
                break
            }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $edgeReady) { throw 'Templates local edge stack did not become ready for browser verification.' }
    Push-Location "$root\frontend"
    try {
        & npx.cmd playwright test e2e/templates.spec.ts --project=teacher-web --project=admin-web
        if ($LASTEXITCODE -ne 0) { throw 'Templates teacher/admin Playwright verification failed.' }
    } finally { Pop-Location }
    Write-Output 'Templates isolated Compose schema, MinIO policy, ClamAV, q_provision, OpenAPI, seed, EICAR rejection, and teacher/admin Playwright checks passed; production evidence remains environment-dependent.'
} finally {
    foreach ($name in $previous.Keys) {
        $value = $previous[$name]
        if ($null -eq $value) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue } else { Set-Item "Env:$name" $value }
    }
    if (-not $KeepEnvironment) { & docker @compose down --volumes --remove-orphans }
}
