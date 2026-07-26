[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[1-9][0-9]{4,11}$')]
    [string]$OwnerQq
)

$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $appRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) {
    throw 'Missing .env. Configure the project first.'
}

$lines = [Collections.Generic.List[string]]::new()
$found = $false
foreach ($line in [IO.File]::ReadAllLines($envPath, [Text.Encoding]::UTF8)) {
    if ($line.StartsWith('R_AGENT_OWNER_QQ=', [StringComparison]::Ordinal)) {
        $lines.Add("R_AGENT_OWNER_QQ=$OwnerQq")
        $found = $true
    }
    else {
        $lines.Add($line)
    }
}
if (-not $found) { $lines.Add("R_AGENT_OWNER_QQ=$OwnerQq") }

$tempPath = "$envPath.tmp"
try {
    [IO.File]::WriteAllLines($tempPath, $lines, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tempPath -Destination $envPath -Force
}
finally {
    if (Test-Path -LiteralPath $tempPath) {
        Remove-Item -LiteralPath $tempPath -Force
    }
}

Write-Host 'Owner identity saved locally and not printed. Restart Higgs to apply it.'
