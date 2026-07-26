[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $appRoot

if (-not (Test-Path -LiteralPath '.env')) {
    throw 'Missing .env. Run the configuration scripts first.'
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv is not installed or not available in PATH.'
}

Write-Host 'Starting Higgs in the foreground. Press Ctrl+C to stop safely.'
& uv run python -m r_agent.phase2_cli listen
exit $LASTEXITCODE
