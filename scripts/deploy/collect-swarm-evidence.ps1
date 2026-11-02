<#
.SYNOPSIS
收集服务栈、节点与运行时网络的原始状态输出，仅留本地。
.DESCRIPTION
从仓库根目录调用。
#>
param(
    [string]$StackName = 'experimental-platform',
    [string]$OutputDirectory = ''
)

$ErrorActionPreference = 'Stop'
if ($StackName -ne 'experimental-platform') { throw 'Only the project stack name experimental-platform is allowed.' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmssK'
$target = if ($OutputDirectory) { [IO.Path]::GetFullPath($OutputDirectory) } else { Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "evidence/swarm/$stamp" }
New-Item -ItemType Directory -Force -Path $target | Out-Null

function Save-Command {
    param([string]$Name, [string[]]$Arguments)
    $path = Join-Path $target "$Name.txt"
    & docker @Arguments 2>&1 | Out-File -LiteralPath $path -Encoding utf8
    if ($LASTEXITCODE -ne 0) { Add-Content -LiteralPath $path -Value "command_exit_code=$LASTEXITCODE" }
}

Save-Command 'docker-version' @('version')
Save-Command 'docker-info' @('info')
Save-Command 'swarm-nodes' @('node', 'ls')
Save-Command 'stack-services' @('stack', 'services', $StackName)
Save-Command 'stack-tasks' @('stack', 'ps', $StackName, '--no-trunc')
Save-Command 'runtime-network' @('network', 'inspect', 'experimental-platform-swarm-runtime')

$services = docker stack services $StackName --format '{{.Name}}' 2>$null
foreach ($service in $services) {
    if ($service.StartsWith("$StackName`_")) { Save-Command ("service-" + ($service -replace '[^A-Za-z0-9_.-]', '_')) @('service', 'inspect', $service) }
}

$manifest = [ordered]@{
    stack = $StackName
    collected_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    app_version = $env:APP_VERSION
    openapi_revision = $env:OPENAPI_REVISION
    image_tag = $env:IMAGE_TAG
    registry = $env:REGISTRY
    limitation = 'Single-node evidence cannot establish HA, production performance, external storage recovery, or RPO/RTO.'
}
$manifest | ConvertTo-Json | Out-File -LiteralPath (Join-Path $target 'manifest.json') -Encoding utf8
Write-Output "Swarm runtime evidence collected at $target (secrets are not collected)."
