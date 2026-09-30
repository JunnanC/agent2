param(
    [string]$StackName = 'edu-platform',
    [string]$ComposeFile = 'infrastructure/swarm/stack.yml',
    [string]$EnvironmentFile = '',
    [Parameter(Mandatory = $true)][string]$Registry,
    [Parameter(Mandatory = $true)][string]$ImageTag,
    [switch]$WithRegistryAuth
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    if ($StackName -ne 'edu-platform') { throw 'Only the project stack name edu-platform is allowed.' }
    if (-not (Test-Path -LiteralPath $ComposeFile)) { throw "Stack file not found: $ComposeFile" }
    if ((docker info --format '{{.Swarm.LocalNodeState}}' 2>$null) -ne 'active') {
        throw 'Swarm is inactive. Run p14-bootstrap-swarm.ps1 first.'
    }
    $env:REGISTRY = $Registry
    $env:IMAGE_TAG = $ImageTag
    if ($EnvironmentFile) {
        if (-not (Test-Path -LiteralPath $EnvironmentFile)) { throw "Environment file not found: $EnvironmentFile" }
        foreach ($line in Get-Content -LiteralPath $EnvironmentFile) {
            if ($line -match '^\s*(?<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?<value>.*)\s*$') {
                Set-Item -Path ("Env:" + $Matches.name) -Value $Matches.value.Trim().Trim('"').Trim("'")
            }
        }
    }

    $requiredEnvironment = @(
        'DJANGO_ALLOWED_HOSTS', 'DJANGO_TRUSTED_ORIGINS', 'WORKSPACE_ALLOWED_ORIGINS',
        'TRUSTED_PROXY_CIDRS', 'APP_NETWORK_SUBNET', 'USER_HOST', 'TEACHER_HOST',
        'ADMIN_HOST', 'API_HOST', 'KONG_IMAGE',
        'FLUENT_BIT_IMAGE', 'OTEL_COLLECTOR_IMAGE', 'MYSQL_HOST', 'REDIS_URL',
        'CELERY_BROKER_URL', 'CELERY_RESULT_BACKEND', 'MINIO_ENDPOINT', 'CLAMAV_HOST',
        'SWARM_DOCKER_HOST'
    )
    foreach ($name in $requiredEnvironment) {
        $value = (Get-Item -Path ("Env:" + $name) -ErrorAction SilentlyContinue).Value
        if ([string]::IsNullOrWhiteSpace($value)) {
            throw "Missing required deployment environment variable: $name"
        }
    }

    $requiredConfigs = @('kong_config_v1', 'fluent_bit_config_v1', 'fluent_bit_redact_v1', 'otel_config_v1')
    $requiredSecrets = @('django_secret_key', 'identity_hmac_key', 'course_invitation_hmac_key', 'mysql_app_password', 'mongodb_uri', 'minio_app_access_key', 'minio_app_secret_key', 'workspace_internal_key', 'swarm_docker_ca', 'swarm_docker_cert', 'swarm_docker_key', 'tls_certificate', 'tls_private_key')
    foreach ($config in $requiredConfigs) {
        docker config inspect $config *> $null
        if ($LASTEXITCODE -ne 0) { throw "Missing external Swarm config: $config" }
    }
    foreach ($secret in $requiredSecrets) {
        docker secret inspect $secret *> $null
        if ($LASTEXITCODE -ne 0) { throw "Missing external Swarm secret: $secret" }
    }

    & docker stack config -c $ComposeFile *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Rendered Swarm stack configuration is invalid.' }
    $deployArgs = @('stack', 'deploy')
    if ($WithRegistryAuth) { $deployArgs += '--with-registry-auth' }
    $deployArgs += @('-c', $ComposeFile, $StackName)
    & docker @deployArgs
    if ($LASTEXITCODE -ne 0) { throw 'Swarm stack deployment failed.' }
    Write-Output "P14 stack deployed: $StackName image=$Registry`:$ImageTag"
} finally { Pop-Location }
