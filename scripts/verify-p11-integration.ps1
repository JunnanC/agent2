param(
    [string]$ProjectName = 'edu-platform-p11-verify',
    [switch]$KeepEnvironment
)

$ErrorActionPreference = 'Stop'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') { throw 'ProjectName must be a narrow Docker Compose project identifier.' }
$root = Split-Path -Parent $PSScriptRoot
$compose = @('compose', '-p', $ProjectName, '-f', "$root\docker-compose.dev.yml")

function Invoke-P11Compose {
    param([string[]]$StepArguments, [string]$FailureMessage)
    & docker @compose @StepArguments
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
}

$existingContainers = & docker @compose ps --all --quiet
$existingVolumes = & docker volume ls --quiet --filter "label=com.docker.compose.project=$ProjectName"
if ($existingContainers -or $existingVolumes) {
    throw "Compose project '$ProjectName' already owns containers or volumes. Choose a fresh project name."
}

$names = @('APP_VERSION', 'OPENAPI_REVISION', 'ENTRY_PORT', 'APP_NETWORK_SUBNET', 'FLUENTD_HOST_PORT', 'MINIO_API_PORT', 'MINIO_CONSOLE_PORT', 'PROMETHEUS_PORT', 'P02_E2E_PASSWORD', 'STUDENT_WEB_URL', 'TEACHER_WEB_URL', 'ADMIN_WEB_URL')
$previous = @{}
foreach ($name in $names) { $previous[$name] = [Environment]::GetEnvironmentVariable($name) }
$env:APP_VERSION = '0.11.0-p11'
$env:OPENAPI_REVISION = 'v2-p11'
$env:ENTRY_PORT = '18110'
$env:APP_NETWORK_SUBNET = '172.33.211.0/24'
$env:FLUENTD_HOST_PORT = '24233'
$env:MINIO_API_PORT = '19131'
$env:MINIO_CONSOLE_PORT = '19132'
$env:PROMETHEUS_PORT = '19111'

try {
    Invoke-P11Compose -StepArguments @('up', '--build', '--detach', 'mysql', 'redis', 'mysql-users', 'migrate', 'mysql-grants', 'minio', 'clamav', 'minio-init') -FailureMessage 'P11 dependencies failed to start.'
    Invoke-P11Compose -StepArguments @('up', '--build', '--detach', 'django', 'celery', 'celery-beat') -FailureMessage 'P11 Django, Celery, or Beat failed to start.'
    Invoke-P11Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'spectacular', '--format', 'openapi-json', '--validate', '--file', '/tmp/openapi-p11.json') -FailureMessage 'P11 container OpenAPI validation failed.'

    $seedPassword = 'P11-Disposable-Seed-Only-2026!'
    Invoke-P11Compose -StepArguments @('exec', '-T', '-e', "PLATFORM_ADMIN_BOOTSTRAP_PASSWORD=$seedPassword", 'django', 'python', 'manage.py', 'bootstrap_platform_admin', '--email', 'admin.integration@example.edu', '--username', 'integration-admin', '--display-name', 'Integration Admin') -FailureMessage 'P11 platform administrator seed failed.'
    Invoke-P11Compose -StepArguments @('exec', '-T', '-e', "P02_E2E_PASSWORD=$seedPassword", 'django', 'python', 'manage.py', 'seed_p02_e2e') -FailureMessage 'P11 account seed failed.'
    foreach ($seed in @('seed_p03_e2e', 'seed_governance_defaults', 'seed_p04_e2e', 'seed_p05_e2e', 'seed_p06_e2e', 'seed_p07_e2e', 'seed_p08_e2e', 'seed_p10_e2e', 'seed_p11_e2e')) {
        Invoke-P11Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', $seed) -FailureMessage "P11 prerequisite seed failed: $seed"
    }

    Invoke-P11Compose -StepArguments @('up', '--build', '--detach') -FailureMessage 'P11 full local edge stack failed to start.'
    $env:P02_E2E_PASSWORD = $seedPassword
    $env:STUDENT_WEB_URL = 'http://student.localhost:18110'
    $env:TEACHER_WEB_URL = 'http://teacher.localhost:18110'
    $env:ADMIN_WEB_URL = 'http://admin.localhost:18110'
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $health = & curl.exe --noproxy '*' --silent --show-error --max-time 5 "$($env:STUDENT_WEB_URL)/api/v2/health" | Out-String
            if ($LASTEXITCODE -eq 0 -and $health -match '"openapi_revision"\s*:\s*"v2-p11"') { $ready = $true; break }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw 'P11 local edge stack did not become ready.' }

    Push-Location "$root\frontend"
    try {
        & npx.cmd playwright test e2e/p11.spec.ts --project=student-web --project=teacher-web --project=admin-web --workers=1
        if ($LASTEXITCODE -ne 0) { throw 'P11 three-portal Playwright verification failed.' }
    } finally { Pop-Location }
    Write-Output 'P11 isolated Compose, MySQL, MinIO, Celery, FakeRuntime, edge, and three-portal Playwright checks passed.'
} finally {
    foreach ($name in $previous.Keys) {
        $value = $previous[$name]
        if ($null -eq $value) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue } else { Set-Item "Env:$name" $value }
    }
    if (-not $KeepEnvironment) {
        & docker @compose down --volumes --remove-orphans
        if ($LASTEXITCODE -ne 0) { throw 'P11 isolated Compose cleanup failed.' }
    }
}
