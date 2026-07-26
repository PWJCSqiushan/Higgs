param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9]{5,12}$')]
    [string]$BotQq,

    [string]$NapCatRoot = '',

    [string]$EnvFile = ''
)

$ErrorActionPreference = 'Stop'

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
if ([string]::IsNullOrWhiteSpace($NapCatRoot)) {
    $NapCatRoot = Join-Path $projectRoot 'runtime\napcat\shell-v4.18.13'
}
if ([string]::IsNullOrWhiteSpace($EnvFile)) {
    $EnvFile = Join-Path $projectRoot 'apps\r-agent\.env'
}

$resolvedRoot = [IO.Path]::GetFullPath($NapCatRoot)
$expectedBase = [IO.Path]::GetFullPath((Join-Path $projectRoot 'runtime\napcat'))
if (-not $resolvedRoot.StartsWith(
    $expectedBase + [IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw 'NapCatRoot must stay inside the project runtime directory'
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw 'Local .env is missing'
}

$tokenLines = @(
    Get-Content -LiteralPath $EnvFile -Encoding utf8 |
        Where-Object { $_ -like 'R_AGENT_ONEBOT_ACCESS_TOKEN=*' }
)
if ($tokenLines.Count -ne 1) {
    throw 'Expected exactly one OneBot token'
}
$token = $tokenLines[0].Substring($tokenLines[0].IndexOf('=') + 1)
if ($token.Length -lt 32) {
    throw 'OneBot token is missing or too short'
}

$configDir = Join-Path $resolvedRoot 'config'
New-Item -ItemType Directory -Path $configDir -Force | Out-Null
$configPath = Join-Path $configDir "onebot11_$BotQq.json"

$config = [ordered]@{
    network = [ordered]@{
        httpServers = @()
        httpSseServers = @()
        httpClients = @()
        websocketServers = @(
            [ordered]@{
                enable = $true
                name = 'r-agent-shadow'
                host = '127.0.0.1'
                port = 3001
                reportSelfMessage = $false
                enableForcePushEvent = $true
                messagePostFormat = 'array'
                token = $token
                debug = $false
                heartInterval = 30000
            }
        )
        websocketClients = @()
        plugins = @()
    }
    musicSignUrl = ''
    enableLocalFile2Url = $false
    parseMultMsg = $false
    imageDownloadProxy = ''
    timeout = [ordered]@{
        baseTimeout = 10000
        uploadSpeedKBps = 256
        downloadSpeedKBps = 256
        maxTimeout = 1800000
    }
}

$json = $config | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText(
    $configPath,
    $json,
    [Text.UTF8Encoding]::new($false)
)

$acl = Get-Acl -LiteralPath $configPath
$acl.SetAccessRuleProtection($true, $false)
$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$rule = New-Object Security.AccessControl.FileSystemAccessRule(
    $currentUser,
    'FullControl',
    'Allow'
)
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $configPath -AclObject $acl

[PSCustomObject]@{
    ConfigCreated = $true
    LoopbackOnly = $true
    WebSocketPort = 3001
    TokenConfigured = $true
    SelfMessagesDisabled = $true
    HttpDisabled = $true
    ReverseWebSocketDisabled = $true
    AclProtected = (Get-Acl -LiteralPath $configPath).AreAccessRulesProtected
} | Format-List
