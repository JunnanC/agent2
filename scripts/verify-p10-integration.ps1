param(
    [string]$ProjectName = 'edu-platform-p10-verify',
    [switch]$KeepEnvironment
)

$ErrorActionPreference = 'Stop'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') { throw 'ProjectName must be a narrow Docker Compose project identifier.' }
$root = Split-Path -Parent $PSScriptRoot
$compose = @('compose', '-p', $ProjectName, '-f', "$root\docker-compose.dev.yml")

function Invoke-P10Compose {
    param([string[]]$StepArguments, [string]$FailureMessage)
    & docker @compose @StepArguments
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
}

$existingContainers = & docker @compose ps --all --quiet
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the isolated P10 Compose project.' }
$existingVolumes = & docker volume ls --quiet --filter "label=com.docker.compose.project=$ProjectName"
if ($existingContainers -or $existingVolumes) {
    throw "Compose project '$ProjectName' already owns containers or volumes. Choose a fresh project name to protect existing data."
}

$previous = @{}
foreach ($name in @('APP_VERSION', 'OPENAPI_REVISION', 'ENTRY_PORT', 'APP_NETWORK_SUBNET', 'FLUENTD_HOST_PORT', 'MINIO_API_PORT', 'MINIO_CONSOLE_PORT', 'PROMETHEUS_PORT', 'P02_E2E_PASSWORD', 'USER_WEB_URL', 'TEACHER_WEB_URL', 'ADMIN_WEB_URL')) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name)
}
$env:APP_VERSION = '0.10.0-p10'
$env:OPENAPI_REVISION = 'v2-p10'
$env:ENTRY_PORT = '18090'
$env:APP_NETWORK_SUBNET = '172.33.210.0/24'
$env:FLUENTD_HOST_PORT = '24232'
$env:MINIO_API_PORT = '19031'
$env:MINIO_CONSOLE_PORT = '19032'
$env:PROMETHEUS_PORT = '19110'

try {
    Invoke-P10Compose -StepArguments @('up', '--build', '--detach', 'mysql', 'redis', 'mysql-users', 'migrate', 'mysql-grants', 'minio', 'clamav', 'minio-init') -FailureMessage 'P10 database, object storage, or scanner dependencies failed to start.'
    Invoke-P10Compose -StepArguments @('up', '--build', '--detach', 'django', 'celery') -FailureMessage 'P10 Django or Celery failed to start.'
    Invoke-P10Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'spectacular', '--format', 'openapi-json', '--validate', '--file', '/tmp/openapi-p10.json') -FailureMessage 'P10 container OpenAPI validation failed.'

    $seedPassword = 'P10-Disposable-Seed-Only-2026!'
    Invoke-P10Compose -StepArguments @('exec', '-T', '-e', "PLATFORM_ADMIN_BOOTSTRAP_PASSWORD=$seedPassword", 'django', 'python', 'manage.py', 'bootstrap_platform_admin', '--email', 'admin.integration@example.edu', '--username', 'integration-admin', '--display-name', 'Integration Admin') -FailureMessage 'P10 platform administrator seed failed.'
    Invoke-P10Compose -StepArguments @('exec', '-T', '-e', "P02_E2E_PASSWORD=$seedPassword", 'django', 'python', 'manage.py', 'seed_p02_e2e') -FailureMessage 'P10 P02 disposable seed failed.'
    foreach ($seed in @('seed_p03_e2e', 'seed_governance_defaults', 'seed_p04_e2e', 'seed_p05_e2e', 'seed_p06_e2e', 'seed_p07_e2e', 'seed_p08_e2e', 'seed_p10_e2e')) {
        Invoke-P10Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', $seed) -FailureMessage "P10 prerequisite seed failed: $seed"
    }

    Invoke-P10Compose -StepArguments @('up', '--build', '--detach') -FailureMessage 'P10 full local edge stack failed to start.'
    $env:P02_E2E_PASSWORD = $seedPassword
    $env:USER_WEB_URL = 'http://user.localhost:18090'
    $env:TEACHER_WEB_URL = 'http://teacher.localhost:18090'
    $env:ADMIN_WEB_URL = 'http://admin.localhost:18090'
    $ready = $false
    $lastProbe = 'no response'
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $healthText = & curl.exe --noproxy '*' --silent --show-error --max-time 5 --write-out "`nHTTP_STATUS:%{http_code}" "$($env:USER_WEB_URL)/api/v2/health" | Out-String
            if ($LASTEXITCODE -ne 0) { throw $healthText.Trim() }
            if ($healthText -match '(?s)^(?<body>.*)\r?\nHTTP_STATUS:(?<status>\d{3})\s*$') {
                $healthBody = $Matches.body.Trim()
                $healthStatus = [int]$Matches.status
                $lastProbe = "status=$healthStatus body=$healthBody"
                if ($healthStatus -eq 200 -and $healthBody -match '"openapi_revision"\s*:\s*"v2-p10"') { $ready = $true; break }
            } else { $lastProbe = $healthText.Trim() }
        } catch { $lastProbe = $_.Exception.Message }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw "P10 local edge stack did not become ready. Last probe: $lastProbe" }

    Push-Location "$root\frontend"
    try {
        & npx.cmd playwright test e2e/p10.spec.ts --project=user-web --project=teacher-web --project=admin-web --workers=1
        if ($LASTEXITCODE -ne 0) { throw 'P10 three-portal Playwright verification failed.' }
    } finally { Pop-Location }
    Write-Output 'P10 isolated Compose, MySQL, Celery, FakeRuntime checks, Nginx-to-Kong edge, OpenAPI, and three-portal Playwright checks passed. Production environment evidence remains outstanding.'
} finally {
    foreach ($name in $previous.Keys) {
        $value = $previous[$name]
        if ($null -eq $value) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue } else { Set-Item "Env:$name" $value }
    }
    if (-not $KeepEnvironment) {
        & docker @compose down --volumes --remove-orphans
        if ($LASTEXITCODE -ne 0) { throw 'P10 isolated Compose cleanup failed.' }
    }
}
