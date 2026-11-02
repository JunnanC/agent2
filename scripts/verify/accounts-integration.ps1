<#
.SYNOPSIS
检查账号表、事件追加权限和门户身份，并调用三个门户的浏览器测试。
.DESCRIPTION
从仓库根目录调用。前置场景缺失：先恢复 scripts/README.md 所列测试文件或命令。
#>
param(
    [string]$ProjectName = 'experimental-platform-accounts-verify',
    [switch]$KeepEnvironment
)

$ErrorActionPreference = 'Stop'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') {
    throw 'ProjectName must be a narrow Docker Compose project identifier.'
}

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
# Check browser-test prerequisites before creating or changing containers.
$frontendScripts = (Get-Content -Raw (Join-Path $root 'frontend/package.json') | ConvertFrom-Json).scripts
if (-not $frontendScripts.PSObject.Properties['test:e2e:student']) {
    throw 'Missing frontend npm command test:e2e:student; this historical browser gate requires restoration. See scripts/README.md.'
}
if (-not $frontendScripts.PSObject.Properties['test:e2e:teacher']) {
    throw 'Missing frontend npm command test:e2e:teacher; this historical browser gate requires restoration. See scripts/README.md.'
}
if (-not $frontendScripts.PSObject.Properties['test:e2e:admin']) {
    throw 'Missing frontend npm command test:e2e:admin; this historical browser gate requires restoration. See scripts/README.md.'
}

$compose = @('compose', '-p', $ProjectName, '-f', "$root\docker-compose.dev.yml")
$bootstrapPassword = 'Accounts-Integration-Admin!234'
$previousAppNetworkSubnet = $env:APP_NETWORK_SUBNET
$previousEntryPort = $env:ENTRY_PORT
$previousFluentdHostPort = $env:FLUENTD_HOST_PORT
$previousMinioConsolePort = $env:MINIO_CONSOLE_PORT
$previousPrometheusPort = $env:PROMETHEUS_PORT
$previousUserWebUrl = $env:STUDENT_WEB_URL
$previousTeacherWebUrl = $env:TEACHER_WEB_URL
$previousAdminWebUrl = $env:ADMIN_WEB_URL
$env:APP_NETWORK_SUBNET = '172.30.202.0/24'
$env:ENTRY_PORT = '18082'
$env:FLUENTD_HOST_PORT = '24225'
$env:MINIO_CONSOLE_PORT = '19001'
$env:PROMETHEUS_PORT = '19090'
$env:STUDENT_WEB_URL = "http://student.localhost:$($env:ENTRY_PORT)"
$env:TEACHER_WEB_URL = "http://teacher.localhost:$($env:ENTRY_PORT)"
$env:ADMIN_WEB_URL = "http://admin.localhost:$($env:ENTRY_PORT)"

try {
    & docker @compose up --build --detach mysql redis mysql-users migrate mysql-grants
    if ($LASTEXITCODE -ne 0) { throw 'Accounts data services failed to start.' }

    & docker @compose --profile tools run --rm --no-deps `
        -e "PLATFORM_ADMIN_BOOTSTRAP_PASSWORD=$bootstrapPassword" `
        core-check python manage.py bootstrap_platform_admin `
        --email admin.integration@example.edu `
        --username integration-admin `
        --display-name 'Integration Admin'
    if ($LASTEXITCODE -ne 0) { throw 'Platform administrator bootstrap failed.' }

    & docker @compose --profile tools run --rm --no-deps `
        -e "E2E_SEED_PASSWORD=$bootstrapPassword" `
        core-check python manage.py seed_accounts_e2e
    if ($LASTEXITCODE -ne 0) { throw 'Accounts disposable E2E seed failed.' }

    & docker @compose exec -T mysql bash -ec @'
export MYSQL_PWD="$MYSQL_APP_PASSWORD"
user_id="$(mysql --host=127.0.0.1 --user="$MYSQL_APP_USER" "$MYSQL_DATABASE" --batch --skip-column-names --execute="SELECT public_id FROM accounts_user LIMIT 1;")"
test "${#user_id}" = "26"
tables="$(mysql --host=127.0.0.1 --user="$MYSQL_APP_USER" "$MYSQL_DATABASE" --batch --skip-column-names --execute="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('accounts_user','accounts_identity_verification','accounts_teacher_qualification','accounts_teacher_qualification_event','accounts_platform_admin_assignment','accounts_platform_admin_assignment_event','django_session');")"
test "$tables" = "7"
'@
    if ($LASTEXITCODE -ne 0) { throw 'Accounts schema or ULID verification failed.' }

    & docker @compose exec -T mysql bash -ec @'
export MYSQL_PWD="$MYSQL_APP_PASSWORD"
mysql --host=127.0.0.1 --user="$MYSQL_APP_USER" "$MYSQL_DATABASE" --execute="UPDATE accounts_platform_admin_assignment_event SET reason='forbidden' LIMIT 1;"
'@
    if ($LASTEXITCODE -eq 0) { throw 'Application DB account unexpectedly updated an account event.' }

    & docker @compose up --build --detach
    if ($LASTEXITCODE -ne 0) { throw 'Accounts full local environment failed to start.' }

    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri "$($env:ADMIN_WEB_URL)/api/v2/health" -TimeoutSec 5 -NoProxy
            if ($health.data.openapi_revision -eq 'v2-p02') { $ready = $true; break }
        } catch { Start-Sleep -Seconds 2 }
    }
    if (-not $ready) { throw 'Accounts real entry did not become ready.' }

    Push-Location "$root\frontend"
    try {
        $env:PLAYWRIGHT_CHANNEL = 'chrome'
        $env:E2E_SEED_PASSWORD = $bootstrapPassword
        $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
        & $npm run test:e2e:student
        if ($LASTEXITCODE -ne 0) { throw 'User portal E2E failed.' }
        & $npm run test:e2e:teacher
        if ($LASTEXITCODE -ne 0) { throw 'Teacher portal E2E failed.' }
        & $npm run test:e2e:admin
        if ($LASTEXITCODE -ne 0) { throw 'Admin portal E2E failed.' }
    } finally { Pop-Location }

    Write-Output 'Accounts empty-MySQL, restricted grants, real entry, and three-portal E2E passed.'
} finally {
    if ($null -eq $previousAppNetworkSubnet) {
        Remove-Item Env:APP_NETWORK_SUBNET -ErrorAction SilentlyContinue
    } else {
        $env:APP_NETWORK_SUBNET = $previousAppNetworkSubnet
    }
    foreach ($item in @(
        @{ Name = 'ENTRY_PORT'; Value = $previousEntryPort },
        @{ Name = 'FLUENTD_HOST_PORT'; Value = $previousFluentdHostPort },
        @{ Name = 'MINIO_CONSOLE_PORT'; Value = $previousMinioConsolePort },
        @{ Name = 'PROMETHEUS_PORT'; Value = $previousPrometheusPort },
        @{ Name = 'STUDENT_WEB_URL'; Value = $previousUserWebUrl },
        @{ Name = 'TEACHER_WEB_URL'; Value = $previousTeacherWebUrl },
        @{ Name = 'ADMIN_WEB_URL'; Value = $previousAdminWebUrl }
    )) {
        if ($null -eq $item.Value) {
            Remove-Item "Env:$($item.Name)" -ErrorAction SilentlyContinue
        } else {
            Set-Item "Env:$($item.Name)" $item.Value
        }
    }
    if (-not $KeepEnvironment) {
        & docker @compose down --volumes --remove-orphans
    }
}
