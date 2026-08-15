[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$ProjectRoot,
    [string]$Image = 'eclipse-mosquitto:2.0.22'
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
$generatedDir = Join-Path $ProjectRoot 'deploy\mosquitto\generated'
$passwordFile = Join-Path $generatedDir 'passwords'
$rotationId = [guid]::NewGuid().ToString('N')
$stagedPasswordFile = Join-Path $generatedDir ('passwords.rotate.' + $rotationId + '.next')
$composeFile = Join-Path $ProjectRoot 'deploy\docker-compose.yml'
$probeScript = Join-Path $ProjectRoot 'deploy\scripts\Test-NodeMqttCredential.ps1'
$hostPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

function Get-UniqueFirmwareDefine {
    param(
        [string]$Source,
        [string]$Name
    )

    $quote = [char]34
    $pattern = '(?m)^\s*#define\s+' + [regex]::Escape($Name) +
        '\s+' + $quote + '([^' + $quote + ']+)' + $quote + '\s*(?://.*)?$'
    $defineMatches = [regex]::Matches($Source, $pattern)
    if ($defineMatches.Count -ne 1) {
        throw "Firmware define khong hop le: $Name"
    }
    $value = $defineMatches[0].Groups[1].Value
    if ($value.Contains([char]92)) {
        throw "Firmware define co escape khong duoc ho tro: $Name"
    }
    return $value
}

function Set-UniqueFirmwareDefine {
    param(
        [string]$Source,
        [string]$Name,
        [string]$Value
    )

    $quote = [char]34
    $pattern = '(?m)^(\s*#define\s+' + [regex]::Escape($Name) +
        '\s+' + $quote + ')([^' + $quote + ']+)(' + $quote + '\s*(?://.*)?)$'
    $defineRegex = [regex]::new($pattern)
    if ($defineRegex.Matches($Source).Count -ne 1) {
        throw "Firmware define khong hop le: $Name"
    }
    return $defineRegex.Replace(
        $Source,
        [System.Text.RegularExpressions.MatchEvaluator]{
            param($match)
            return $match.Groups[1].Value + $Value + $match.Groups[3].Value
        },
        1
    )
}

function Get-UniqueDotEnvUsername {
    param([string]$Source)

    $pattern = '(?m)^\s*SIMULATOR_MQTT_USERNAME\s*=\s*' +
        '([A-Za-z0-9][A-Za-z0-9._-]{0,63})(?:\s+#.*)?\s*$'
    $settingMatches = [regex]::Matches($Source, $pattern)
    if ($settingMatches.Count -ne 1) {
        throw 'SIMULATOR_MQTT_USERNAME khong hop le hoac bi trung.'
    }
    return $settingMatches[0].Groups[1].Value
}

function Set-UniqueDotEnvValue {
    param(
        [string]$Source,
        [string]$Name,
        [string]$Value
    )

    $settingRegex = [regex]::new(
        '(?m)^\s*' + [regex]::Escape($Name) + '\s*=[^\r\n]*$'
    )
    if ($settingRegex.Matches($Source).Count -ne 1) {
        throw "$Name khong ton tai duy nhat trong .env."
    }
    return $settingRegex.Replace($Source, $Name + '=' + $Value, 1)
}

function Invoke-DockerQuiet {
    param([string[]]$Arguments)

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & docker @Arguments *> $null
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function ConvertTo-WindowsCommandLineArgument {
    param([string]$Value)

    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') {
        return $Value
    }

    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append([char]34)
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq [char]92) {
            ++$backslashes
            continue
        }
        if ($character -eq [char]34) {
            if ($backslashes -gt 0) {
                [void]$builder.Append((([string][char]92) * (2 * $backslashes)))
            }
            [void]$builder.Append([char]92)
            [void]$builder.Append([char]34)
            $backslashes = 0
            continue
        }
        if ($backslashes -gt 0) {
            [void]$builder.Append((([string][char]92) * $backslashes))
            $backslashes = 0
        }
        [void]$builder.Append($character)
    }
    if ($backslashes -gt 0) {
        [void]$builder.Append((([string][char]92) * (2 * $backslashes)))
    }
    [void]$builder.Append([char]34)
    return $builder.ToString()
}

