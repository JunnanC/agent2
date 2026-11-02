<#
.SYNOPSIS
按已通过的真实工作区证据晋级镜像，保留 Registry digest 和回滚清单。
.DESCRIPTION
从仓库根目录调用。
#>
param(
    [string]$SourceImage = 'experimental-platform-workspace:local',
    [string]$Registry = 'localhost:5000',
    [string]$Repository = 'experimental-platform-workspace',
    [string]$PromotionTag = 'candidate',
    [string]$RollbackTag = 'rollback',
    [string]$RegistryContainerName = 'experimental-platform-image-registry',
    [int]$RegistryPort = 5000,
    [string]$SourceEvidenceDirectory = '',
    [string]$OutputDirectory = '',
    [int]$JourneyPort = 8180,
    [string]$JourneyAppNetworkSubnet = '172.31.20.0/24',
    [int]$JourneyFluentdPort = 24225,
    [int]$JourneyMinioApiPort = 9100,
    [int]$JourneyMinioConsolePort = 9101,
    [int]$JourneyPrometheusPort = 9190,
    [string]$JourneyProjectName = 'experimental-platform',
    [switch]$JourneyUseExistingEnvironment,
    [switch]$SkipJourney,
    [switch]$RemoveLocalRegistry
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $SkipJourney -and -not (Test-Path -LiteralPath (Join-Path $root 'frontend/e2e/real-workspace.spec.ts'))) {
    throw 'Missing browser scenario frontend/e2e/real-workspace.spec.ts; restore it before image promotion with journey verification. See scripts/README.md.'
}
$registryContainerCreated = $false
$promotionDigest = ''
$rollbackDigest = ''
$journeyResult = 'not_started'
$result = 'failed'
$previousAppNetworkSubnet = [Environment]::GetEnvironmentVariable('APP_NETWORK_SUBNET')

function Invoke-Docker {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$FailureMessage,
        [string]$OutputPath = ''
    )
    $output = & docker @Arguments 2>&1
    if ($OutputPath) { $output | Out-File -LiteralPath $OutputPath -Encoding utf8 }
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
    return @($output)
}

function Assert-ReferencePart {
    param([string]$Value, [string]$Name)
    if ([string]::IsNullOrWhiteSpace($Value) -or $Value -match '[\s\\]' -or $Value -match ':latest$') {
        throw "$Name must be a fixed OCI reference component and may not use :latest."
    }
}

function Get-DigestFromOutput {
    param([string[]]$Lines)
    $joined = $Lines -join "`n"
    $match = [regex]::Match($joined, '(?i)(?:digest|Digest):\s*(sha256:[0-9a-f]{64})')
    if ($match.Success) { return $match.Groups[1].Value.ToLowerInvariant() }
    return ''
}

function Get-SourceEvidence {
    param([string]$ExplicitDirectory, [string]$ExpectedImage, [string]$ExpectedDigest)
    $candidates = @()
    if ($ExplicitDirectory) {
        $candidates = @(Get-Item -LiteralPath $ExplicitDirectory -ErrorAction Stop)
    } else {
        $evidenceRoot = Join-Path $root 'evidence/real-workspace'
        if (Test-Path -LiteralPath $evidenceRoot) {
            $candidates = @(Get-ChildItem -LiteralPath $evidenceRoot -Directory | Sort-Object LastWriteTime -Descending)
        }
    }
    foreach ($candidate in $candidates) {
        $summaryPath = Join-Path $candidate.FullName 'summary.json'
        if (-not (Test-Path -LiteralPath $summaryPath)) { continue }
        try { $summary = Get-Content -Raw -Encoding UTF8 $summaryPath | ConvertFrom-Json } catch { continue }
        if ($summary.phase -notin @('real-workspace-integration', 'P16-F') -or $summary.result -ne 'passed') { continue }
        $summaryDigest = [string]$summary.image_digest
        $summaryImage = [string]$summary.image
        if (($summaryDigest -eq $ExpectedDigest -or $summaryImage -eq $ExpectedImage) -and $summaryDigest -eq $ExpectedDigest) {
            return [ordered]@{ directory = $candidate.FullName; summary = $summary }
        }
    }
    throw "No passed Real workspace evidence matches source image $ExpectedImage and digest $ExpectedDigest. Pass -SourceEvidenceDirectory explicitly when using a different evidence location."
}

