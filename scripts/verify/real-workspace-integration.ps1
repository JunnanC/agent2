<#
.SYNOPSIS
真实工作区浏览器流程、令牌隔离、快照摘要与测试资源回收。
.DESCRIPTION
从仓库根目录调用。前置场景缺失：先恢复 scripts/README.md 所列测试文件或命令。
#>
param(
    [string]$ProjectName = 'experimental-platform',
    [int]$EntryPort = 8080,
    [string]$RuntimeImage = 'experimental-platform-workspace:local',
    [string]$OutputDirectory = '',
    [string]$SeedPassword = 'Integration-Disposable-Seed-Only-2026!',
    [switch]$SkipRuntimeBuild,
    [switch]$SeedPrerequisites
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
# Check browser-test prerequisites before creating or changing containers.
if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend/e2e/real-workspace.spec.ts'))) {
    throw 'Missing browser scenario frontend/e2e/real-workspace.spec.ts; restore that scenario before running this verification. See scripts/README.md.'
}

$composeFile = Join-Path $root 'docker-compose.dev.yml'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') { throw 'ProjectName must be a narrow Docker Compose project identifier.' }
if ($EntryPort -lt 1 -or $EntryPort -gt 65535) { throw 'EntryPort must be a valid TCP port.' }
if ($RuntimeImage -match ':latest$' -or $RuntimeImage -notmatch '^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}$') { throw 'RuntimeImage must be a fixed OCI image reference, never :latest.' }

$stamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMdd-HHmmss')
$evidence = if ($OutputDirectory) { [IO.Path]::GetFullPath($OutputDirectory) } else { Join-Path $root "evidence/real-workspace/$stamp" }
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
$compose = @('compose', '--profile', 'runtime', '-p', $ProjectName, '-f', $composeFile)
$runId = [DateTimeOffset]::UtcNow.ToString('yyyyMMddHHmmss')
$taskTitle = "真实工作区验收 $runId"
$seeded = $false
$result = 'failed'
$journeyPassed = $false
$taskId = ''
$imageId = ''
$imageDigest = ''
$previous = @{}
$environmentNames = @(
    'APP_VERSION', 'OPENAPI_REVISION', 'ENTRY_PORT', 'E2E_SEED_PASSWORD',
    'REAL_WORKSPACE_E2E_TASK_TITLE', 'REAL_WORKSPACE_COMPOSE_PROJECT', 'REAL_WORKSPACE_COMPOSE_FILE',
    'STUDENT_WEB_URL', 'TEACHER_WEB_URL', 'ADMIN_WEB_URL', 'APP_NETWORK_SUBNET', 'FLUENTD_HOST_PORT',
    'MINIO_API_PORT', 'MINIO_CONSOLE_PORT', 'PROMETHEUS_PORT', 'LOCAL_RUNTIME_IMAGE',
    'LOCAL_RUNTIME_MODE', 'LOCAL_RUNTIME_NETWORK', 'RUNTIME_ADAPTER_CONFIGS'
)
foreach ($name in $environmentNames) { $previous[$name] = [Environment]::GetEnvironmentVariable($name) }

function Invoke-Compose {
    param([string[]]$StepArguments, [string]$FailureMessage)
    & docker @compose @StepArguments
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
}

