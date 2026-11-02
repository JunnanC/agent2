<#
.SYNOPSIS
后端完整单测、Django/迁移、OpenAPI、Ruff、mypy 和基础设施契约检查。
.DESCRIPTION
从仓库根目录调用。
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$backend = Join-Path $root 'backend'
$djangoProject = $backend
$backendPython = Join-Path $backend '.venv\Scripts\python.exe'
$python = $null
$pythonArgs = @()

function Test-Python314Candidate {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$Arguments = @()
    )

    $version = & $Executable @Arguments -c 'import sys; import django, mypy, pytest, ruff; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>$null
    return $LASTEXITCODE -eq 0 -and (($version | Select-Object -Last 1) -eq '3.14')
}

if (Test-Path -LiteralPath $backendPython) {
    if (Test-Python314Candidate -Executable $backendPython -Arguments @()) {
        $python = $backendPython
    }
}
if ($null -eq $python -and (Test-Python314Candidate -Executable 'py' -Arguments @('-3.14'))) {
    $python = 'py'
    $pythonArgs = @('-3.14')
}
if ($null -eq $python) {
    throw 'Backend local gate requires Python 3.14 with Django, pytest, Ruff, and mypy available.'
}

$previousLocation = (Get-Location).Path
$previousEnvironment = @{}
Get-ChildItem Env: | ForEach-Object { $previousEnvironment[$_.Name] = $_.Value }
$openApiFile = Join-Path ([IO.Path]::GetTempPath()) "experimental-platform-openapi-backend-$PID.json"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed."
    }
}

try {
    $env:DJANGO_SETTINGS_MODULE = 'education_experiment_platform.settings.test'

    Set-Location -LiteralPath $djangoProject
    Invoke-Checked -Description 'Django system check' -Command {
        & $python @pythonArgs manage.py check
    }
    Invoke-Checked -Description 'Migration drift check' -Command {
        & $python @pythonArgs manage.py makemigrations --check --dry-run
    }
    Set-Location -LiteralPath $backend
    Invoke-Checked -Description 'Backend pytest' -Command {
        & $python @pythonArgs -m pytest
    }
    Set-Location -LiteralPath $djangoProject
    Invoke-Checked -Description 'OpenAPI schema validation' -Command {
        & $python @pythonArgs manage.py spectacular --format openapi-json --validate --file $openApiFile
    }
    Set-Location -LiteralPath $backend
    Invoke-Checked -Description 'Backend Ruff' -Command {
        & $python @pythonArgs -m ruff check apps education_experiment_platform --exclude 'migrations' --force-exclude
    }
    Invoke-Checked -Description 'Backend mypy' -Command {
        & $python @pythonArgs -m mypy apps education_experiment_platform
    }
    Set-Location -LiteralPath $root
    Invoke-Checked -Description 'Compose configuration validation' -Command {
        & docker compose -f (Join-Path $root 'docker-compose.dev.yml') config --quiet
    }

    Write-Output 'Backend-only local gate passed.'
    Write-Output 'This gate checks the backend and infrastructure contracts; run frontend and runtime gates separately.'
} finally {
    Remove-Item -LiteralPath $openApiFile -ErrorAction SilentlyContinue
    Set-Location -LiteralPath $previousLocation
    $currentEnvironment = @(Get-ChildItem Env:)
    foreach ($entry in $currentEnvironment) {
        if (-not $previousEnvironment.ContainsKey($entry.Name)) {
            Remove-Item -LiteralPath "Env:$($entry.Name)" -ErrorAction SilentlyContinue
        }
    }
    foreach ($entry in $previousEnvironment.GetEnumerator()) {
        Set-Item -LiteralPath "Env:$($entry.Key)" -Value $entry.Value
    }
}
