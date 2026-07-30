[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'config_file.ps1')
$appRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $appRoot '.env'

if (-not (Test-Path -LiteralPath $envPath)) {
    $example = Join-Path $appRoot '.env.example'
    if (-not (Test-Path -LiteralPath $example)) {
        throw 'Missing .env.example.'
    }
    Copy-Item -LiteralPath $example -Destination $envPath
}

$secureKey = Read-Host 'Paste Zhipu API Key (input is hidden)' -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
if ([string]::IsNullOrWhiteSpace($apiKey) -or $apiKey.Contains("`r") -or $apiKey.Contains("`n")) {
    throw 'The API key is empty or invalid.'
}

$updates = [ordered]@{
    'R_AGENT_REPLY_MODE' = 'draft'
    'R_AGENT_SHADOW_MODE' = 'true'
    'R_AGENT_PHASE2_ENABLE_LIVE' = 'false'
    'R_AGENT_REPLY_ALLOWED_GROUPS' = ''
    'R_AGENT_MODEL_PROVIDER' = 'zhipu'
    'R_AGENT_MODEL_BASE_URL' = 'https://open.bigmodel.cn/api/paas/v4'
    'R_AGENT_MODEL_NAME' = 'glm-5.2'
    'R_AGENT_MODEL_THINKING' = 'disabled'
    'R_AGENT_MODEL_API_KEY' = $apiKey
    'R_AGENT_PERSONA_FILE' = './persona.local.md'
}

$lines = [Collections.Generic.List[string]]::new()
foreach ($line in [IO.File]::ReadAllLines($envPath, [Text.Encoding]::UTF8)) {
    $lines.Add($line)
}
foreach ($entry in $updates.GetEnumerator()) {
    $prefix = "$($entry.Key)="
    $found = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index].StartsWith($prefix, [StringComparison]::Ordinal)) {
            $lines[$index] = "$prefix$($entry.Value)"
            $found = $true
            break
        }
    }
    if (-not $found) {
        $lines.Add("$prefix$($entry.Value)")
    }
}

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
    $apiKey = $null
}

Write-Host 'GLM-5.2 draft configuration saved locally. The API key was not printed.'
