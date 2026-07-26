[CmdletBinding()]
param(
    [string[]]$PrivateQq = @(),
    [string[]]$GroupQq = @(),
    [string[]]$NaturalTriggerGroupQq = @(),
    [string[]]$NaturalTriggerTerm = @('higgs'),
    [switch]$AllowGroupWithoutMention
)

$ErrorActionPreference = 'Stop'
$appRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $appRoot '.env'

if (-not (Test-Path -LiteralPath $envPath)) {
    $example = Join-Path $appRoot '.env.example'
    if (-not (Test-Path -LiteralPath $example)) {
        throw 'Missing .env.example.'
    }
    Copy-Item -LiteralPath $example -Destination $envPath
}

function Normalize-QqIds {
    param(
        [string[]]$Values,
        [string]$Label
    )

    $normalized = [Collections.Generic.SortedSet[string]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($value in $Values) {
        foreach ($part in ($value -split ',')) {
            $candidate = $part.Trim()
            if (-not $candidate) {
                continue
            }
            if ($candidate -notmatch '^[1-9][0-9]{4,11}$') {
                throw "$Label contains an invalid ID. Use exact 5-12 digit QQ numbers only."
            }
            [void]$normalized.Add($candidate)
        }
    }
    return [string]::Join(',', $normalized)
}

$privateValue = Normalize-QqIds -Values $PrivateQq -Label 'PrivateQq'
$groupValue = Normalize-QqIds -Values $GroupQq -Label 'GroupQq'
$naturalGroupValue = Normalize-QqIds -Values $NaturalTriggerGroupQq -Label 'NaturalTriggerGroupQq'
$allowedGroupIds = @($groupValue -split ',' | Where-Object { $_ })
foreach ($naturalGroupId in ($naturalGroupValue -split ',' | Where-Object { $_ })) {
    if ($allowedGroupIds -notcontains $naturalGroupId) {
        throw 'Every NaturalTriggerGroupQq must also appear in GroupQq.'
    }
}
$mentionValue = if ($AllowGroupWithoutMention) { 'false' } else { 'true' }

$triggerTerms = [Collections.Generic.SortedSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
foreach ($value in $NaturalTriggerTerm) {
    foreach ($part in ($value -split ',')) {
        $candidate = $part.Trim()
        if (-not $candidate) { continue }
        if ($candidate.Length -gt 32 -or $candidate.Contains("`n") -or $candidate.Contains("`r")) {
            throw 'NaturalTriggerTerm entries must be 1-32 characters without line breaks.'
        }
        [void]$triggerTerms.Add($candidate)
    }
}
if ($triggerTerms.Count -eq 0 -or $triggerTerms.Count -gt 16) {
    throw 'NaturalTriggerTerm requires 1-16 explicit terms.'
}
$triggerTermValue = [string]::Join(',', $triggerTerms)

$updates = [ordered]@{
    'R_AGENT_ALLOWED_PRIVATE_QQS' = $privateValue
    'R_AGENT_REPLY_ALLOWED_PRIVATE_QQS' = $privateValue
    'R_AGENT_ALLOWED_GROUPS' = $groupValue
    'R_AGENT_REPLY_ALLOWED_GROUPS' = $groupValue
    'R_AGENT_REPLY_GROUP_REQUIRE_MENTION' = $mentionValue
    'R_AGENT_REPLY_NATURAL_TRIGGER_GROUPS' = $naturalGroupValue
    'R_AGENT_REPLY_NATURAL_TRIGGER_TERMS' = $triggerTermValue
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
    Move-Item -LiteralPath $tempPath -Destination $envPath -Force
}
finally {
    if (Test-Path -LiteralPath $tempPath) {
        Remove-Item -LiteralPath $tempPath -Force
    }
}

Write-Host "QQ access saved locally: private=$($privateValue.Length -gt 0), groups=$($groupValue.Length -gt 0), natural groups=$($naturalGroupValue.Length -gt 0), trigger terms=$triggerTermValue, default group mention required=$(-not $AllowGroupWithoutMention)."
