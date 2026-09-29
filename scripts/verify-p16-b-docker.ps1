param(
    [string]$Image = 'edu-platform-algorithm-workspace:p16-b',
    [string]$OutputDirectory = '',
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if ($Image -notmatch '^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}$') {
    throw 'Image must be a narrow OCI image reference.'
}

$stamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMdd-HHmmss')
$evidence = if ($OutputDirectory) {
    [IO.Path]::GetFullPath($OutputDirectory)
} else {
    Join-Path $root "evidence/p16/$stamp-p16-b"
}
New-Item -ItemType Directory -Force -Path $evidence | Out-Null

$metadataPath = Join-Path $evidence 'build-metadata.json'
$inspectPath = Join-Path $evidence 'image-inspect.json'
$sbomPath = Join-Path $evidence 'sbom.spdx.json'
$smokePath = Join-Path $evidence 'smoke.json'
$summaryPath = Join-Path $evidence 'summary.json'
$secretPath = Join-Path ([IO.Path]::GetTempPath()) "p16-b-upstream-$PID"
$container = "p16-b-verify-$PID"

function Invoke-Docker {
    param([string[]]$Arguments, [string]$FailureMessage)
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
}

try {
    if (-not $SkipBuild) {
        Invoke-Docker -Arguments @(
            'buildx', 'build',
            '--load',
            '--platform', 'linux/amd64',
            '--provenance=false',
            '--metadata-file', $metadataPath,
            '--tag', $Image,
            (Join-Path $root 'runtime/algorithm-workspace')
        ) -FailureMessage 'P16-B workspace image build failed.'
    } elseif (-not (docker image inspect $Image 2>$null)) {
        throw "P16-B image '$Image' does not exist and -SkipBuild was supplied."
    }

    $judgeOutput = (& docker run --rm --read-only --network none --tmpfs '/tmp:rw,noexec,nosuid,size=32m' $Image python -c 'import platform; print(platform.python_version())').Trim()
    if ($LASTEXITCODE -ne 0 -or $judgeOutput -ne '3.14.0') {
        throw "P16-B judge command override failed: $judgeOutput"
    }

    $randomBytes = New-Object byte[] 48
    [Security.Cryptography.RandomNumberGenerator]::Fill($randomBytes)
    [IO.File]::WriteAllText($secretPath, [Convert]::ToBase64String($randomBytes))

    $testsPath = [IO.Path]::GetFullPath((Join-Path $root 'runtime/algorithm-workspace/tests'))
    Invoke-Docker -Arguments @(
        'run', '--detach',
        '--name', $container,
        '--read-only',
        '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges:true',
        '--pids-limit', '128',
        '--memory', '768m',
        '--network', 'none',
        '--tmpfs', '/tmp:rw,noexec,nosuid,size=128m,uid=10001,gid=10001',
        '--tmpfs', '/workspace:rw,noexec,nosuid,size=64m,uid=10001,gid=10001',
        '--mount', "type=bind,source=$secretPath,target=/run/secrets/workspace_upstream_token,readonly",
        '--mount', "type=bind,source=$testsPath,target=/opt/p16-tests,readonly",
        $Image
    ) -FailureMessage 'P16-B hardened workspace container failed to start.'

    $health = 'starting'
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $health = (& docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' $container).Trim()
        if ($health -eq 'healthy') { break }
        if ($health -eq 'unhealthy') {
            & docker logs $container
            throw 'P16-B workspace container became unhealthy.'
        }
        Start-Sleep -Seconds 1
    }
    if ($health -ne 'healthy') {
        & docker logs $container
        throw 'P16-B workspace container did not become healthy in time.'
    }

    $smokeOutput = & docker exec $container python /opt/p16-tests/smoke.py
    if ($LASTEXITCODE -ne 0) {
        & docker logs $container
        throw 'P16-B image contract smoke failed.'
    }
    $smokeOutput | Out-File -LiteralPath $smokePath -Encoding utf8

    $codeServerVersion = (& docker exec $container /opt/code-server/bin/code-server --version | Select-Object -First 1).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $codeServerVersion.StartsWith('4.104.2 ')) {
        throw "Unexpected code-server version: $codeServerVersion"
    }

    $publishedPorts = (& docker inspect --format '{{json .NetworkSettings.Ports}}' $container).Trim()
    if ($publishedPorts -match 'HostPort') {
        throw 'P16-B workspace container unexpectedly publishes a host port.'
    }

    & docker image inspect $Image | Out-File -LiteralPath $inspectPath -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw 'P16-B image inspect failed.' }

    Invoke-Docker -Arguments @('sbom', $Image, '--format', 'spdx-json', '--output', $sbomPath) -FailureMessage 'P16-B SBOM generation failed.'

    $imageInspect = (Get-Content -LiteralPath $inspectPath -Raw | ConvertFrom-Json)[0]
    $buildMetadata = if (Test-Path -LiteralPath $metadataPath) {
        Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
    } else {
        $null
    }
    if ($imageInspect.Config.User -ne '10001:10001') {
        throw "Unexpected image user: $($imageInspect.Config.User)"
    }
    if ($imageInspect.Config.Entrypoint[0] -ne '/usr/local/bin/workspace-entrypoint') {
        throw 'Unexpected workspace image entrypoint.'
    }
    if (-not $imageInspect.Config.ExposedPorts.'8080/tcp' -or $imageInspect.Config.ExposedPorts.PSObject.Properties.Count -ne 1) {
        throw 'P16-B image must expose only 8080/tcp.'
    }

    $summary = [ordered]@{
        phase = 'P16-B'
        result = 'passed'
        collected_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        image = $Image
        image_id = $imageInspect.Id
        image_config_digest = if ($null -ne $buildMetadata) { $buildMetadata.'containerimage.config.digest' } else { $null }
        local_manifest_digest = if ($null -ne $buildMetadata) {
            $buildMetadata.'containerimage.digest'
        } elseif ($imageInspect.RepoDigests.Count -gt 0) {
            ($imageInspect.RepoDigests[0] -split '@', 2)[1]
        } else {
            $null
        }
        repo_digests = @($imageInspect.RepoDigests)
        size_bytes = [long]$imageInspect.Size
        user = $imageInspect.Config.User
        entrypoint = @($imageInspect.Config.Entrypoint)
        exposed_ports = @($imageInspect.Config.ExposedPorts.PSObject.Properties.Name)
        published_ports = $publishedPorts
        code_server = $codeServerVersion
        python = '3.14.0'
        base_image = 'm.daocloud.io/docker.io/library/python:3.14.0-slim-bookworm@sha256:9bbb8720ae0a24a6ca8dd678bfdf57818fe70caf54c52a53ec01d8db43405056'
        code_server_archive_sha256 = 'bc650b57fd8d0bcee952c97308dd43ae37ad8dc11b83a713d8eca8ce823fefd9'
        health = $health
        judge_command_override = 'passed'
        security = [ordered]@{
            cap_drop = 'ALL'
            network = 'none'
            no_new_privileges = $true
            read_only_rootfs = $true
            host_ports = 0
        }
        sbom = 'sbom.spdx.json'
        limitation = 'This is local image-level evidence. Registry promotion and real Swarm acceptance remain pending.'
    }
    $summary | ConvertTo-Json -Depth 6 | Out-File -LiteralPath $summaryPath -Encoding utf8
    Write-Output "P16-B Docker image gates passed. Evidence: $evidence"
} finally {
    & docker rm --force $container 2>$null | Out-Null
    Remove-Item -LiteralPath $secretPath -Force -ErrorAction SilentlyContinue
}
