<#
.SYNOPSIS
删除所选本地 Compose 项目的数据卷并重建环境；会丢失该项目数据。
.DESCRIPTION
从仓库根目录调用。
#>
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$compose = "$root\docker-compose.dev.yml"

if ($PSCmdlet.ShouldProcess('experimental-platform Docker Compose volumes', 'Remove and recreate empty Platform infrastructure data services')) {
    docker compose -f $compose down --volumes --remove-orphans
    if ($LASTEXITCODE -ne 0) { throw 'Failed to remove the local Platform infrastructure environment.' }
    docker compose -f $compose up --build --detach
    if ($LASTEXITCODE -ne 0) { throw 'Failed to recreate the local Platform infrastructure environment.' }
}