function Invoke-DockerWithUtf8StdinQuiet {
    param(
        [string[]]$Arguments,
        [string]$InputText
    )

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = (Get-Command docker -ErrorAction Stop).Source
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.Arguments = (@(
        $Arguments | ForEach-Object {
            ConvertTo-WindowsCommandLineArgument -Value $_
        }
    ) -join ' ')

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    $inputBytes = [Text.Encoding]::UTF8.GetBytes($InputText)
    $previousInputEncoding = [Console]::InputEncoding
    try {
        # .NET Framework builds Process.StandardInput from Console.InputEncoding.
        # Set a no-preamble encoder before first access to avoid a UTF-8 BOM.
        [Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
        [void]$process.Start()
        $outputTask = $process.StandardOutput.ReadToEndAsync()
        $errorTask = $process.StandardError.ReadToEndAsync()
        $standardInput = $process.StandardInput
        $standardInput.BaseStream.Write($inputBytes, 0, $inputBytes.Length)
        $standardInput.BaseStream.Flush()
        $standardInput.Close()
        $process.WaitForExit()
        [void]$outputTask.GetAwaiter().GetResult()
        [void]$errorTask.GetAwaiter().GetResult()
        return $process.ExitCode
    }
    finally {
        [Console]::InputEncoding = $previousInputEncoding
        [Array]::Clear($inputBytes, 0, $inputBytes.Length)
        $process.Dispose()
    }
}

if (-not $PSCmdlet.ShouldProcess(
    $ProjectRoot,
    'Rotate local node MQTT credential in broker, .env, and firmware source'
)) {
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

foreach ($requiredPath in @(
    $envPath,
    $secretsPath,
    $passwordFile,
    $composeFile,
    $probeScript,
    $hostPython
)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw 'Thieu tep bat buoc de xoay credential MQTT node.'
    }
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Khong tim thay Docker CLI.'
}
if ((Invoke-DockerQuiet -Arguments @('info')) -ne 0) {
    throw 'Docker Desktop chua san sang.'
}
if ((Invoke-DockerQuiet -Arguments @('image', 'inspect', $Image)) -ne 0) {
    throw 'Thieu Mosquitto image cuc bo; hay khoi dong stack truoc.'
}

$previousPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & $hostPython -c 'import paho.mqtt.client' *> $null
    $pythonExit = $LASTEXITCODE
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
        -File $probeScript -ProjectRoot $ProjectRoot -StaticOnly *> $null
    $staticPreflightExit = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousPreference
}
if ($pythonExit -ne 0) {
    throw 'Python venv thieu paho-mqtt; khong the probe broker an toan.'
}
if ($staticPreflightExit -ne 0) {
    throw 'Firmware/ACL node khong nhat quan; khong xoay credential.'
}

$previousPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    $runningServices = @(
        & docker compose --env-file $envPath -f $composeFile `
            ps --status running --services 2> $null
    )
    $serviceQueryExit = $LASTEXITCODE
    if ($serviceQueryExit -eq 0 -and $runningServices -notcontains 'mosquitto') {
        & docker compose --env-file $envPath -f $composeFile up -d mosquitto *> $null
        $brokerStartExit = $LASTEXITCODE
    }
    else {
        $brokerStartExit = $serviceQueryExit
    }
}
finally {
    $ErrorActionPreference = $previousPreference
}
if ($brokerStartExit -ne 0) {
    throw 'Khong khoi dong duoc Mosquitto de xoay credential.'
}

$envOriginal = [IO.File]::ReadAllBytes($envPath)
$secretsOriginal = [IO.File]::ReadAllBytes($secretsPath)
$passwordsOriginal = [IO.File]::ReadAllBytes($passwordFile)
$envSource = [Text.Encoding]::UTF8.GetString($envOriginal)
$secretsSource = [Text.Encoding]::UTF8.GetString($secretsOriginal)
$nodeUsername = Get-UniqueDotEnvUsername -Source $envSource
$firmwareUsername = Get-UniqueFirmwareDefine `
    -Source $secretsSource `
    -Name 'MQTT_USERNAME'
if ($nodeUsername -cne $firmwareUsername) {
    throw 'MQTT username trong .env va firmware khong khop.'
}

$randomBytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $rng.GetBytes($randomBytes)
}
finally {
    $rng.Dispose()
}
$newPassword = [Convert]::ToBase64String($randomBytes).TrimEnd('=').
    Replace('+', '-').Replace('/', '_')
[Array]::Clear($randomBytes, 0, $randomBytes.Length)

$newEnv = Set-UniqueDotEnvValue `
    -Source $envSource `
    -Name 'SIMULATOR_MQTT_PASSWORD' `
    -Value $newPassword
$newSecrets = Set-UniqueFirmwareDefine `
    -Source $secretsSource `
    -Name 'MQTT_PASSWORD' `
    -Value $newPassword
$stagedEnv = Join-Path $ProjectRoot ('.env.rotate.' + $rotationId)
$stagedSecrets = Join-Path (
    Split-Path -Parent $secretsPath
) ('secrets.' + $rotationId + '.h')
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$activated = $false

try {
    [IO.File]::WriteAllText($stagedEnv, $newEnv, $utf8NoBom)
    [IO.File]::WriteAllText($stagedSecrets, $newSecrets, $utf8NoBom)
    Copy-Item -LiteralPath $passwordFile -Destination $stagedPasswordFile -Force

    $generatedPath = (Resolve-Path -LiteralPath $generatedDir).Path
    $passwordInput = $newPassword + "`n" + $newPassword + "`n"
    try {
        # Explicit no-BOM UTF-8 stdin keeps both interactive password entries
        # byte-identical under Windows PowerShell 5.1. No secret enters argv/output.
        $passwdExit = Invoke-DockerWithUtf8StdinQuiet -Arguments @(
            'run', '--rm', '-i',
            '--mount', "type=bind,source=$generatedPath,target=/work",
            $Image, 'mosquitto_passwd', ('/work/' + (Split-Path -Leaf $stagedPasswordFile)),
            $nodeUsername
        ) -InputText $passwordInput
    }
    finally {
        $passwordInput = $null
    }
    if ($passwdExit -ne 0) {
        throw 'Khong tao duoc password hash moi cho node.'
    }
    if ((Invoke-DockerQuiet -Arguments @(
        'run', '--rm',
        '--mount', "type=bind,source=$generatedPath,target=/work",
        '--entrypoint', 'sh', $Image, '-c',
        ('chown mosquitto:mosquitto /work/' + (Split-Path -Leaf $stagedPasswordFile) +
        ' && chmod 0600 /work/' + (Split-Path -Leaf $stagedPasswordFile))
    )) -ne 0) {
        throw 'Khong dat duoc quyen doc an toan cho password hash moi.'
    }

    $activated = $true
    Move-Item -LiteralPath $stagedEnv -Destination $envPath -Force
    Move-Item -LiteralPath $stagedSecrets -Destination $secretsPath -Force
    Move-Item -LiteralPath $stagedPasswordFile -Destination $passwordFile -Force

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & docker compose --env-file $envPath -f $composeFile restart mosquitto *> $null
        $restartExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($restartExit -ne 0) {
        throw 'Mosquitto khong restart duoc sau khi xoay credential.'
    }

    $probeExit = 17
    for ($probeAttempt = 0; $probeAttempt -lt 5; ++$probeAttempt) {
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass `
                -File $probeScript -ProjectRoot $ProjectRoot -HostBroker *> $null
            $probeExit = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousPreference
        }
        if ($probeExit -eq 0) {
            break
        }
        Start-Sleep -Seconds 1
    }
    if ($probeExit -ne 0) {
        throw 'Broker khong chap nhan credential node moi.'
    }
}
catch {
    if (-not $activated) {
        throw 'Xoay credential MQTT node that bai truoc khi kich hoat; cau hinh cu khong doi.'
    }

    $rollbackComplete = $true
    if ($activated) {
        foreach ($restoreItem in @(
            @{ Path = $envPath; Bytes = $envOriginal },
            @{ Path = $secretsPath; Bytes = $secretsOriginal },
            @{ Path = $passwordFile; Bytes = $passwordsOriginal }
        )) {
            try {
                [IO.File]::WriteAllBytes($restoreItem.Path, $restoreItem.Bytes)
            }
            catch {
                $rollbackComplete = $false
            }
        }
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & docker compose --env-file $envPath -f $composeFile restart mosquitto *> $null
            $rollbackRestartExit = $LASTEXITCODE
            $rollbackServices = @(
                & docker compose --env-file $envPath -f $composeFile `
                    ps --status running --services 2> $null
            )
            $rollbackStatusExit = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousPreference
        }
        if (
            $rollbackRestartExit -ne 0 -or
            $rollbackStatusExit -ne 0 -or
            $rollbackServices -notcontains 'mosquitto'
        ) {
            $rollbackComplete = $false
        }
    }
    if (-not $rollbackComplete) {
        throw 'Xoay credential that bai va rollback chua hoan tat; can kiem tra Mosquitto thu cong.'
    }
    throw 'Xoay credential MQTT node that bai; file cu da duoc khoi phuc va broker da restart.'
}
finally {
    Remove-Item -LiteralPath $stagedEnv -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stagedSecrets -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stagedPasswordFile -Force -ErrorAction SilentlyContinue
    $newPassword = $null
    $newEnv = $null
    $newSecrets = $null
}

Write-Host 'Da xoay credential MQTT node, restart broker va xac minh thanh cong.'
Write-Host 'Credential moi khong duoc hien thi; can build/upload lai firmware.'
}
finally {
    if ($credentialMutexAcquired) {
        $credentialMutex.ReleaseMutex()
    }
    $credentialMutex.Dispose()
}
