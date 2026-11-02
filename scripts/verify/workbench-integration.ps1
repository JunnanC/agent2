<#
.SYNOPSIS
现有测试环境中的工作台装载、保存、助手与提交浏览器回归。
.DESCRIPTION
从仓库根目录调用。前置场景缺失：先恢复 scripts/README.md 所列测试文件或命令。
#>
param(
    [string]$ProjectName = 'experimental-platform',
    [int]$EntryPort = 8080,
    [string]$SeedPassword = 'Integration-Disposable-Seed-Only-2026!'
)

$ErrorActionPreference = 'Stop'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') { throw 'ProjectName must be a narrow Docker Compose project identifier.' }
if ($EntryPort -lt 1 -or $EntryPort -gt 65535) { throw 'EntryPort must be a valid TCP port.' }
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
# Check browser-test prerequisites before creating or changing containers.
if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend/e2e/workbench-assistant.spec.ts'))) {
    throw 'Missing browser scenario frontend/e2e/workbench-assistant.spec.ts; restore that scenario before running this verification. See scripts/README.md.'
}
if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend/e2e/workbench-journey.spec.ts'))) {
    throw 'Missing browser scenario frontend/e2e/workbench-journey.spec.ts; restore that scenario before running this verification. See scripts/README.md.'
}
if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend/e2e/workspaces.spec.ts'))) {
    throw 'Missing browser scenario frontend/e2e/workspaces.spec.ts; restore that scenario before running this verification. See scripts/README.md.'
}

$composeFile = "$root\docker-compose.dev.yml"
$compose = @('compose', '--profile', 'runtime', '-p', $ProjectName, '-f', $composeFile)
$runtimeWorkerStopped = $false
$runId = [DateTimeOffset]::UtcNow.ToString('yyyyMMddHHmmss')
$taskTitle = "工作台集成验收实验 $runId"
$names = @('APP_VERSION', 'OPENAPI_REVISION', 'ENTRY_PORT', 'E2E_SEED_PASSWORD', 'WORKBENCH_E2E_TASK_TITLE', 'WORKBENCH_COMPOSE_PROJECT', 'WORKBENCH_COMPOSE_FILE', 'STUDENT_WEB_URL', 'TEACHER_WEB_URL', 'ADMIN_WEB_URL')
$previous = @{}
foreach ($name in $names) { $previous[$name] = [Environment]::GetEnvironmentVariable($name) }

function Invoke-Compose {
    param([string[]]$StepArguments, [string]$FailureMessage)
    & docker @compose @StepArguments
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
}

