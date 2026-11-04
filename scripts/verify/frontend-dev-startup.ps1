$ErrorActionPreference = 'Stop'
$startup = Join-Path (Split-Path -Parent $PSScriptRoot) 'frontend-dev-up.ps1'
$frontendCompose = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'docker-compose.frontend-dev.yml'
$global:frontendDevDockerCalls = [System.Collections.Generic.List[string]]::new()

function docker {
    $global:frontendDevDockerCalls.Add(($args -join ' '))
    $global:LASTEXITCODE = 0
}

function Get-NetTCPConnection {}

& $startup
if ($global:frontendDevDockerCalls.Count -ne 2) { throw '默认启动应分别调用后端和前端 Compose。' }
if ($global:frontendDevDockerCalls[0] -ne 'compose --profile runtime --env-file .env up -d --build') {
    throw "后端启动应沿用 .env 中的 Compose 配置，实际调用：$($global:frontendDevDockerCalls[0])"
}
$frontendCommand = "compose --project-name edu-platform-frontend-dev -f $frontendCompose up -d"
if ($global:frontendDevDockerCalls[1] -ne $frontendCommand) { throw '前端应使用独立热更新配置。' }

$global:frontendDevDockerCalls.Clear()
& $startup -SkipBackend
if ($global:frontendDevDockerCalls.Count -ne 1 -or $global:frontendDevDockerCalls[0] -ne $frontendCommand) {
    throw '-SkipBackend 应仅启动前端。'
}

Write-Host '前端启动脚本检查通过（Docker 与端口查询均使用替身）。'
