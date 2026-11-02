<#
.SYNOPSIS
请求回滚指定 Swarm 服务，恢复情况需继续检查。
.DESCRIPTION
从仓库根目录调用。
#>
param(
    [string]$StackName = 'experimental-platform',
    [Parameter(Mandatory = $true)][string]$Service,
    [switch]$ConfirmTarget
)

$ErrorActionPreference = 'Stop'
if ($StackName -ne 'experimental-platform') { throw 'Only the project stack name experimental-platform is allowed.' }
if (-not $ConfirmTarget) { throw 'Rollback requires -ConfirmTarget and an explicit service name.' }
$qualified = if ($Service.StartsWith("$StackName`_")) { $Service } else { "$StackName`_$Service" }
if (-not $qualified.StartsWith("$StackName`_")) { throw "Service is outside the project stack: $Service" }
$serviceInfo = docker service inspect $qualified --format '{{index .Spec.Labels "com.docker.stack.namespace"}}' 2>$null
if ($serviceInfo -ne $StackName) { throw "Service is not owned by stack ${StackName}: $qualified" }
& docker service rollback $qualified
if ($LASTEXITCODE -ne 0) { throw "Rollback failed for $qualified" }
Write-Output "Rollback requested for $qualified. Inspect docker service ps before declaring recovery."