try {
    $existing = & docker @compose ps --all --quiet
    if (-not $existing) { throw "Compose project '$ProjectName' is not running. Start the requested Swarm runtime container baseline first." }

    $env:APP_VERSION = '0.15.0-p15'
    $env:OPENAPI_REVISION = 'v2-p15'
    $env:ENTRY_PORT = [string]$EntryPort
    $env:E2E_SEED_PASSWORD = $SeedPassword
    $env:WORKBENCH_E2E_TASK_TITLE = $taskTitle
    $env:WORKBENCH_COMPOSE_PROJECT = $ProjectName
    $env:WORKBENCH_COMPOSE_FILE = $composeFile
    $env:STUDENT_WEB_URL = "http://student.localhost:$EntryPort"
    $env:TEACHER_WEB_URL = "http://teacher.localhost:$EntryPort"
    $env:ADMIN_WEB_URL = "http://admin.localhost:$EntryPort"

    # Re-apply the restricted runtime grants after the baseline migrations. The
    # one-shot grants container may predate newly added tables in a reused Swarm runtime
    # project, so `up` alone would incorrectly keep stale privileges.
    Invoke-Compose -StepArguments @('run', '--rm', 'mysql-grants') -FailureMessage 'Workbench database grants could not be refreshed.'
    Invoke-Compose -StepArguments @('up', '--build', '--detach', 'django', 'celery', 'runtime-worker', 'workspace-gateway', 'nginx') -FailureMessage 'Workbench application image refresh failed.'
    # Compose does not recreate long-running Kong/nginx services when their
    # Django upstream is replaced, leaving stale container IPs in proxy DNS.
    Invoke-Compose -StepArguments @('up', '--detach', '--force-recreate', '--no-deps', 'kong') -FailureMessage 'Workbench Kong proxy could not refresh its upstreams.'
    Invoke-Compose -StepArguments @('up', '--detach', '--force-recreate', '--no-deps', 'nginx') -FailureMessage 'Workbench nginx edge proxy could not refresh its upstreams.'
    Invoke-Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'spectacular', '--format', 'openapi-json', '--validate', '--file', '/tmp/openapi-workbench.json') -FailureMessage 'Workbench container OpenAPI validation failed.'
    Invoke-Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'seed_simulated_experiment') -FailureMessage 'Provisioning disposable journey seed failed.'
    Invoke-Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'seed_workspaces_e2e') -FailureMessage 'Workspaces disposable workspace seed failed.'
    Invoke-Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'seed_workbench_e2e', '--run-id', $runId) -FailureMessage 'Workbench disposable journey seed failed. Ensure the Accounts-Publications integration facts already exist.'

    $ready = $false
    $lastProbe = 'no response'
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $health = Invoke-WebRequest -Uri "$($env:STUDENT_WEB_URL)/api/v2/health" -TimeoutSec 5 -NoProxy
            $lastProbe = "status=$($health.StatusCode) body=$($health.Content)"
            if ($health.StatusCode -eq 200 -and $health.Content -match '"openapi_revision"\s*:\s*"v2-p15"') { $ready = $true; break }
        } catch { $lastProbe = $_.Exception.Message }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw "Workbench edge did not become ready. Last probe: $lastProbe" }

    Invoke-Compose -StepArguments @('stop', 'runtime-worker') -FailureMessage 'Workbench could not pause the runtime worker for deterministic loading-page verification.'
    $runtimeWorkerStopped = $true
    Push-Location "$root\frontend"
    try {
        & npx.cmd playwright test e2e/workbench-journey.spec.ts --project=student-web --workers=1
        $journeyExit = $LASTEXITCODE
    } finally { Pop-Location }
    Invoke-Compose -StepArguments @('up', '--detach', '--no-deps', 'runtime-worker') -FailureMessage 'Workbench runtime worker could not be restored after the loading-page check.'
    $runtimeWorkerStopped = $false
    if ($journeyExit -ne 0) {
        & "$root\.venv\Scripts\python.exe" "$root\scripts\verify\redact-browser-artifacts.py" "$root\frontend\test-results"
        throw 'Workbench complete Playwright journey failed; retained artifacts were scrubbed.'
    }

    Push-Location "$root\frontend"
    try {
        & npx.cmd playwright test e2e/workspaces.spec.ts e2e/workbench-assistant.spec.ts --project=student-web --project=teacher-web --project=admin-web --workers=1
        $regressionExit = $LASTEXITCODE
    } finally { Pop-Location }
    if ($regressionExit -ne 0) {
        & "$root\.venv\Scripts\python.exe" "$root\scripts\verify\redact-browser-artifacts.py" "$root\frontend\test-results"
        throw 'Workbench workspace, Agent, or portal-boundary Playwright regression failed; retained artifacts were scrubbed.'
    }
    Write-Output "Workbench container journey passed for project '$ProjectName'; production HA, capacity, recovery, and DNS/TLS remain pending."
} finally {
    if ($runtimeWorkerStopped) { & docker @compose up --detach --no-deps runtime-worker | Out-Null }
    foreach ($name in $previous.Keys) {
        $value = $previous[$name]
        if ($null -eq $value) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue } else { Set-Item "Env:$name" $value }
    }
}
