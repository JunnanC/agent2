param(
    [string]$StackName = 'edu-platform',
    [string]$OutputDirectory = ''
)

$ErrorActionPreference = 'Stop'
if ($StackName -ne 'edu-platform') { throw 'Only the project stack name edu-platform is allowed.' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmssK'
$target = if ($OutputDirectory) { [IO.Path]::GetFullPath($OutputDirectory) } else { Join-Path (Join-Path $PSScriptRoot '..') "evidence/p14/$stamp" }
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
Save-Command 'runtime-network' @('network', 'inspect', 'edu-runtime')

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
Write-Output "P14 evidence collected at $target (secrets are not collected)."
