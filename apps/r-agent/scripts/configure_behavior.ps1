[CmdletBinding()]
param(
    [string[]]$NaturalTriggerTerm = @('higgs'),
    [ValidateRange(1, 10)]
    [int]$ConversationMaxPerMinute = 6,
    [ValidateRange(1, 60)]
    [int]$GlobalMaxPerMinute = 20,
    [ValidateRange(0.5, 10.0)]
    [double]$DebounceSeconds = 2.5
)

$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $appRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) {
    throw 'Missing .env. Configure the project before changing behavior.'
}

$terms = [Collections.Generic.SortedSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
foreach ($value in $NaturalTriggerTerm) {
    foreach ($part in ($value -split ',')) {
        $candidate = $part.Trim()
        if (-not $candidate) { continue }
        if ($candidate.Length -gt 32 -or $candidate.Contains("`n") -or $candidate.Contains("`r")) {
            throw 'Each trigger term must be 1-32 characters without line breaks.'
        }
        [void]$terms.Add($candidate)
    }
}
if ($terms.Count -eq 0 -or $terms.Count -gt 16) {
    throw 'Provide 1-16 explicit trigger terms.'
}

$updates = [ordered]@{
    'R_AGENT_REPLY_NATURAL_TRIGGER_TERMS' = [string]::Join(',', $terms)
    'R_AGENT_REPLY_MAX_PER_MINUTE' = [string]$ConversationMaxPerMinute
    'R_AGENT_REPLY_GLOBAL_MAX_PER_MINUTE' = [string]$GlobalMaxPerMinute
    'R_AGENT_GROUP_DEBOUNCE_SECONDS' = [string]$DebounceSeconds
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
    if (-not $found) { $lines.Add("$prefix$($entry.Value)") }
}

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

Write-Host 'Behavior saved locally. Restart Higgs for the changes to take effect.'