function Ensure-LocalRegistry {
    param([string]$RegistryHost, [string]$ContainerName, [int]$PublishedPort)
    if ($RegistryHost -notmatch '^(localhost|127\.0\.0\.1):[0-9]+$') { return $false }
    $exists = $false
    docker container inspect $ContainerName *> $null
    if ($LASTEXITCODE -eq 0) {
        $exists = $true
        $running = (& docker inspect --format '{{.State.Running}}' $ContainerName 2>$null).Trim()
        if ($running -ne 'true') {
            Invoke-Docker -Arguments @('start', $ContainerName) -FailureMessage "Unable to start local registry container $ContainerName."
        }
    } else {
        Invoke-Docker -Arguments @('run', '--detach', '--restart', 'unless-stopped', '--name', $ContainerName, '--publish', "${PublishedPort}:5000", 'registry:2') -FailureMessage 'Unable to start the local private Registry container.'
        $script:registryContainerCreated = $true
    }
    try {
        $probe = Invoke-WebRequest -Uri "http://$RegistryHost/v2/" -TimeoutSec 10 -NoProxy
        if ($probe.StatusCode -ne 200) { throw "Registry probe returned HTTP $($probe.StatusCode)." }
    } catch {
        throw "Local Registry $RegistryHost is not ready: $($_.Exception.Message)"
    }
    return $true
}

function Get-RemoteTagDigest {
    param([string]$Reference, [string]$OutputPath)
    $output = & docker pull $Reference 2>&1
    $output | Out-File -LiteralPath $OutputPath -Encoding utf8
    if ($LASTEXITCODE -ne 0) { return '' }
    return Get-DigestFromOutput -Lines @($output)
}

Assert-ReferencePart -Value $Registry -Name 'Registry'
Assert-ReferencePart -Value $Repository -Name 'Repository'
Assert-ReferencePart -Value $PromotionTag -Name 'PromotionTag'
Assert-ReferencePart -Value $RollbackTag -Name 'RollbackTag'
if ($JourneyPort -lt 1 -or $JourneyPort -gt 65535) { throw 'JourneyPort must be a valid TCP port.' }
if ($RegistryPort -lt 1 -or $RegistryPort -gt 65535) { throw 'RegistryPort must be a valid TCP port.' }
foreach ($port in @($JourneyFluentdPort, $JourneyMinioApiPort, $JourneyMinioConsolePort, $JourneyPrometheusPort)) {
    if ($port -lt 1 -or $port -gt 65535) { throw 'Journey service ports must be valid TCP ports.' }
}
if ($SourceImage -match ':latest$' -or $SourceImage -match '@sha256:') { throw 'SourceImage must be a local immutable image tag; promotion derives its digest from the local image.' }
if ($JourneyProjectName -notmatch '^[a-z0-9][a-z0-9_-]{2,62}$') { throw 'JourneyProjectName must be a narrow Docker Compose project identifier.' }

$stamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMdd-HHmmss')
$evidence = if ($OutputDirectory) { [IO.Path]::GetFullPath($OutputDirectory) } else { Join-Path $root "evidence/image-promotion/$stamp" }
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
$promotionRef = "$Registry/$Repository`:$PromotionTag"
$rollbackRef = "$Registry/$Repository`:$RollbackTag"
$digestRef = ''
$sourceInfo = $null
$sourceDigest = ''
$sourceEvidence = $null

