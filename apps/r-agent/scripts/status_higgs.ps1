[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$matches = @(
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine.Contains('r_agent.phase2_cli')
        } |
        Select-Object ProcessId, Name, CreationDate
)

if ($matches.Count -eq 0) {
    Write-Host 'Higgs Phase 2 is not running.'
    exit 1
}
$matches | Format-Table -AutoSize
