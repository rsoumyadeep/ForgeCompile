# Run every check that CI runs: lint, format check, type check, tests.
# Usage: scripts\check.ps1 [extra pytest args]
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Invoke-Step([string]$Name, [scriptblock]$Command) {
    Write-Host "== $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Invoke-Step "ruff check"  { uv run ruff check . }
Invoke-Step "ruff format" { uv run ruff format --check . }
Invoke-Step "mypy"        { uv run mypy }
Invoke-Step "pytest"      { uv run pytest @args }
