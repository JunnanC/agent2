<#
.SYNOPSIS
准备单节点 Swarm 适配器测试环境；初始化必须显式指定参数。
.DESCRIPTION
从仓库根目录调用。
#>
param(
    [string]$AdvertiseAddr = "",
    [string]$RuntimeNode = "",
    [switch]$InitializeIfInactive
)

$ErrorActionPreference = 'Stop'

function Invoke-Docker {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed: docker $($Arguments -join ' ')" }
}

$state = docker info --format '{{.Swarm.LocalNodeState}}' 2>$null
if ($state -ne 'active') {
    if (-not $InitializeIfInactive) {
        throw 'Swarm is inactive. Re-run with -InitializeIfInactive and an explicit -AdvertiseAddr.'
    }
    if ([string]::IsNullOrWhiteSpace($AdvertiseAddr)) {
        throw '-AdvertiseAddr is required when initializing a Swarm.'
    }
    & docker swarm init --advertise-addr $AdvertiseAddr *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Swarm initialization failed.' }
}

$self = docker info --format '{{.Name}}'
if ([string]::IsNullOrWhiteSpace($self)) { throw 'Unable to resolve the local Swarm node.' }

$runtime = if ([string]::IsNullOrWhiteSpace($RuntimeNode)) { $self } else { $RuntimeNode }
$runtimeNodeExists = docker node inspect $runtime --format '{{.Description.Hostname}}' 2>$null
if ([string]::IsNullOrWhiteSpace($runtimeNodeExists)) { throw "Runtime node not found: $runtime" }

Invoke-Docker node update --label-add edu.platform.managed=true --label-add edu.role.edge=true --label-add edu.role.app=true --label-add edu.role.worker=true --label-add edu.role.data=true $self
Invoke-Docker node update --label-add edu.platform.managed=true --label-add edu.role.runtime=true $runtime

$network = docker network ls --filter name=^experimental-platform-swarm-runtime$ --format '{{.Name}}'
if (-not $network) {
    Invoke-Docker network create --driver overlay --scope swarm --internal --label edu.platform.managed=true --label edu.platform.kind=runtime-gateway-network experimental-platform-swarm-runtime
}

Write-Output "Swarm runtime local Swarm ready. manager=$self runtime=$runtime network=experimental-platform-swarm-runtime"
Write-Output 'This proves only single-node runtime behavior. HA, external services, TLS, recovery, and performance remain pending real-environment acceptance.'
