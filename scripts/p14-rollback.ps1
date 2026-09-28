param(
    [string]$StackName = 'edu-platform',
    [Parameter(Mandatory = $true)][string]$Service,
    [switch]$ConfirmTarget
)

$ErrorActionPreference = 'Stop'
if ($StackName -ne 'edu-platform') { throw 'Only the project stack name edu-platform is allowed.' }
if (-not $ConfirmTarget) { throw 'Rollback requires -ConfirmTarget and an explicit service name.' }
$qualified = if ($Service.StartsWith("$StackName`_")) { $Service } else { "$StackName`_$Service" }
if (-not $qualified.StartsWith("$StackName`_")) { throw "Service is outside the project stack: $Service" }
$serviceInfo = docker service inspect $qualified --format '{{index .Spec.Labels "com.docker.stack.namespace"}}' 2>$null
if ($serviceInfo -ne $StackName) { throw "Service is not owned by stack ${StackName}: $qualified" }
& docker service rollback $qualified
if ($LASTEXITCODE -ne 0) { throw "Rollback failed for $qualified" }
Write-Output "Rollback requested for $qualified. Inspect docker service ps before declaring recovery."
