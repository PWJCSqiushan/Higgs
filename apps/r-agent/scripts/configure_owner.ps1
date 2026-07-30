[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[1-9][0-9]{4,11}$')]
    [string]$OwnerQq
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'config_file.ps1')
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
    Install-LocalConfigFile -TempPath $tempPath -DestinationPath $envPath
}
finally {
    if (Test-Path -LiteralPath $tempPath) {
        $trashDir = Join-Path (Split-Path -Parent $tempPath) '.trash'
        New-Item -ItemType Directory -Path $trashDir -Force | Out-Null
        $trashName = '{0}-{1}-{2}' -f (Get-Date -Format 'yyyyMMddTHHmmss'), ([guid]::NewGuid().ToString('N').Substring(0, 8)), (Split-Path -Leaf $tempPath)
        Move-Item -LiteralPath $tempPath -Destination (Join-Path $trashDir $trashName)
    }
}

Write-Host 'Owner identity saved locally and not printed. Restart Higgs to apply it.'
