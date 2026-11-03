[CmdletBinding()]
param(
    [switch]$SkipBackend,
    [int]$StudentPort = 5173,
    [int]$TeacherPort = 5174,
    [int]$AdminPort = 5176
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$compose = Join-Path $root 'docker-compose.frontend-dev.yml'
$backendCompose = Join-Path $root 'docker-compose.dev.yml'
$backendCompat = Join-Path $root 'docker-compose.p14-compat.yml'
$backendProject = 'edu-platform-p14'
$project = 'edu-platform-frontend-dev'

function Assert-Command([string]$name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "缺少命令 '$name'。请先安装 Docker Desktop。"
    }
}

function Assert-PortAvailable([int]$port) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if ($listener) {
        throw "端口 $port 已被占用。请停止占用该端口的进程，或修改 docker-compose.frontend-dev.yml 的端口映射。"
    }
}

Assert-Command 'docker'
if (-not (Test-Path -LiteralPath $compose)) { throw "找不到 $compose" }
if (-not (Test-Path -LiteralPath $backendCompat)) { throw "找不到 $backendCompat" }
if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend\package-lock.json'))) { throw '找不到 frontend/package-lock.json' }

foreach ($port in @($StudentPort, $TeacherPort, $AdminPort)) { Assert-PortAvailable $port }

Push-Location $root
try {
    if (-not $SkipBackend) {
        Write-Host '确保后端 Compose 服务正在运行...'
        docker compose --project-name $backendProject --profile p14 --env-file .env -f $backendCompose -f $backendCompat up -d --build
        if ($LASTEXITCODE -ne 0) { throw '后端 Compose 启动失败。' }
    }

    Write-Host '启动前端 Vite 热更新服务...'
    $env:FRONTEND_STUDENT_PORT = $StudentPort
    $env:FRONTEND_TEACHER_PORT = $TeacherPort
    $env:FRONTEND_ADMIN_PORT = $AdminPort
    docker compose --project-name $project -f $compose up -d
    if ($LASTEXITCODE -ne 0) { throw '前端开发服务启动失败。' }

    Write-Host ''
    Write-Host '前端热更新开发模式已启动：' -ForegroundColor Green
    Write-Host "  学生端: http://student.localhost:$StudentPort"
    Write-Host "  教师端: http://teacher.localhost:$TeacherPort"
    Write-Host "  管理端: http://admin.localhost:$AdminPort"
    Write-Host '  静态入口仍为: http://student.localhost:8080 / teacher.localhost:8080 / admin.localhost:8080'
    Write-Host ''
    Write-Host "查看日志: docker compose --project-name $project -f docker-compose.frontend-dev.yml logs -f"
    Write-Host '停止前端: .\scripts\frontend-dev-down.ps1'
}
finally {
    Pop-Location
}