try {
    if ($RuntimeImage -eq 'experimental-platform-workspace:local' -and -not $SkipRuntimeBuild) {
        & docker buildx build --load --platform linux/amd64 --provenance=false --tag $RuntimeImage (Join-Path $root 'runtime/algorithm-workspace')
        if ($LASTEXITCODE -ne 0) { throw 'Real workspace runtime image build failed.' }
    } elseif (-not (docker image inspect $RuntimeImage 2>$null)) {
        throw 'The requested fixed runtime image is not available in the local Docker Engine.'
    }
    $imageId = (& docker image inspect --format '{{.Id}}' $RuntimeImage).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $imageId.StartsWith('sha256:')) { throw 'Real workspace runtime image inspect did not return an immutable image id.' }
    $repoDigest = (& docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' $RuntimeImage).Trim()
    $imageDigest = $imageId
    if ($repoDigest.Contains('@')) { $imageDigest = [string](($repoDigest -split "`n")[0] -split '@', 2)[1] }
    $imageId | Out-File -LiteralPath (Join-Path $evidence 'runtime-image-id.txt') -Encoding utf8
    $imageDigest | Out-File -LiteralPath (Join-Path $evidence 'runtime-image-digest.txt') -Encoding utf8

    $env:APP_VERSION = '0.16.0-p16'
    $env:OPENAPI_REVISION = 'v2-p16'
    $env:ENTRY_PORT = [string]$EntryPort
    $env:E2E_SEED_PASSWORD = $SeedPassword
    $env:REAL_WORKSPACE_E2E_TASK_TITLE = $taskTitle
    $env:REAL_WORKSPACE_COMPOSE_PROJECT = $ProjectName
    $env:REAL_WORKSPACE_COMPOSE_FILE = $composeFile
    $env:STUDENT_WEB_URL = "http://student.localhost:$EntryPort"
    $env:TEACHER_WEB_URL = "http://teacher.localhost:$EntryPort"
    $env:ADMIN_WEB_URL = "http://admin.localhost:$EntryPort"
    $env:LOCAL_RUNTIME_IMAGE = $RuntimeImage
    $env:LOCAL_RUNTIME_MODE = 'REAL'
    $env:LOCAL_RUNTIME_NETWORK = "${ProjectName}-runtime"
    $env:RUNTIME_ADAPTER_CONFIGS = ('{"runtime/local-docker":{"runtime_network":"' + $env:LOCAL_RUNTIME_NETWORK + '","image":"' + $RuntimeImage + '","pids_limit":128}}')

    $composeUpArgs = @('up')
    if ($SkipRuntimeBuild) {
        # Build every application service explicitly, but never rebuild the promoted digest.
        $buildServices = @('core-check', 'migrate', 'django', 'celery', 'celery-beat', 'runtime-worker', 'workspace-gateway', 'log-ingest', 'nginx')
        Invoke-Compose -StepArguments (@('build') + $buildServices) -FailureMessage 'Real workspace Compose application services failed to build.'
        $composeUpArgs += '--no-build'
    } else {
        $composeUpArgs += '--build'
    }
    $composeUpArgs += @('--detach', 'migrate', 'django', 'celery', 'celery-beat', 'runtime-worker', 'workspace-gateway', 'nginx')
    Invoke-Compose -StepArguments $composeUpArgs -FailureMessage 'Real workspace Compose services failed to build or start.'
    # Long-running Kong replicas cache Compose DNS answers across Django recreation.
    Invoke-Compose -StepArguments @('restart', 'kong') -FailureMessage 'Real workspace Kong replicas failed to refresh upstream DNS.'
    Invoke-Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'spectacular', '--format', 'openapi-json', '--validate', '--file', '/tmp/openapi-real-workspace.json') -FailureMessage 'Real workspace container OpenAPI validation failed.'

    if ($SeedPrerequisites) {
        Invoke-Compose -StepArguments @('--profile', 'tools', 'run', '--rm', '--no-deps', '-e', "PLATFORM_ADMIN_BOOTSTRAP_PASSWORD=$SeedPassword", 'core-check', 'python', 'manage.py', 'bootstrap_platform_admin', '--email', 'admin.integration@example.edu', '--username', 'integration-admin', '--display-name', 'Integration Admin') -FailureMessage 'Real workspace platform administrator bootstrap failed.'
        $seedChain = @(
            @('-e', "E2E_SEED_PASSWORD=$SeedPassword", 'django', 'python', 'manage.py', 'seed_accounts_e2e'),
            @('django', 'python', 'manage.py', 'seed_courses_e2e'),
            @('django', 'python', 'manage.py', 'seed_governance_defaults'),
            @('django', 'python', 'manage.py', 'seed_governance_e2e'),
            @('django', 'python', 'manage.py', 'seed_templates_e2e'),
            @('django', 'python', 'manage.py', 'seed_publications_e2e'),
            @('django', 'python', 'manage.py', 'seed_simulated_experiment'),
            @('django', 'python', 'manage.py', 'seed_workspaces_e2e'),
            @('django', 'python', 'manage.py', 'seed_reviews_e2e')
        )
        foreach ($seedArguments in $seedChain) {
            Invoke-Compose -StepArguments (@('exec', '-T') + $seedArguments) -FailureMessage ("Real workspace prerequisite seed failed: " + ($seedArguments[-1]))
        }
    }

    $ready = $false
    $consecutiveReady = 0
    $lastProbe = 'no response'
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        try {
            $health = Invoke-WebRequest -Uri "$($env:STUDENT_WEB_URL)/api/v2/health" -TimeoutSec 5 -NoProxy
            $lastProbe = "status=$($health.StatusCode) body=$($health.Content)"
            if ($health.StatusCode -eq 200 -and $health.Content -match 'v2-p16') {
                $consecutiveReady++
                if ($consecutiveReady -ge 6) { $ready = $true; break }
            } else { $consecutiveReady = 0 }
        } catch {
            $consecutiveReady = 0
            $lastProbe = $_.Exception.Message
        }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw "Real workspace edge did not become ready. Last probe: $lastProbe" }

    $seedOutput = & docker @compose exec -T -e "WORKSPACE_E2E_IMAGE_DIGEST=$imageDigest" django python manage.py seed_real_workspace_e2e --run-id $runId 2>&1
    $seedExit = $LASTEXITCODE
    $seedOutput | Out-File -LiteralPath (Join-Path $evidence 'seed.log') -Encoding utf8
    if ($seedExit -ne 0) { throw 'Real workspace disposable real-runtime seed failed.' }
    $seeded = $true
    $seedText = $seedOutput -join "`n"
    if ($seedText -match '\btask=([A-Za-z0-9_-]+)\b') { $taskId = $Matches[1] }
    if (-not $taskId) { throw 'Real workspace seed output did not return a task id for scoped cleanup.' }

    $playwrightCommand = 'npm ci --ignore-scripts && npx playwright test e2e/real-workspace.spec.ts --project=student-web --workers=1'
    $playwrightArgs = @(
        'run', '--rm', '--network', 'host', '--volume', "$(Join-Path $root 'frontend'):/work/frontend",
        '--volume', '/work/frontend/node_modules',
        '--workdir', '/work/frontend', '--env', "E2E_SEED_PASSWORD=$SeedPassword", '--env', "REAL_WORKSPACE_E2E_TASK_TITLE=$taskTitle",
        '--env', "STUDENT_WEB_URL=http://student.localhost:$EntryPort", '--env', "TEACHER_WEB_URL=http://teacher.localhost:$EntryPort",
        '--env', "REAL_WORKSPACE_COMPOSE_PROJECT=$ProjectName", '--env', "REAL_WORKSPACE_COMPOSE_FILE=/work/compose.dev.yml",
        'mcr.microsoft.com/playwright:v1.55.1-noble', 'bash', '-lc', $playwrightCommand
    )
    # The Playwright image is the only Node/browser runtime used by this gate.
    & docker @playwrightArgs 2>&1 | Tee-Object -FilePath (Join-Path $evidence 'playwright.log')
    $playwrightExit = $LASTEXITCODE
    & docker run --rm --volume "$(Join-Path $root 'frontend/test-results'):/artifacts" --volume "$(Join-Path $root 'scripts'):/scripts:ro" python:3.14-slim python /scripts/verify/redact-browser-artifacts.py /artifacts
    if ($LASTEXITCODE -ne 0) { throw 'Real workspace Playwright artifact redaction failed.' }
    if ($playwrightExit -ne 0) { throw 'Real workspace Docker Playwright journey failed; retained artifacts were scrubbed.' }

    $boundary = & docker @compose exec -T runtime-worker python manage.py verify_workspace_token_boundary --title $taskTitle 2>&1
    $boundaryExit = $LASTEXITCODE
    $boundary | Out-File -LiteralPath (Join-Path $evidence 'runtime-boundary.json') -Encoding utf8
    if ($boundaryExit -ne 0) { throw 'Real workspace instance upstream-token boundary verification failed.' }

    $before = & docker @compose exec -T runtime-worker python manage.py collect_workspace_evidence --title $taskTitle 2>&1
    $before | Out-File -LiteralPath (Join-Path $evidence 'before-cleanup.json') -Encoding utf8
    $jsonLine = ($before | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1)
    if ($jsonLine) {
        $beforeObject = $jsonLine | ConvertFrom-Json
        $taskId = [string]$beforeObject.task_id
    }
    if (-not $taskId) { throw 'Real workspace evidence did not return a task id.' }
    if ($beforeObject.latest_snapshot_digest -ne $beforeObject.runtime_file_digest -or $beforeObject.latest_snapshot_digest -ne $beforeObject.minio_object_digest) {
        throw 'Real workspace snapshot digest does not match both MinIO and the live workspace file.'
    }
    $journeyPassed = $true
} finally {
    if ($seeded) {
        & docker @compose exec -T runtime-worker python manage.py cleanup_workspace_e2e --title $taskTitle 2>&1 | Tee-Object -FilePath (Join-Path $evidence 'cleanup.log') | Out-Null
        $cleanupExit = $LASTEXITCODE
        $cleanupResources = [ordered]@{
            containers = @(& docker ps -a --filter "label=edu.platform.task=$taskId" --format '{{json .}}' 2>$null)
            volumes = @(& docker volume ls --filter "label=edu.platform.task=$taskId" --format '{{json .}}' 2>$null)
        }
        $cleanupResources | ConvertTo-Json -Depth 4 | Out-File -LiteralPath (Join-Path $evidence 'resources-after-cleanup.json') -Encoding utf8
        $after = & docker @compose exec -T runtime-worker python manage.py collect_workspace_evidence --title $taskTitle 2>&1
        $afterExit = $LASTEXITCODE
        $after | Out-File -LiteralPath (Join-Path $evidence 'after-cleanup.json') -Encoding utf8
        $afterJsonLine = ($after | Where-Object { $_ -match '^\s*\{' } | Select-Object -Last 1)
        $afterObject = if ($afterJsonLine) { $afterJsonLine | ConvertFrom-Json } else { $null }
        $resourcesRemain = $cleanupResources.containers.Count -gt 0 -or $cleanupResources.volumes.Count -gt 0
        if ($journeyPassed -and $cleanupExit -eq 0 -and $afterExit -eq 0 -and -not $resourcesRemain -and $afterObject.instance_status -eq 'DESTROYED' -and $afterObject.session_status -eq 'REVOKED') {
            $result = 'passed'
        }
    }
    $summary = [ordered]@{
        phase = 'real-workspace-integration'
        result = $result
        collected_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        project = $ProjectName
        image = $RuntimeImage
        image_id = $imageId
        image_digest = $imageDigest
        task_title = $taskTitle
        task_id = $taskId
        docker_playwright = $true
        evidence = [ordered]@{
            seed = 'seed.log'
            journey = 'playwright.log'
            boundary = 'runtime-boundary.json'
            before_cleanup = 'before-cleanup.json'
            cleanup = 'cleanup.log'
            after_cleanup = 'after-cleanup.json'
            resources_after_cleanup = 'resources-after-cleanup.json'
        }
        limitation = 'Local Docker evidence only; registry promotion and real Swarm acceptance remain pending.'
    }
    $summary | ConvertTo-Json -Depth 6 | Out-File -LiteralPath (Join-Path $evidence 'summary.json') -Encoding utf8
    foreach ($name in $environmentNames) {
        $value = $previous[$name]
        if ($null -eq $value) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue } else { Set-Item "Env:$name" $value }
    }
}

if ($result -ne 'passed') { throw "Real workspace failed. Evidence: $evidence" }
Write-Output "Real workspace Docker full journey passed. Evidence: $evidence"
