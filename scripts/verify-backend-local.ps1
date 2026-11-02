$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
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
$openApiFile = Join-Path ([IO.Path]::GetTempPath()) "edu-platform-openapi-backend-$PID.json"
$deselectNode = 'education_experiment_platform/tests/test_infrastructure_contract.py::test_frontends_are_independent_build_entries'

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
        & $python @pythonArgs -m pytest "--deselect=$deselectNode"
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
    Write-Output "Remaining full-gate limitation: frontend source/build entries are absent, so this is not a full repository/frontend pass; only the exact node '$deselectNode' was deselected."
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
