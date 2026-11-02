<#
.SYNOPSIS
门户路由、健康接口、代理上下文与浏览器入口检查。
.DESCRIPTION
从仓库根目录调用。前置场景缺失：先恢复 scripts/README.md 所列测试文件或命令。
#>
param(
    [string]$Address = '127.0.0.1',
    [int]$Port = 8080
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
# Check browser-test prerequisites before creating or changing containers.
$frontendScripts = (Get-Content -Raw (Join-Path $root 'frontend/package.json') | ConvertFrom-Json).scripts
if (-not $frontendScripts.PSObject.Properties['test:e2e:student']) {
    throw 'Missing frontend npm command test:e2e:student; this historical browser gate requires restoration. See scripts/README.md.'
}
if (-not $frontendScripts.PSObject.Properties['test:e2e:teacher']) {
    throw 'Missing frontend npm command test:e2e:teacher; this historical browser gate requires restoration. See scripts/README.md.'
}
if (-not $frontendScripts.PSObject.Properties['test:e2e:admin']) {
    throw 'Missing frontend npm command test:e2e:admin; this historical browser gate requires restoration. See scripts/README.md.'
}

$npm = (Get-Command npm.cmd -ErrorAction Stop).Source

function Invoke-EdgeRequest {
    param([string]$HostName, [string]$Path, [hashtable]$Headers = @{})
    $requestHeaders = @{ Host = $HostName }
    foreach ($key in $Headers.Keys) { $requestHeaders[$key] = $Headers[$key] }
    Invoke-WebRequest -SkipHttpErrorCheck -UseBasicParsing -Uri "http://${Address}:${Port}${Path}" -Headers $requestHeaders
}

$portalHosts = @{
    'student.localhost' = 'USER'
    'teacher.localhost' = 'TEACHING'
    'admin.localhost' = 'PLATFORM'
}

foreach ($entry in $portalHosts.GetEnumerator()) {
    $homeResponse = Invoke-EdgeRequest -HostName $entry.Key -Path '/health'
    if ($homeResponse.StatusCode -ne 200) { throw "$($entry.Key) static application failed." }

    $health = Invoke-EdgeRequest -HostName $entry.Key -Path '/api/v2/health' -Headers @{
        'X-Portal' = 'FORGED'
        'X-Auth-Context' = 'FORGED'
    }
    if ($health.StatusCode -ne 200) { throw "$($entry.Key) health chain failed." }
    $payload = $health.Content | ConvertFrom-Json
    if ($payload.data.portal -ne $entry.Value) { throw "$($entry.Key) did not overwrite forged context." }
}

$machineHome = Invoke-EdgeRequest -HostName 'api.localhost' -Path '/'
if ($machineHome.StatusCode -ne 404) { throw 'Machine host unexpectedly served a web application.' }
$machineHealth = Invoke-EdgeRequest -HostName 'api.localhost' -Path '/api/v2/health'
if ($machineHealth.StatusCode -ne 404) { throw 'Machine host exposed a portal API.' }

$sse = Invoke-EdgeRequest -HostName 'student.localhost' -Path '/api/v2/events/stream'
if ($sse.StatusCode -ne 200 -or $sse.Headers['X-Accel-Buffering'] -ne 'no') {
    throw 'SSE proxy buffering contract failed.'
}

Push-Location "$root\frontend"
try {
    $env:PLAYWRIGHT_CHANNEL = $env:PLAYWRIGHT_CHANNEL ?? 'chrome'
    $env:STUDENT_WEB_URL = "http://student.localhost:$Port"
    $env:TEACHER_WEB_URL = "http://teacher.localhost:$Port"
    $env:ADMIN_WEB_URL = "http://admin.localhost:$Port"
    & $npm run test:e2e:student
    if ($LASTEXITCODE -ne 0) { throw 'Student portal E2E failed.' }
    & $npm run test:e2e:teacher
    if ($LASTEXITCODE -ne 0) { throw 'Teacher portal E2E failed.' }
    & $npm run test:e2e:admin
    if ($LASTEXITCODE -ne 0) { throw 'Admin portal E2E failed.' }
} finally { Pop-Location }

Write-Output 'Platform infrastructure edge verification passed.'
