<#
.SYNOPSIS
准备归档测试数据并调用归档浏览器测试。
.DESCRIPTION
从仓库根目录调用。前置场景缺失：先恢复 scripts/README.md 所列测试文件或命令。
#>
param(
    [string]$ProjectName = 'experimental-platform-archives-verify',
    [switch]$KeepEnvironment
)

$ErrorActionPreference = 'Stop'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') { throw 'ProjectName must be a narrow Docker Compose project identifier.' }
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
# Check browser-test prerequisites before creating or changing containers.
if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend/e2e/archives.spec.ts'))) {
    throw 'Missing browser scenario frontend/e2e/archives.spec.ts; restore that scenario before running this verification. See scripts/README.md.'
}

$compose = @('compose', '-p', $ProjectName, '-f', "$root\docker-compose.dev.yml")

function Invoke-Compose {
    param([string[]]$StepArguments, [string]$FailureMessage)
    & docker @compose @StepArguments
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
}

$existingContainers = & docker @compose ps --all --quiet
$existingVolumes = & docker volume ls --quiet --filter "label=com.docker.compose.project=$ProjectName"
if ($existingContainers -or $existingVolumes) {
    throw "Compose project '$ProjectName' already owns containers or volumes. Choose a fresh project name."
}

$names = @('APP_VERSION', 'OPENAPI_REVISION', 'ENTRY_PORT', 'APP_NETWORK_SUBNET', 'FLUENTD_HOST_PORT', 'MINIO_API_PORT', 'MINIO_CONSOLE_PORT', 'PROMETHEUS_PORT', 'E2E_SEED_PASSWORD', 'STUDENT_WEB_URL', 'TEACHER_WEB_URL', 'ADMIN_WEB_URL')
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
    Invoke-Compose -StepArguments @('up', '--build', '--detach', 'mysql', 'redis', 'mysql-users', 'migrate', 'mysql-grants', 'minio', 'clamav', 'minio-init') -FailureMessage 'Archives dependencies failed to start.'
    Invoke-Compose -StepArguments @('up', '--build', '--detach', 'django', 'celery', 'celery-beat') -FailureMessage 'Archives Django, Celery, or Beat failed to start.'
    Invoke-Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'spectacular', '--format', 'openapi-json', '--validate', '--file', '/tmp/openapi-archives.json') -FailureMessage 'Archives container OpenAPI validation failed.'

    $seedPassword = 'Integration-Disposable-Seed-Only-2026!'
    Invoke-Compose -StepArguments @('exec', '-T', '-e', "PLATFORM_ADMIN_BOOTSTRAP_PASSWORD=$seedPassword", 'django', 'python', 'manage.py', 'bootstrap_platform_admin', '--email', 'admin.integration@example.edu', '--username', 'integration-admin', '--display-name', 'Integration Admin') -FailureMessage 'Archives platform administrator seed failed.'
    Invoke-Compose -StepArguments @('exec', '-T', '-e', "E2E_SEED_PASSWORD=$seedPassword", 'django', 'python', 'manage.py', 'seed_accounts_e2e') -FailureMessage 'Archives account seed failed.'
    foreach ($seed in @('seed_courses_e2e', 'seed_governance_defaults', 'seed_governance_e2e', 'seed_templates_e2e', 'seed_publications_e2e', 'seed_simulated_experiment', 'seed_workspaces_e2e', 'seed_reviews_e2e', 'seed_archives_e2e')) {
        Invoke-Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', $seed) -FailureMessage "Archives prerequisite seed failed: $seed"
    }

    Invoke-Compose -StepArguments @('up', '--build', '--detach') -FailureMessage 'Archives full local edge stack failed to start.'
    $env:E2E_SEED_PASSWORD = $seedPassword
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
    if (-not $ready) { throw 'Archives local edge stack did not become ready.' }

    Push-Location "$root\frontend"
    try {
        & npx.cmd playwright test e2e/archives.spec.ts --project=student-web --project=teacher-web --project=admin-web --workers=1
        if ($LASTEXITCODE -ne 0) { throw 'Archives three-portal Playwright verification failed.' }
    } finally { Pop-Location }
    Write-Output 'Archives isolated Compose, MySQL, MinIO, Celery, FakeRuntime, edge, and three-portal Playwright checks passed.'
} finally {
    foreach ($name in $previous.Keys) {
        $value = $previous[$name]
        if ($null -eq $value) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue } else { Set-Item "Env:$name" $value }
    }
    if (-not $KeepEnvironment) {
        & docker @compose down --volumes --remove-orphans
        if ($LASTEXITCODE -ne 0) { throw 'Archives isolated Compose cleanup failed.' }
    }
}
