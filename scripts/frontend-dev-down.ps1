[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$compose = Join-Path $root 'docker-compose.frontend-dev.yml'

Push-Location $root
try {
    docker compose --project-name experimental-platform-frontend -f $compose down --remove-orphans
    if ($LASTEXITCODE -ne 0) { throw '前端开发服务停止失败。' }
    Write-Host '前端热更新服务已停止；后端服务和数据卷未删除。' -ForegroundColor Green
}
finally {
    Pop-Location
}
