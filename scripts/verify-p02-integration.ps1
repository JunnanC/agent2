param(
    [string]$ProjectName = 'edu-platform-p02-verify',
    [switch]$KeepEnvironment
)

$ErrorActionPreference = 'Stop'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') {
    throw 'ProjectName must be a narrow Docker Compose project identifier.'
}

$root = Split-Path -Parent $PSScriptRoot
$compose = @('compose', '-p', $ProjectName, '-f', "$root\docker-compose.dev.yml")
$bootstrapPassword = 'P02-Integration-Admin!234'
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
    if ($LASTEXITCODE -ne 0) { throw 'P02 data services failed to start.' }

    & docker @compose --profile tools run --rm --no-deps `
        -e "PLATFORM_ADMIN_BOOTSTRAP_PASSWORD=$bootstrapPassword" `
        core-check python manage.py bootstrap_platform_admin `
        --email admin.integration@example.edu `
        --username integration-admin `
        --display-name 'Integration Admin'
    if ($LASTEXITCODE -ne 0) { throw 'Platform administrator bootstrap failed.' }

    & docker @compose --profile tools run --rm --no-deps `
        -e "P02_E2E_PASSWORD=$bootstrapPassword" `
        core-check python manage.py seed_p02_e2e
    if ($LASTEXITCODE -ne 0) { throw 'P02 disposable E2E seed failed.' }

    & docker @compose exec -T mysql bash -ec @'
export MYSQL_PWD="$MYSQL_APP_PASSWORD"
user_id="$(mysql --host=127.0.0.1 --user="$MYSQL_APP_USER" "$MYSQL_DATABASE" --batch --skip-column-names --execute="SELECT public_id FROM accounts_user LIMIT 1;")"
test "${#user_id}" = "26"
tables="$(mysql --host=127.0.0.1 --user="$MYSQL_APP_USER" "$MYSQL_DATABASE" --batch --skip-column-names --execute="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('accounts_user','accounts_identity_verification','accounts_teacher_qualification','accounts_teacher_qualification_event','accounts_platform_admin_assignment','accounts_platform_admin_assignment_event','django_session');")"
test "$tables" = "7"
'@
    if ($LASTEXITCODE -ne 0) { throw 'P02 schema or ULID verification failed.' }

    & docker @compose exec -T mysql bash -ec @'
export MYSQL_PWD="$MYSQL_APP_PASSWORD"
mysql --host=127.0.0.1 --user="$MYSQL_APP_USER" "$MYSQL_DATABASE" --execute="UPDATE accounts_platform_admin_assignment_event SET reason='forbidden' LIMIT 1;"
'@
    if ($LASTEXITCODE -eq 0) { throw 'Application DB account unexpectedly updated an account event.' }

    & docker @compose up --build --detach
    if ($LASTEXITCODE -ne 0) { throw 'P02 full local environment failed to start.' }

    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri "$($env:ADMIN_WEB_URL)/api/v2/health" -TimeoutSec 5 -NoProxy
            if ($health.data.openapi_revision -eq 'v2-p02') { $ready = $true; break }
        } catch { Start-Sleep -Seconds 2 }
    }
    if (-not $ready) { throw 'P02 real entry did not become ready.' }

    Push-Location "$root\frontend"
    try {
        $env:PLAYWRIGHT_CHANNEL = 'chrome'
        $env:P02_E2E_PASSWORD = $bootstrapPassword
        $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
        & $npm run test:e2e:student
        if ($LASTEXITCODE -ne 0) { throw 'User portal E2E failed.' }
        & $npm run test:e2e:teacher
        if ($LASTEXITCODE -ne 0) { throw 'Teacher portal E2E failed.' }
        & $npm run test:e2e:admin
        if ($LASTEXITCODE -ne 0) { throw 'Admin portal E2E failed.' }
    } finally { Pop-Location }

    Write-Output 'P02 empty-MySQL, restricted grants, real entry, and three-portal E2E passed.'
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
