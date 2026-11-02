<#
.SYNOPSIS
验证治理表、默认数据、维护任务及 OpenAPI。
.DESCRIPTION
从仓库根目录调用。
#>
param(
    [string]$ProjectName = 'experimental-platform-governance-verify',
    [switch]$KeepEnvironment
)

$ErrorActionPreference = 'Stop'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') { throw 'ProjectName must be a narrow Docker Compose project identifier.' }
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$compose = @('compose', '-p', $ProjectName, '-f', "$root\docker-compose.dev.yml")
$previousEntryPort = $env:ENTRY_PORT
$previousOpenApi = $env:OPENAPI_REVISION
$previousSubnet = $env:APP_NETWORK_SUBNET
$previousFluentdPort = $env:FLUENTD_HOST_PORT
$previousMinioPort = $env:MINIO_CONSOLE_PORT
$previousPrometheusPort = $env:PROMETHEUS_PORT
$env:ENTRY_PORT = '18084'
$env:OPENAPI_REVISION = 'v2-p04'
$env:APP_NETWORK_SUBNET = '172.32.204.0/24'
$env:FLUENTD_HOST_PORT = '24226'
$env:MINIO_CONSOLE_PORT = '19002'
$env:PROMETHEUS_PORT = '19090'

try {
    & docker @compose up --build --detach mysql redis mysql-users migrate mysql-grants
    if ($LASTEXITCODE -ne 0) { throw 'Governance data services failed to start.' }
    & docker @compose run --rm django python manage.py seed_governance_defaults
    $tableNames = @(
        'governance_runtime_adapter',
        'governance_image_asset',
        'governance_resource_profile',
        'governance_quota',
        'governance_quota_reservation',
        'governance_security_policy',
        'governance_network_allowlist'
    ) -join "','"
    $tableCount = & docker @compose exec -T mysql mysql --host=127.0.0.1 --user=edu_platform_app --password=local-app-password edu_platform --batch --skip-column-names --execute="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('$tableNames')"
    if ($LASTEXITCODE -ne 0 -or ($tableCount | Select-Object -Last 1).Trim() -ne '7') { throw 'Governance schema verification failed.' }
    & docker @compose up --build --detach
    if ($LASTEXITCODE -ne 0) { throw 'Governance full local environment failed to start.' }
    & docker @compose exec -T django python manage.py run_governance_maintenance
    & docker @compose exec -T django python manage.py spectacular --format openapi-json --validate --file /tmp/openapi-governance.json
    if ($LASTEXITCODE -ne 0) { throw 'Governance OpenAPI validation failed.' }
    Write-Output 'Governance Compose schema, seed, maintenance, and service startup passed; real-entry Playwright and HA evidence remain environment-dependent.'
} finally {
    if ($null -eq $previousEntryPort) { Remove-Item Env:ENTRY_PORT -ErrorAction SilentlyContinue } else { $env:ENTRY_PORT = $previousEntryPort }
    if ($null -eq $previousOpenApi) { Remove-Item Env:OPENAPI_REVISION -ErrorAction SilentlyContinue } else { $env:OPENAPI_REVISION = $previousOpenApi }
    if ($null -eq $previousSubnet) { Remove-Item Env:APP_NETWORK_SUBNET -ErrorAction SilentlyContinue } else { $env:APP_NETWORK_SUBNET = $previousSubnet }
    if ($null -eq $previousFluentdPort) { Remove-Item Env:FLUENTD_HOST_PORT -ErrorAction SilentlyContinue } else { $env:FLUENTD_HOST_PORT = $previousFluentdPort }
    if ($null -eq $previousMinioPort) { Remove-Item Env:MINIO_CONSOLE_PORT -ErrorAction SilentlyContinue } else { $env:MINIO_CONSOLE_PORT = $previousMinioPort }
    if ($null -eq $previousPrometheusPort) { Remove-Item Env:PROMETHEUS_PORT -ErrorAction SilentlyContinue } else { $env:PROMETHEUS_PORT = $previousPrometheusPort }
    if (-not $KeepEnvironment) { & docker @compose down --volumes --remove-orphans }
}
