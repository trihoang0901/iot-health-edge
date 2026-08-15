[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [switch]$HostBroker,
    [switch]$StaticOnly
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    if ([string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        exit 17
    }
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$secretsPath = Join-Path $ProjectRoot 'firmware\health-node\include\secrets.h'
$composeFile = Join-Path $ProjectRoot 'deploy\docker-compose.yml'
$envFile = Join-Path $ProjectRoot '.env'
$aclPath = Join-Path $ProjectRoot 'deploy\mosquitto\generated\acl'
$hostPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

function Get-FirmwareDefine {
    param(
        [string]$Source,
        [string]$Name
    )

    $quote = [char]34
    $pattern = '(?m)^\s*#define\s+' + [regex]::Escape($Name) +
        '\s+' + $quote + '([^' + $quote + ']+)' + $quote
    $pattern += '\s*(?://.*)?$'
    $defineMatches = [regex]::Matches($Source, $pattern)
    if ($defineMatches.Count -ne 1) {
        throw "Missing firmware define: $Name"
    }
    $value = $defineMatches[0].Groups[1].Value
    if ($value.Contains([char]92)) {
        throw "Escaped firmware define is not supported: $Name"
    }
    return $value
}

function Test-FirmwareWriteAcl {
    param(
        [string[]]$Lines,
        [string]$Username,
        [string]$DeviceId
    )

    $requiredTopics = @(
        "iot-health/v1/devices/$DeviceId/telemetry",
        "iot-health/v1/devices/$DeviceId/event",
        "iot-health/v1/devices/$DeviceId/status"
    )
    $writeTopics = New-Object 'System.Collections.Generic.HashSet[string]' (
        [StringComparer]::Ordinal
    )
    $currentUser = $null
    $targetUserSections = 0
    $targetWriteRules = 0
    foreach ($line in $Lines) {
        $userMatch = [regex]::Match($line, '^\s*user\s+(\S+)\s*$')
        if ($userMatch.Success) {
            $currentUser = $userMatch.Groups[1].Value
            if ($currentUser -ceq $Username) {
                ++$targetUserSections
            }
            continue
        }
        if ($currentUser -cne $Username) {
            continue
        }
        if ([string]::IsNullOrWhiteSpace($line) -or $line -match '^\s*#') {
            continue
        }
        $topicMatch = [regex]::Match($line, '^\s*topic\s+write\s+(\S+)\s*$')
        if (-not $topicMatch.Success) {
            return $false
        }
        ++$targetWriteRules
        [void]$writeTopics.Add($topicMatch.Groups[1].Value)
    }

    if (
        $targetUserSections -ne 1 -or
        $targetWriteRules -ne 3 -or
        $writeTopics.Count -ne 3
    ) {
        return $false
    }

    foreach ($requiredTopic in $requiredTopics) {
        if (-not $writeTopics.Contains($requiredTopic)) {
            return $false
        }
    }
    return $true
}

try {
    $source = [IO.File]::ReadAllText($secretsPath)
    $firmwareUsername = Get-FirmwareDefine -Source $source -Name 'MQTT_USERNAME'
    $firmwareDeviceId = Get-FirmwareDefine -Source $source -Name 'DEVICE_ID'
    if ($firmwareDeviceId -cnotmatch '^[a-z0-9][a-z0-9-]{0,30}$') {
        exit 16
    }
    if (-not (Test-FirmwareWriteAcl `
        -Lines ([IO.File]::ReadAllLines($aclPath)) `
        -Username $firmwareUsername `
        -DeviceId $firmwareDeviceId
    )) {
        exit 16
    }
    if ($StaticOnly) {
        exit 0
    }
    $payloadObject = [ordered]@{
        host = if ($HostBroker) { '127.0.0.1' } else { 'mosquitto' }
        port = 1883
        username = $firmwareUsername
        password = Get-FirmwareDefine -Source $source -Name 'MQTT_PASSWORD'
        timeout_seconds = 5.0
    }
    $payload = $payloadObject | ConvertTo-Json -Compress
    $encodedPayload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($payload))
    Write-Verbose (
        'MQTT auth probe input: username_length={0}, password_length={1}' -f
        $payloadObject.username.Length,
        $payloadObject.password.Length
    )

    $previousPreference = $ErrorActionPreference
    try {
        # Credential values travel only through stdin. Suppress native output so
        # neither Docker nor a Python exception can echo sensitive input.
        $ErrorActionPreference = 'Continue'
        if ($HostBroker) {
            if (-not (Test-Path -LiteralPath $hostPython -PathType Leaf)) {
                exit 17
            }
            Push-Location $ProjectRoot
            try {
                $encodedPayload | & $hostPython -m edge.mqtt_auth_probe --base64 *> $null
            }
            finally {
                Pop-Location
            }
        }
        else {
            $encodedPayload | & docker compose --env-file $envFile -f $composeFile exec -T edge `
                python -m edge.mqtt_auth_probe --base64 *> $null
        }
        $result = $LASTEXITCODE
        Write-Verbose "MQTT auth probe native exit code: $result"
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}
catch {
    Write-Verbose ("MQTT auth probe setup failed: " + $_.Exception.GetType().Name)
    exit 17
}

if ($result -eq 0) {
    exit 0
}
if ($result -eq 16) {
    exit 16
}
exit 17
