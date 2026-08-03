[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$matches = @(
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -in @('uv.exe', 'python.exe', 'pythonw.exe') -and
            $_.CommandLine -and
            $_.CommandLine.Contains('r_agent.phase2_cli')
        }
)

if ($matches.Count -eq 0) {
    Write-Host 'Higgs Phase 2 is not running.'
    exit 0
}
foreach ($process in $matches) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}
Write-Host "Stopped $($matches.Count) Higgs process(es)."