try {
    $sourceJson = Invoke-Docker -Arguments @('image', 'inspect', $SourceImage) -FailureMessage "Source image is not available locally: $SourceImage"
    $sourceInfo = ($sourceJson -join "`n") | ConvertFrom-Json
    $sourceInfo | ConvertTo-Json -Depth 30 | Out-File -LiteralPath (Join-Path $evidence 'source-image-inspect.json') -Encoding utf8
    $sourceDigest = [string]$sourceInfo.Descriptor.digest
    if ($sourceDigest -notmatch '^sha256:[0-9a-f]{64}$') {
        $sourceDigest = [string](($sourceInfo.RepoDigests | Where-Object { $_ -match '@sha256:[0-9a-f]{64}$' } | Select-Object -First 1) -split '@', 2)[1]
    }
    if ($sourceDigest -notmatch '^sha256:[0-9a-f]{64}$') { throw 'Source image does not expose an immutable sha256 digest.' }
    $sourceDigest = $sourceDigest.ToLowerInvariant()
    $sourceDigest | Out-File -LiteralPath (Join-Path $evidence 'source-digest.txt') -Encoding utf8

    $sourceEvidence = Get-SourceEvidence -ExplicitDirectory $SourceEvidenceDirectory -ExpectedImage $SourceImage -ExpectedDigest $sourceDigest
    Copy-Item -LiteralPath (Join-Path $sourceEvidence.directory 'summary.json') -Destination (Join-Path $evidence 'source-workspace-summary.json') -Force

    $isLocalRegistry = Ensure-LocalRegistry -RegistryHost $Registry -ContainerName $RegistryContainerName -PublishedPort $RegistryPort
    if (-not $isLocalRegistry) {
        Write-Warning "Using external Registry $Registry. Docker credentials must already be available to this Docker client."
        $probeOutput = @(& docker manifest inspect $promotionRef 2>&1)
        $probeOutput | Out-File -LiteralPath (Join-Path $evidence 'registry-probe.log') -Encoding utf8
    }

    $remotePromotionDigest = Get-RemoteTagDigest -Reference $promotionRef -OutputPath (Join-Path $evidence 'promotion-existing-pull.log')
    if ($remotePromotionDigest -and $remotePromotionDigest -ne $sourceDigest) {
        throw "Promotion tag $promotionRef already points to $remotePromotionDigest; refusing to overwrite a different digest."
    }
    Invoke-Docker -Arguments @('tag', $SourceImage, $promotionRef) -FailureMessage "Unable to tag source image as $promotionRef." | Out-Null
    if (-not $remotePromotionDigest) {
        $promotionPush = Invoke-Docker -Arguments @('push', $promotionRef) -FailureMessage "Unable to push promoted image $promotionRef." -OutputPath (Join-Path $evidence 'promotion-push.log')
        $promotionDigest = Get-DigestFromOutput -Lines $promotionPush
    } else {
        $promotionDigest = $remotePromotionDigest
        "Existing remote tag already matches source digest $promotionDigest." | Out-File -LiteralPath (Join-Path $evidence 'promotion-push.log') -Encoding utf8
    }
    if ($promotionDigest -ne $sourceDigest) { throw "Registry promotion digest mismatch: source=$sourceDigest registry=$promotionDigest" }
    $digestRef = "$Registry/$Repository@$promotionDigest"

    $remoteRollbackDigest = Get-RemoteTagDigest -Reference $rollbackRef -OutputPath (Join-Path $evidence 'rollback-existing-pull.log')
    if ($remoteRollbackDigest) {
        $rollbackDigest = $remoteRollbackDigest
        "Existing rollback reference preserved at digest $rollbackDigest." | Out-File -LiteralPath (Join-Path $evidence 'rollback-push.log') -Encoding utf8
    } else {
        Invoke-Docker -Arguments @('tag', $SourceImage, $rollbackRef) -FailureMessage "Unable to tag rollback image as $rollbackRef." | Out-Null
        $rollbackPush = Invoke-Docker -Arguments @('push', $rollbackRef) -FailureMessage "Unable to push rollback image $rollbackRef." -OutputPath (Join-Path $evidence 'rollback-push.log')
        $rollbackDigest = Get-DigestFromOutput -Lines $rollbackPush
    }
    if ($rollbackDigest -notmatch '^sha256:[0-9a-f]{64}$') { throw 'Rollback tag did not produce an immutable digest.' }

    Invoke-Docker -Arguments @('image', 'rm', $promotionRef) -FailureMessage "Unable to remove the local mutable promotion tag $promotionRef." | Out-Null
    $pullOutput = Invoke-Docker -Arguments @('pull', $digestRef) -FailureMessage "Unable to pull promoted image by digest $digestRef." -OutputPath (Join-Path $evidence 'promotion-digest-pull.log')
    $pulledDigest = Get-DigestFromOutput -Lines $pullOutput
    if ($pulledDigest -and $pulledDigest -ne $promotionDigest) { throw "Digest pull returned $pulledDigest instead of $promotionDigest." }
    $promotedInspectJson = Invoke-Docker -Arguments @('image', 'inspect', $digestRef) -FailureMessage 'Promoted image digest inspect failed.'
    $promotedInfo = ($promotedInspectJson -join "`n") | ConvertFrom-Json
    $promotedInfo | ConvertTo-Json -Depth 30 | Out-File -LiteralPath (Join-Path $evidence 'promoted-image-inspect.json') -Encoding utf8
    $repoDigestMatches = @($promotedInfo.RepoDigests | Where-Object { $_ -match "@${promotionDigest.Replace(':', '\:')}$" }).Count -gt 0
    if (-not $repoDigestMatches -and [string]$promotedInfo.Descriptor.digest -ne $promotionDigest) { throw 'Pulled image inspection does not prove the promoted manifest digest.' }

    if (-not $SkipJourney) {
        $journeyEvidence = Join-Path $evidence 'workspace-reverification'
        New-Item -ItemType Directory -Force -Path $journeyEvidence | Out-Null
        $verifyScript = Join-Path (Split-Path -Parent $PSScriptRoot) 'verify/real-workspace-integration.ps1'
        try {
            if ($JourneyAppNetworkSubnet -notmatch '^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$') {
                throw 'JourneyAppNetworkSubnet must be an IPv4 CIDR.'
            }
            $journeyParams = @{
                ProjectName = $JourneyProjectName
                EntryPort = $JourneyPort
                RuntimeImage = $digestRef
                OutputDirectory = $journeyEvidence
                SkipRuntimeBuild = $true
            }
            if (-not $JourneyUseExistingEnvironment) {
                $env:APP_NETWORK_SUBNET = $JourneyAppNetworkSubnet
                $env:FLUENTD_HOST_PORT = [string]$JourneyFluentdPort
                $env:MINIO_API_PORT = [string]$JourneyMinioApiPort
                $env:MINIO_CONSOLE_PORT = [string]$JourneyMinioConsolePort
                $env:PROMETHEUS_PORT = [string]$JourneyPrometheusPort
                $journeyParams.SeedPrerequisites = $true
            }
            & $verifyScript @journeyParams 2>&1 | Tee-Object -FilePath (Join-Path $evidence 'journey-reverification.log')
            if ($LASTEXITCODE -ne 0) { throw 'Real workspace digest re-verification exited with a non-zero code.' }
            $journeySummaryPath = Join-Path $journeyEvidence 'summary.json'
            if (-not (Test-Path -LiteralPath $journeySummaryPath)) { throw 'Real workspace digest re-verification did not produce summary.json.' }
            $journeySummary = Get-Content -Raw -Encoding UTF8 $journeySummaryPath | ConvertFrom-Json
            if ($journeySummary.result -ne 'passed') { throw 'Real workspace digest re-verification did not pass.' }
            $journeyResult = 'passed'
        } catch {
            $journeyResult = 'failed'
            throw
        }
    } else {
        $journeyResult = 'skipped'
    }

    $gitRevision = (& git -C $root rev-parse HEAD 2>$null).Trim()
    $releaseManifest = [ordered]@{
        phase = 'workspace-image-promotion'
        result = 'passed'
        created_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        git_revision = $gitRevision
        source = [ordered]@{ image = $SourceImage; digest = $sourceDigest; workspace_evidence = $sourceEvidence.directory }
        promoted = [ordered]@{ tag_reference = $promotionRef; digest_reference = $digestRef; manifest_digest = $promotionDigest; platform = 'linux/amd64' }
        rollback = [ordered]@{ tag_reference = $rollbackRef; digest_reference = "$Registry/$Repository@$rollbackDigest"; manifest_digest = $rollbackDigest }
        local_reverification = [ordered]@{ result = $journeyResult; project = $JourneyProjectName; entry_port = $JourneyPort; existing_environment = [bool]$JourneyUseExistingEnvironment; rebuild_workspace_image = $false }
        policy = [ordered]@{ server_must_pull_digest = $true; server_must_not_build = $true; tags_are_display_only = $true }
    }
    $releaseManifest | ConvertTo-Json -Depth 12 | Out-File -LiteralPath (Join-Path $evidence 'release-manifest.json') -Encoding utf8

    $allowedImages = [ordered]@{
        schema = 'workspace-image-promotion/allowed-images/v1'
        generated_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        images = @([ordered]@{
            name = 'algorithm-workspace'
            repository = "$Registry/$Repository"
            tag = $PromotionTag
            digest = $promotionDigest
            reference = $digestRef
            platform = 'linux/amd64'
            source_workspace_digest = $sourceDigest
        })
    }
    $allowedImages | ConvertTo-Json -Depth 10 | Out-File -LiteralPath (Join-Path $evidence 'allowed-images.json') -Encoding utf8

    $runtimeAdapterConfigs = (@{ 'runtime/local-docker' = @{ runtime_network = 'experimental-platform-promotion-runtime'; image = $digestRef; pids_limit = 128 } } | ConvertTo-Json -Compress)
    $deploymentConfig = [ordered]@{
        schema = 'workspace-image-promotion/deployment-config/v1'
        generated_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        required = [ordered]@{
            LOCAL_RUNTIME_IMAGE = $digestRef
            LOCAL_RUNTIME_MODE = 'REAL'
            RUNTIME_WORKSPACE_PORT = '8080'
            RUNTIME_HEALTHCHECK_PATH = '/healthz'
            SWARM_RUNTIME_NETWORK = 'experimental-platform-swarm-runtime'
        }
        local_reverification = [ordered]@{
            LOCAL_RUNTIME_NETWORK = 'experimental-platform-promotion-runtime'
            RUNTIME_ADAPTER_CONFIGS = $runtimeAdapterConfigs
        }
        prohibited = @('LOCAL_RUNTIME_IMAGE=:latest', 'server-side docker build', 'mutable tag as deployment fact')
    }
    $deploymentConfig | ConvertTo-Json -Depth 12 | Out-File -LiteralPath (Join-Path $evidence 'deployment-config.json') -Encoding utf8

    $rollbackManifest = [ordered]@{
        schema = 'workspace-image-promotion/rollback/v1'
        generated_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        current_release = $digestRef
        rollback_reference = "$Registry/$Repository@$rollbackDigest"
        rollback_digest = $rollbackDigest
        action = 'Create new runtime instances with rollback_reference; do not mutate historical task image facts.'
        verification = 'The rollback digest is immutable and was pushed or preserved before promotion was accepted.'
    }
    $rollbackManifest | ConvertTo-Json -Depth 10 | Out-File -LiteralPath (Join-Path $evidence 'rollback-manifest.json') -Encoding utf8

    $result = 'passed'
} finally {
    $summary = [ordered]@{
        phase = 'workspace-image-promotion'
        result = $result
        collected_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        source_image = $SourceImage
        source_digest = $sourceDigest
        promotion_reference = $promotionRef
        promotion_digest = $promotionDigest
        rollback_reference = $rollbackRef
        rollback_digest = $rollbackDigest
        digest_reference = $digestRef
        local_registry = ($Registry -match '^(localhost|127\.0\.0\.1):[0-9]+$')
        journey = $journeyResult
        evidence = $evidence
        limitation = 'This verifies local Registry promotion and digest re-verification; real Swarm acceptance remains pending.'
    }
    $summary | ConvertTo-Json -Depth 10 | Out-File -LiteralPath (Join-Path $evidence 'summary.json') -Encoding utf8
    if ($RemoveLocalRegistry -and $registryContainerCreated) {
        & docker rm --force $RegistryContainerName *> $null
    }
    if ($null -eq $previousAppNetworkSubnet) { Remove-Item Env:APP_NETWORK_SUBNET -ErrorAction SilentlyContinue } else { Set-Item Env:APP_NETWORK_SUBNET $previousAppNetworkSubnet }
}

if ($result -ne 'passed') { throw "Real workspace failed. Evidence: $evidence" }
Write-Output "Real workspace Registry promotion passed. Digest: $digestRef. Evidence: $evidence"
