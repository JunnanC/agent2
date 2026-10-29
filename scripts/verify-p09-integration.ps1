param(
    [string]$ProjectName = 'edu-platform-p09-verify',
    [switch]$KeepEnvironment
)

$ErrorActionPreference = 'Stop'
if ($ProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') { throw 'ProjectName must be a narrow Docker Compose project identifier.' }
$root = Split-Path -Parent $PSScriptRoot
$compose = @('compose', '-p', $ProjectName, '-f', "$root\docker-compose.dev.yml")

function Invoke-P09Compose {
    param(
        [string[]]$StepArguments,
        [string]$FailureMessage
    )
    & docker @compose @StepArguments
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
}

$existingContainers = & docker @compose ps --all --quiet
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the isolated P09 Compose project.' }
$existingVolumes = & docker volume ls --quiet --filter "label=com.docker.compose.project=$ProjectName"
if ($existingContainers -or $existingVolumes) {
    throw "Compose project '$ProjectName' already owns containers or volumes. Choose a fresh project name to protect existing data."
}

$previous = @{}
foreach ($name in @('APP_VERSION', 'OPENAPI_REVISION', 'ENTRY_PORT', 'APP_NETWORK_SUBNET', 'FLUENTD_HOST_PORT', 'MINIO_API_PORT', 'MINIO_CONSOLE_PORT', 'PROMETHEUS_PORT', 'P02_E2E_PASSWORD', 'STUDENT_WEB_URL', 'TEACHER_WEB_URL', 'ADMIN_WEB_URL')) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name)
}
$env:APP_VERSION = '0.9.0-p09'
$env:OPENAPI_REVISION = 'v2-p09'
$env:ENTRY_PORT = '18089'
$env:APP_NETWORK_SUBNET = '172.33.209.0/24'
$env:FLUENTD_HOST_PORT = '24231'
$env:MINIO_API_PORT = '19029'
$env:MINIO_CONSOLE_PORT = '19030'
$env:PROMETHEUS_PORT = '19109'

try {
    Invoke-P09Compose -StepArguments @('up', '--build', '--detach', 'mysql', 'redis', 'mysql-users', 'migrate', 'mysql-grants', 'minio', 'clamav', 'minio-init') -FailureMessage 'P09 database, object storage, or scanner dependencies failed to start.'
    Invoke-P09Compose -StepArguments @('up', '--build', '--detach', 'django', 'celery') -FailureMessage 'P09 Django or Celery failed to start.'
    Invoke-P09Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'spectacular', '--format', 'openapi-json', '--validate', '--file', '/tmp/openapi-p09.json') -FailureMessage 'P09 container OpenAPI validation failed.'

    $seedPassword = 'P09-Disposable-Seed-Only-2026!'
    Invoke-P09Compose -StepArguments @('exec', '-T', '-e', "PLATFORM_ADMIN_BOOTSTRAP_PASSWORD=$seedPassword", 'django', 'python', 'manage.py', 'bootstrap_platform_admin', '--email', 'admin.integration@example.edu', '--username', 'integration-admin', '--display-name', 'Integration Admin') -FailureMessage 'P09 platform administrator seed failed.'
    Invoke-P09Compose -StepArguments @('exec', '-T', '-e', "P02_E2E_PASSWORD=$seedPassword", 'django', 'python', 'manage.py', 'seed_p02_e2e') -FailureMessage 'P09 P02 disposable seed failed.'
    Invoke-P09Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'seed_p03_e2e') -FailureMessage 'P09 P03 disposable seed failed.'
    Invoke-P09Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'seed_governance_defaults') -FailureMessage 'P09 governance seed failed.'
    Invoke-P09Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'seed_p04_e2e') -FailureMessage 'P09 P04 disposable seed failed.'
    Invoke-P09Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'seed_p05_e2e') -FailureMessage 'P09 P05 disposable seed failed.'
    Invoke-P09Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'seed_p06_e2e') -FailureMessage 'P09 P06 disposable seed failed.'
    Invoke-P09Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'seed_p07_e2e') -FailureMessage 'P09 P07 disposable seed failed.'
    Invoke-P09Compose -StepArguments @('exec', '-T', 'django', 'python', 'manage.py', 'seed_p08_e2e') -FailureMessage 'P09 P08 disposable seed failed.'

    Invoke-P09Compose -StepArguments @('up', '--build', '--detach') -FailureMessage 'P09 full local edge stack failed to start.'
    $env:P02_E2E_PASSWORD = $seedPassword
    $env:STUDENT_WEB_URL = 'http://student.localhost:18089'
    $env:TEACHER_WEB_URL = 'http://teacher.localhost:18089'
    $env:ADMIN_WEB_URL = 'http://admin.localhost:18089'
    $ready = $false
    $lastProbe = 'no response'
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $healthText = & curl.exe --noproxy '*' --silent --show-error --max-time 5 --write-out "`nHTTP_STATUS:%{http_code}" "$($env:STUDENT_WEB_URL)/api/v2/health" | Out-String
            if ($LASTEXITCODE -ne 0) { throw $healthText.Trim() }
            if ($healthText -match '(?s)^(?<body>.*)\r?\nHTTP_STATUS:(?<status>\d{3})\s*$') {
                $healthBody = $Matches.body.Trim()
                $healthStatus = [int]$Matches.status
                $lastProbe = "status=$healthStatus body=$healthBody"
                if ($healthStatus -eq 200 -and $healthBody -match '"openapi_revision"\s*:\s*"v2-p09"') { $ready = $true; break }
            } else {
                $lastProbe = $healthText.Trim()
            }
        } catch { $lastProbe = $_.Exception.Message }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw "P09 local edge stack did not become ready. Last probe: $lastProbe" }

    Push-Location "$root\frontend"
    try {
        & npx.cmd playwright test e2e/p09.spec.ts --project=student-web --project=admin-web --workers=1
        if ($LASTEXITCODE -ne 0) { throw 'P09 student, teacher, or admin Playwright verification failed.' }
    } finally { Pop-Location }
    Write-Output 'P09 isolated Compose, MySQL migrations, MinIO, ClamAV, Celery, Nginx-to-Kong edge, OpenAPI, and three-portal Playwright checks passed. Production environment evidence remains outstanding.'
} finally {
    foreach ($name in $previous.Keys) {
        $value = $previous[$name]
        if ($null -eq $value) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue } else { Set-Item "Env:$name" $value }
    }
    if (-not $KeepEnvironment) {
        & docker @compose down --volumes --remove-orphans
        if ($LASTEXITCODE -ne 0) { throw 'P09 isolated Compose cleanup failed.' }
    }
}
