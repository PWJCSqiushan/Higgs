function Install-LocalConfigFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$TempPath,

        [Parameter(Mandatory)]
        [string]$DestinationPath
    )

    $trashDir = Join-Path (Split-Path -Parent $DestinationPath) '.trash'
    New-Item -ItemType Directory -Path $trashDir -Force | Out-Null
    $trashName = '{0}-{1}-{2}' -f (
        Get-Date -Format 'yyyyMMddTHHmmss'
    ), ([guid]::NewGuid().ToString('N').Substring(0, 8)), (
        Split-Path -Leaf $DestinationPath
    )
    $previousPath = Join-Path $trashDir $trashName
    Move-Item -LiteralPath $DestinationPath -Destination $previousPath
    try {
        Move-Item -LiteralPath $TempPath -Destination $DestinationPath
    }
    catch {
        if (
            -not (Test-Path -LiteralPath $DestinationPath) -and
            (Test-Path -LiteralPath $previousPath)
        ) {
            Move-Item -LiteralPath $previousPath -Destination $DestinationPath
        }
        throw
    }
}
