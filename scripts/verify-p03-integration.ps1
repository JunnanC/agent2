param(
    [string]$ProjectName = 'edu-platform-p03-verify',
    [switch]$KeepEnvironment
)

$ErrorActionPreference = 'Stop'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') { throw 'ProjectName must be a narrow Docker Compose project identifier.' }
$root = Split-Path -Parent $PSScriptRoot
$compose = @('compose', '-p', $ProjectName, '-f', "$root\docker-compose.dev.yml")
$previousEntryPort = $env:ENTRY_PORT
$previousOpenApi = $env:OPENAPI_REVISION
$previousSubnet = $env:APP_NETWORK_SUBNET
$env:ENTRY_PORT = '18083'
$env:OPENAPI_REVISION = 'v2-p04'
$env:APP_NETWORK_SUBNET = '172.31.203.0/24'

try {
    & docker @compose up --build --detach mysql redis mysql-users migrate mysql-grants
    if ($LASTEXITCODE -ne 0) { throw 'P03 data services failed to start.' }
    $tableCount = & docker @compose exec -T mysql mysql --host=127.0.0.1 --user=edu_platform_app --password=local-app-password edu_platform --batch --skip-column-names --execute="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name LIKE 0x636f75727365735f25"
    if ($LASTEXITCODE -ne 0 -or ($tableCount | Select-Object -Last 1).Trim() -ne '22') { throw 'P03 MySQL schema verification failed.' }
    & docker @compose up --build --detach
    if ($LASTEXITCODE -ne 0) { throw 'P03 full local environment failed to start.' }
    Write-Output 'P03 Compose schema and service startup passed; portal Playwright flows require disposable seed credentials.'
} finally {
    if ($null -eq $previousEntryPort) { Remove-Item Env:ENTRY_PORT -ErrorAction SilentlyContinue } else { $env:ENTRY_PORT = $previousEntryPort }
    if ($null -eq $previousOpenApi) { Remove-Item Env:OPENAPI_REVISION -ErrorAction SilentlyContinue } else { $env:OPENAPI_REVISION = $previousOpenApi }
    if ($null -eq $previousSubnet) { Remove-Item Env:APP_NETWORK_SUBNET -ErrorAction SilentlyContinue } else { $env:APP_NETWORK_SUBNET = $previousSubnet }
    if (-not $KeepEnvironment) { & docker @compose down --volumes --remove-orphans }
}
