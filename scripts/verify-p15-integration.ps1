param(
    [string]$ProjectName = 'edu-platform-p14',
    [int]$EntryPort = 8080,
    [string]$SeedPassword = 'P08-Disposable-Seed-Only-2026!'
)

$ErrorActionPreference = 'Stop'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') { throw 'ProjectName must be a narrow Docker Compose project identifier.' }
if ($EntryPort -lt 1 -or $EntryPort -gt 65535) { throw 'EntryPort must be a valid TCP port.' }
$root = Split-Path -Parent $PSScriptRoot
$composeFile = "$root\docker-compose.dev.yml"
$compose = @('compose', '--profile', 'p14', '-p', $ProjectName, '-f', $composeFile)
$runtimeWorkerStopped = $false
$runId = [DateTimeOffset]::UtcNow.ToString('yyyyMMddHHmmss')
$taskTitle = "P15 集成验收实验 $runId"
$names = @('APP_VERSION', 'OPENAPI_REVISION', 'ENTRY_PORT', 'P02_E2E_PASSWORD', 'P15_E2E_TASK_TITLE', 'P15_COMPOSE_PROJECT', 'P15_COMPOSE_FILE', 'STUDENT_WEB_URL', 'TEACHER_WEB_URL', 'ADMIN_WEB_URL')
$previous = @{}
foreach ($name in $names) { $previous[$name] = [Environment]::GetEnvironmentVariable($name) }

function Invoke-P15Compose {
    param([string[]]$StepArguments, [string]$FailureMessage)
    & docker @compose @StepArguments
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
}

try {
    $existing = & docker @compose ps --all --quiet
    if (-not $existing) { throw "Compose project '$ProjectName' is not running. Start the requested P14 container baseline first." }

    $env:APP_VERSION = '0.15.0-p15'
    $env:OPENAPI_REVISION = 'v2-p15'
    $env:ENTRY_PORT = [string]$EntryPort
    $env:P02_E2E_PASSWORD = $SeedPassword
    $env:P15_E2E_TASK_TITLE = $taskTitle
    $env:P15_COMPOSE_PROJECT = $ProjectName
    $env:P15_COMPOSE_FILE = $composeFile
    $env:STUDENT_WEB_URL = "http://student.localhost:$EntryPort"
    $env:TEACHER_WEB_URL = "http://teacher.localhost:$EntryPort"
    $env:ADMIN_WEB_URL = "http://admin.localhost:$EntryPort"

    # Re-apply the restricted runtime grants after the baseline migrations. The
    # one-shot grants container may predate newly added tables in a reused P14
    # project, so `up` alone would incorrectly keep stale privileges.
    Invoke-P15Compose -StepArguments @('run', '--rm', 'mysql-grants') -FailureMessage 'P15 database grants could not be refreshed.'
    Invoke-P15Compose -StepArguments @('up', '--build', '--detach', 'django', 'celery', 'runtime-worker', 'workspace-gateway', 'nginx') -FailureMessage 'P15 application image refresh failed.'
    # Compose does not recreate long-running Kong/nginx services when their
    # Django upstream is replaced, leaving stale container IPs in proxy DNS.
    Invoke-P15Compose -StepArguments @('up', '--detach', '--force-recreate', '--no-deps', 'kong') -FailureMessage 'P15 Kong proxy could not refresh its upstreams.'
    Invoke-P15Compose -StepArguments @('up', '--detach', '--force-recreate', '--no-deps', 'nginx') -FailureMessage 'P15 nginx edge proxy could not refresh its upstreams.'
    Invoke-P15Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'spectacular', '--format', 'openapi-json', '--validate', '--file', '/tmp/openapi-p15.json') -FailureMessage 'P15 container OpenAPI validation failed.'
    Invoke-P15Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'seed_p07_e2e') -FailureMessage 'P07 disposable journey seed failed.'
    Invoke-P15Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'seed_p08_e2e') -FailureMessage 'P08 disposable workspace seed failed.'
    Invoke-P15Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'seed_p15_e2e', '--run-id', $runId) -FailureMessage 'P15 disposable journey seed failed. Ensure the P02-P06 integration facts already exist.'

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
    if (-not $ready) { throw "P15 edge did not become ready. Last probe: $lastProbe" }

    Invoke-P15Compose -StepArguments @('stop', 'runtime-worker') -FailureMessage 'P15 could not pause the runtime worker for deterministic loading-page verification.'
    $runtimeWorkerStopped = $true
    Push-Location "$root\frontend"
    try {
        & npx.cmd playwright test e2e/p15f.spec.ts --project=student-web --workers=1
        $journeyExit = $LASTEXITCODE
    } finally { Pop-Location }
    Invoke-P15Compose -StepArguments @('up', '--detach', '--no-deps', 'runtime-worker') -FailureMessage 'P15 runtime worker could not be restored after the loading-page check.'
    $runtimeWorkerStopped = $false
    if ($journeyExit -ne 0) {
        & "$root\.venv\Scripts\python.exe" "$root\scripts\redact-playwright-artifacts.py" "$root\frontend\test-results"
        throw 'P15 complete Playwright journey failed; retained artifacts were scrubbed.'
    }

    Push-Location "$root\frontend"
    try {
        & npx.cmd playwright test e2e/p08.spec.ts e2e/p15e.spec.ts --project=student-web --project=teacher-web --project=admin-web --workers=1
        $regressionExit = $LASTEXITCODE
    } finally { Pop-Location }
    if ($regressionExit -ne 0) {
        & "$root\.venv\Scripts\python.exe" "$root\scripts\redact-playwright-artifacts.py" "$root\frontend\test-results"
        throw 'P15 workspace, Agent, or portal-boundary Playwright regression failed; retained artifacts were scrubbed.'
    }
    Write-Output "P15 container journey passed for project '$ProjectName'; production HA, capacity, recovery, and DNS/TLS remain pending."
} finally {
    if ($runtimeWorkerStopped) { & docker @compose up --detach --no-deps runtime-worker | Out-Null }
    foreach ($name in $previous.Keys) {
        $value = $previous[$name]
        if ($null -eq $value) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue } else { Set-Item "Env:$name" $value }
    }
}
