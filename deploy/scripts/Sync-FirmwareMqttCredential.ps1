[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$ProjectRoot
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    if ([string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        throw 'Khong xac dinh duoc thu muc du an.'
    }
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$envPath = Join-Path $ProjectRoot '.env'
$secretsPath = Join-Path $ProjectRoot 'firmware\health-node\include\secrets.h'

function Get-DotEnvValue {
    param(
        [string[]]$Lines,
        [string]$Name
    )

    $candidateValues = New-Object 'System.Collections.Generic.List[string]'
    $pattern = '^\s*' + [regex]::Escape($Name) + '\s*=(.*)$'
    foreach ($line in $Lines) {
        $match = [regex]::Match($line, $pattern)
        if ($match.Success) {
            $candidateValues.Add($match.Groups[1].Value)
        }
    }
    if ($candidateValues.Count -eq 0) {
        throw "Missing local setting: $Name"
    }
    if ($candidateValues.Count -ne 1) {
        throw "Duplicate local setting: $Name"
    }

    $rawValue = $candidateValues[0]
    $trimmedValue = $rawValue.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmedValue)) {
        throw "Missing local setting: $Name"
    }

    if ($trimmedValue[0] -eq [char]34 -or $trimmedValue[0] -eq [char]39) {
        $quote = $trimmedValue[0]
        $closingIndex = $trimmedValue.IndexOf($quote, 1)
        if ($closingIndex -lt 1) {
            throw "Malformed quoted local setting: $Name"
        }
        $value = $trimmedValue.Substring(1, $closingIndex - 1)
        $suffix = $trimmedValue.Substring($closingIndex + 1)
        if ($value.Contains($quote) -or $suffix -notmatch '^\s*(?:#.*)?$') {
            throw "Malformed quoted local setting: $Name"
        }
    }
    else {
        $comment = [regex]::Match($rawValue, '\s+#')
        if ($comment.Success) {
            $rawValue = $rawValue.Substring(0, $comment.Index)
        }
        $value = $rawValue.Trim()
    }

    if (
        [string]::IsNullOrWhiteSpace($value) -or
        $value.Contains([char]34) -or
        $value.Contains([char]92) -or
        $value.Contains("`r") -or
        $value.Contains("`n") -or
        $value.Contains([char]0)
    ) {
        throw "$Name cannot be represented safely in the firmware header"
    }
    return $value
}

function Set-FirmwareDefine {
    param(
        [string]$Source,
        [string]$Name,
        [string]$Value
    )

    $quote = [char]34
    $pattern = '(?m)^(\s*#define\s+' + [regex]::Escape($Name) +
        '\s+' + $quote + ')([^' + $quote + ']*?)(' + $quote + '\s*)$'
    if (-not [regex]::IsMatch($Source, $pattern)) {
        throw "Missing firmware define: $Name"
    }
    return [regex]::Replace(
        $Source,
        $pattern,
        [System.Text.RegularExpressions.MatchEvaluator]{
            param($match)
            return $match.Groups[1].Value + $Value + $match.Groups[3].Value
        },
        1
    )
}

if (-not $PSCmdlet.ShouldProcess($secretsPath, 'Synchronize local node MQTT credential')) {
    exit 0
}

$credentialMutex = New-Object System.Threading.Mutex(
    $false,
    'Local\IotHealthEdge.MqttCredentialFiles.v1'
)
$credentialMutexAcquired = $false
try {
    try {
        $credentialMutexAcquired = $credentialMutex.WaitOne(0)
    }
    catch [System.Threading.AbandonedMutexException] {
        $credentialMutexAcquired = $true
    }
    if (-not $credentialMutexAcquired) {
        throw 'Mot tien trinh khac dang thay doi credential MQTT.'
    }

$envLines = [IO.File]::ReadAllLines($envPath)
$username = Get-DotEnvValue -Lines $envLines -Name 'SIMULATOR_MQTT_USERNAME'
$password = Get-DotEnvValue -Lines $envLines -Name 'SIMULATOR_MQTT_PASSWORD'
foreach ($setting in @(
    @{ Name = 'SIMULATOR_MQTT_USERNAME'; Value = $username },
    @{ Name = 'SIMULATOR_MQTT_PASSWORD'; Value = $password }
)) {
    if ($setting.Value -match '(?i)replace[-_]?with[-_]?local|placeholder|^\s*<.*>\s*$') {
        throw ($setting.Name + ' van la gia tri mau.')
    }
}
$firmwareSource = [IO.File]::ReadAllText($secretsPath)
$updated = Set-FirmwareDefine -Source $firmwareSource -Name 'MQTT_USERNAME' -Value $username
$updated = Set-FirmwareDefine -Source $updated -Name 'MQTT_PASSWORD' -Value $password

$temporaryPath = Join-Path (
    Split-Path -Parent $secretsPath
) ('secrets.' + [guid]::NewGuid().ToString('N') + '.h')
try {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($temporaryPath, $updated, $utf8NoBom)
    Move-Item -LiteralPath $temporaryPath -Destination $secretsPath -Force
}
finally {
    Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
}

Write-Host 'Da dong bo credential node vao secrets.h ma khong hien thi gia tri.'
Write-Host 'Can build/upload lai firmware; chi sua file khong thay doi NodeMCU dang chay.'
}
finally {
    if ($credentialMutexAcquired) {
        $credentialMutex.ReleaseMutex()
    }
    $credentialMutex.Dispose()
}
