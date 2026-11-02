<#
.SYNOPSIS
导出后端 OpenAPI 并重新生成前端 API 类型。
.DESCRIPTION
从仓库根目录调用。
#>
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = if (Test-Path "$root\backend\.venv\Scripts\python.exe") { "$root\backend\.venv\Scripts\python.exe" } elseif (Test-Path "$root\.venv\Scripts\python.exe") { "$root\.venv\Scripts\python.exe" } else { 'python' }
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source

Push-Location "$root\backend"
try {
    $env:DJANGO_SETTINGS_MODULE = 'education_experiment_platform.settings.test'
    & $python manage.py spectacular --format openapi-json --file "$root\frontend\openapi.json"
    if ($LASTEXITCODE -ne 0) { throw 'OpenAPI export failed.' }
} finally {
    Pop-Location
}

Push-Location "$root\frontend"
try {
    & $npm run generate:api
    if ($LASTEXITCODE -ne 0) { throw 'Type generation failed.' }
} finally {
    Pop-Location
}
