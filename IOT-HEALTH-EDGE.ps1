[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        'Install', 'StartSoftware', 'StartHardware', 'StartLegacy',
        'Stop', 'Status', 'Logs'
    )]
    [string]$Action,

    [switch]$NoPause,

    [ValidateRange(1, 1000)]
    [int]$Tail = 200,

    [ValidatePattern('^[1-9][0-9]*[smhd]$')]
    [string]$Since = '10m'
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$script:Root = $PSScriptRoot
$script:EnvFile = Join-Path $script:Root '.env'
$script:ComposeFile = Join-Path $script:Root 'deploy\docker-compose.yml'
$script:PasswordFile = Join-Path $script:Root 'deploy\mosquitto\generated\passwords'
$script:AclFile = Join-Path $script:Root 'deploy\mosquitto\generated\acl'
$script:SecretsFile = Join-Path $script:Root 'firmware\health-node\include\secrets.h'
$script:DashboardUrl = 'http://127.0.0.1:8000/'

function Write-Step {
    param([string]$Message)
    Write-Host "`n==> $Message"
}

function Test-NonEmptyFile {
    param([string]$Path)
    return (Test-Path -LiteralPath $Path -PathType Leaf) -and
        ((Get-Item -LiteralPath $Path).Length -gt 0)
}

function Invoke-Native {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$FailureMessage
    )
    $previousPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5.1 wraps native stderr as ErrorRecord. Keep it
        # visible, but decide success from the native exit code ourselves.
        $ErrorActionPreference = 'Continue'
        & $FilePath @ArgumentList
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        throw "$FailureMessage (exit $exitCode)."
    }
}

function Invoke-NativeQuiet {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList
    )

    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $FilePath @ArgumentList *> $null
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Get-ComposeBaseArguments {
    param(
        [switch]$RequireEnv,
        [switch]$UseEmptyEnv
    )

    if ($RequireEnv -and -not (Test-Path -LiteralPath $script:EnvFile)) {
        throw 'Thieu .env. Chay INSTALL-IOT-HEALTH-EDGE.bat va dien cau hinh truoc.'
    }
    $arguments = @()
    if ($UseEmptyEnv) {
        # An explicit empty Windows device prevents Compose from auto-loading .env.
        $arguments += @('--env-file', 'NUL')
    }
    elseif (Test-Path -LiteralPath $script:EnvFile) {
        $arguments += @('--env-file', $script:EnvFile)
    }
    return $arguments + @('-f', $script:ComposeFile, '--profile', 'full')
}

function Assert-DockerReady {
    if (-not (Get-Command docker.exe -ErrorAction SilentlyContinue)) {
        throw 'Khong tim thay Docker CLI. Hay cai va mo Docker Desktop.'
    }
    if ((Invoke-NativeQuiet -FilePath 'docker.exe' -ArgumentList @('compose', 'version')) -ne 0) {
        throw 'Docker Compose khong san sang.'
    }
    if ((Invoke-NativeQuiet -FilePath 'docker.exe' -ArgumentList @('info')) -ne 0) {
        throw 'Docker Desktop chua o trang thai Running.'
    }
}

function Get-EnvValue {
    param([string]$Name)

    $text = [IO.File]::ReadAllText($script:EnvFile)
    $match = [regex]::Match(
        $text,
        '(?m)^' + [regex]::Escape($Name) + '=([^\r\n]*)$'
    )
    if (-not $match.Success) {
        return $null
    }
    return $match.Groups[1].Value.Trim()
}

function Test-PlaceholderValue {
    param([string]$Value)
    return [string]::IsNullOrWhiteSpace($Value) -or
        $Value -match '(?i)replace[-_]?with|placeholder|^\s*<.*>\s*$'
}

function Assert-SoftwareConfiguration {
    foreach ($path in @($script:EnvFile, $script:PasswordFile, $script:AclFile)) {
        if (-not (Test-NonEmptyFile -Path $path)) {
            throw 'Thieu cau hinh local/Mosquitto. Chay INSTALL-IOT-HEALTH-EDGE.bat truoc.'
        }
    }
    if (Test-PlaceholderValue -Value (Get-EnvValue -Name 'MQTT_PASSWORD')) {
        throw 'MQTT_PASSWORD trong .env chua duoc cau hinh.'
    }
}

function Get-SingleDefineValue {
    param(
        [string]$Text,
        [string]$Name
    )

    $quote = [char]34
    $matches = [regex]::Matches(
        $Text,
        '(?m)^\s*#define\s+' + [regex]::Escape($Name) +
        '\s+' + $quote + '([^' + $quote + ']*)' + $quote + '\s*$'
    )
    if ($matches.Count -ne 1) {
        throw "secrets.h phai co dung mot #define $Name dang chuoi don gian."
    }
    return $matches[0].Groups[1].Value
}

function Assert-HardwareConfiguration {
    Assert-SoftwareConfiguration
    if (-not (Test-NonEmptyFile -Path $script:SecretsFile)) {
        throw 'Thieu firmware\health-node\include\secrets.h.'
    }

    $secretText = [IO.File]::ReadAllText($script:SecretsFile)
    $values = @{}
    foreach ($name in @(
        'WIFI_SSID', 'WIFI_PASSWORD', 'DEVICE_ID', 'MQTT_HOST',
        'MQTT_USERNAME', 'MQTT_PASSWORD'
    )) {
        $values[$name] = Get-SingleDefineValue -Text $secretText -Name $name
        if (Test-PlaceholderValue -Value $values[$name]) {
            throw "secrets.h con gia tri mau tai $name."
        }
    }
    if ($values['MQTT_HOST'] -eq '127.0.0.1') {
        throw 'MQTT_HOST cua firmware khong duoc la 127.0.0.1.'
    }

    [Net.IPAddress]$mqttAddress = $null
    if (-not [Net.IPAddress]::TryParse($values['MQTT_HOST'], [ref]$mqttAddress) -or
        $mqttAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
        [Net.IPAddress]::IsLoopback($mqttAddress)) {
        throw 'MQTT_HOST cua firmware phai la IPv4 local non-loopback.'
    }

    try {
        $localIpv4 = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.AddressState -eq 'Preferred' -and
                $_.IPAddress -ne '0.0.0.0' -and
                -not [Net.IPAddress]::IsLoopback([Net.IPAddress]::Parse($_.IPAddress))
            } | ForEach-Object { $_.IPAddress })
    }
    catch {
        throw 'Khong truy van duoc IPv4 local de xac minh MQTT_HOST.'
    }
    if ($localIpv4 -notcontains $mqttAddress.IPAddressToString) {
        throw 'MQTT_HOST trong firmware khong khop IPv4 local dang hoat dong.'
    }

    if (Test-PlaceholderValue -Value (Get-EnvValue -Name 'SIMULATOR_MQTT_PASSWORD')) {
        throw 'SIMULATOR_MQTT_PASSWORD trong .env chua duoc cau hinh.'
    }
    $aclText = [IO.File]::ReadAllText($script:AclFile)
    if ($aclText -match '__DEVICE_ID__|\{device_id\}') {
        throw 'ACL Mosquitto van con placeholder device_id.'
    }
    return $values
}

function Wait-EdgeHealthy {
    param([int]$TimeoutSeconds = 90)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $health = Invoke-RestMethod -Uri ($script:DashboardUrl + 'healthz') -TimeoutSec 3
            if ($health.database.healthy -eq $true -and
                $health.mqtt.connected -eq $true -and
                $health.mqtt.subscribed -eq $true -and
                $health.ingestion.worker_alive -eq $true) {
                return $health
            }
        }
        catch {
            # Service startup races are expected inside the bounded wait.
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "Edge API/MQTT khong healthy sau $TimeoutSeconds giay."
}

function Start-SoftwareStack {
    param([switch]$OpenDashboard)

    Assert-SoftwareConfiguration
    Assert-DockerReady
    $compose = Get-ComposeBaseArguments -RequireEnv

    Write-Step 'Khoi dong Mosquitto, edge API va dashboard'
    Invoke-Native -FilePath 'docker.exe' `
        -ArgumentList ($compose + @('up', '-d', '--build')) `
        -FailureMessage 'Docker Compose khoi dong that bai'
    Invoke-Native -FilePath 'docker.exe' `
        -ArgumentList ($compose + @('restart', 'mosquitto')) `
        -FailureMessage 'Mosquitto khong tai lai duoc password/ACL'

    Write-Step 'Cho edge API, database va MQTT worker healthy'
    $null = Wait-EdgeHealthy -TimeoutSeconds 90
    Write-Host '[OK] Software stack da san sang.'
    if ($OpenDashboard) {
        Start-Process $script:DashboardUrl
        Write-Host "[OK] Da mo $($script:DashboardUrl)"
    }
}

function Get-PythonLauncher {
    foreach ($candidate in @(
        @{ Name = 'py.exe'; Prefix = @('-3') },
        @{ Name = 'python.exe'; Prefix = @() }
    )) {
        $command = Get-Command $candidate.Name -ErrorAction SilentlyContinue
        if ($null -eq $command) {
            continue
        }
        $probeArguments = @($candidate.Prefix) + @(
            '-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
        )
        if ((Invoke-NativeQuiet -FilePath $command.Source -ArgumentList $probeArguments) -eq 0) {
            return @{ Path = $command.Source; Prefix = $candidate.Prefix }
        }
    }
    throw 'Can Python 3.11 tro len. Hay cai Python roi chay lai installer.'
}

function Invoke-PythonLauncher {
    param(
        [hashtable]$Launcher,
        [string[]]$Arguments,
        [string]$FailureMessage
    )
    Invoke-Native -FilePath $Launcher.Path `
        -ArgumentList (@($Launcher.Prefix) + $Arguments) `
        -FailureMessage $FailureMessage
}

function Install-System {
    Write-Step 'Kiem tra Docker Desktop va Python'
    Assert-DockerReady
    $python = Get-PythonLauncher

    $venvPython = Join-Path $script:Root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Step 'Tao moi truong Python .venv'
        Invoke-PythonLauncher -Launcher $python `
            -Arguments @('-m', 'venv', (Join-Path $script:Root '.venv')) `
            -FailureMessage 'Khong tao duoc .venv'
    }
    Write-Step 'Cai dependency ung dung'
    Invoke-Native -FilePath $venvPython `
        -ArgumentList @('-m', 'pip', 'install', '--upgrade', 'pip') `
        -FailureMessage 'Khong nang cap duoc pip'
    Invoke-Native -FilePath $venvPython `
        -ArgumentList @('-m', 'pip', 'install', '-e', $script:Root) `
        -FailureMessage 'Khong cai duoc dependency ung dung'

    $pioPython = Join-Path $script:Root '.platformio-venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pioPython)) {
        Write-Step 'Tao moi truong PlatformIO rieng'
        Invoke-PythonLauncher -Launcher $python `
            -Arguments @('-m', 'venv', (Join-Path $script:Root '.platformio-venv')) `
            -FailureMessage 'Khong tao duoc .platformio-venv'
    }
    if ((Invoke-NativeQuiet -FilePath $pioPython -ArgumentList @('-m', 'platformio', '--version')) -ne 0) {
        Write-Step 'Cai dat hoac sua chua PlatformIO trong moi truong rieng'
        Invoke-Native -FilePath $pioPython `
            -ArgumentList @('-m', 'pip', 'install', 'platformio') `
            -FailureMessage 'Khong cai duoc PlatformIO'
    }

    if (-not (Test-Path -LiteralPath $script:EnvFile)) {
        Copy-Item -LiteralPath (Join-Path $script:Root '.env.example') -Destination $script:EnvFile
        Write-Host '[NEW] Da tao .env tu .env.example; hay dien mat khau local.'
    }
    else {
        Write-Host '[KEEP] Giu nguyen .env hien co.'
    }
    if (-not (Test-Path -LiteralPath $script:SecretsFile)) {
        Copy-Item `
            -LiteralPath (Join-Path $script:Root 'firmware\health-node\include\secrets.example.h') `
            -Destination $script:SecretsFile
        Write-Host '[NEW] Da tao secrets.h tu file mau; hay dien Wi-Fi/MQTT local.'
    }
    else {
        Write-Host '[KEEP] Giu nguyen secrets.h hien co.'
    }

    $hasPassword = Test-Path -LiteralPath $script:PasswordFile
    $hasAcl = Test-Path -LiteralPath $script:AclFile
    if (-not $hasPassword -and -not $hasAcl) {
        Write-Step 'Khoi tao tai khoan va ACL Mosquitto'
        Invoke-Native -FilePath 'powershell.exe' `
            -ArgumentList @(
                '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                (Join-Path $script:Root 'deploy\scripts\Initialize-Mosquitto.ps1')
            ) `
            -FailureMessage 'Khoi tao Mosquitto that bai'
    }
    elseif ($hasPassword -and $hasAcl) {
        Write-Host '[KEEP] Giu nguyen password hash va ACL Mosquitto hien co.'
    }
    else {
        throw 'Cau hinh Mosquitto dang thieu mot phan. Khong tu ghi de; hay sao luu va khoi tao lai co chu y.'
    }
    Write-Host "`n[OK] Cai dat hoan tat. Dien .env/secrets.h, sau do chay START-SOFTWARE.bat."
}

function Get-PlatformIoCommand {
    foreach ($pythonPath in @(
        (Join-Path $script:Root '.platformio-venv\Scripts\python.exe'),
        (Join-Path $script:Root '.venv\Scripts\python.exe')
    )) {
        if (Test-Path -LiteralPath $pythonPath) {
            if ((Invoke-NativeQuiet -FilePath $pythonPath -ArgumentList @('-m', 'platformio', '--version')) -eq 0) {
                return @{ FilePath = $pythonPath; Prefix = @('-m', 'platformio') }
            }
        }
    }
    foreach ($name in @('pio.exe', 'platformio.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $command) {
            if ((Invoke-NativeQuiet -FilePath $command.Source -ArgumentList @('--version')) -eq 0) {
                return @{ FilePath = $command.Source; Prefix = @() }
            }
        }
    }
    throw 'PlatformIO khong san sang. Chay INSTALL-IOT-HEALTH-EDGE.bat.'
}

function Get-Ch340Port {
    param([switch]$AllowMissing)

    if (-not (Get-Command Get-PnpDevice -ErrorAction SilentlyContinue)) {
        throw 'PowerShell khong co Get-PnpDevice de do cong CH340.'
    }
    try {
        $ports = @(Get-PnpDevice -Class Ports -PresentOnly -ErrorAction Stop |
            Where-Object {
                $_.FriendlyName -match 'CH340' -or
                $_.InstanceId -match 'VID_1A86.PID_7523'
            } | ForEach-Object {
                $match = [regex]::Match($_.FriendlyName, 'COM(\d+)')
                if ($match.Success) { [int]$match.Groups[1].Value }
            } | Sort-Object)
    }
    catch {
        throw 'Khong truy van duoc cong CH340.'
    }
    if ($ports.Count -eq 0) {
        if ($AllowMissing) {
            return $null
        }
        throw 'Khong tim thay NodeMCU CH340. Hardware start dung truoc khi upload.'
    }
    return 'COM' + $ports[0]
}

function Wait-FreshHardwareTelemetry {
    param(
        [string]$DeviceId,
        [DateTimeOffset]$StartedAt,
        [int]$TimeoutSeconds = 30
    )

    $culture = [Globalization.CultureInfo]::InvariantCulture
    $styles = [Globalization.DateTimeStyles]([int][Globalization.DateTimeStyles]::AssumeUniversal -bor
        [int][Globalization.DateTimeStyles]::AdjustToUniversal)
    $base = $script:DashboardUrl + 'api/v1/devices/' + [uri]::EscapeDataString($DeviceId)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $device = Invoke-RestMethod -Uri $base -TimeoutSec 3
            $latest = Invoke-RestMethod -Uri ($base + '/latest') -TimeoutSec 3
            $received = [DateTimeOffset]::Parse($latest.received_at, $culture, $styles)
            $schema = if ($latest.schema) { $latest.schema } else { $latest.schema_version }
            if ($device.online -eq $true -and
                $received -ge $StartedAt -and
                $schema -eq 'health.telemetry.v4' -and
                $latest.system.fw -eq '0.4.0') {
                return
            }
        }
        catch {
            # Keep polling until the bounded hardware gate expires.
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw 'Chua nhan telemetry v4 moi tu firmware 0.4.0 sau upload.'
}

function Start-HardwareStack {
    param([switch]$AllowMissingHardware)

    Write-Step 'Kiem tra cau hinh firmware fail-closed'
    $firmware = Assert-HardwareConfiguration
    Assert-DockerReady
    $comPort = Get-Ch340Port -AllowMissing:$AllowMissingHardware
    if ([string]::IsNullOrWhiteSpace($comPort)) {
        Write-Host '[WARN] Khong co CH340; launcher tuong thich chi khoi dong software.'
        Start-SoftwareStack -OpenDashboard
        return
    }
    $platformIo = Get-PlatformIoCommand
    Write-Host "[OK] NodeMCU tai $comPort; PlatformIO da san sang."

    Start-SoftwareStack

    Write-Step 'Kiem tra credential MQTT firmware truoc upload'
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File `
            (Join-Path $script:Root 'deploy\scripts\Test-NodeMqttCredential.ps1')
        $authExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($authExitCode -eq 16) {
        throw 'Credential/ACL firmware khong khop Mosquitto. Khong upload.'
    }
    if ($authExitCode -eq 17) {
        throw 'MQTT auth probe khong hoan tat (exit 17). Kiem tra define firmware, Docker va probe setup. Khong upload.'
    }
    if ($authExitCode -ne 0) {
        throw "MQTT auth probe gap loi noi bo (exit $authExitCode). Khong upload."
    }

    Write-Step "Nap firmware qua $comPort"
    Invoke-Native -FilePath $platformIo.FilePath `
        -ArgumentList (@($platformIo.Prefix) + @(
            'run', '-d', (Join-Path $script:Root 'firmware\health-node'),
            '--target', 'upload', '--upload-port', $comPort
        )) `
        -FailureMessage "Khong nap duoc firmware qua $comPort"
    $uploadCompletedUtc = [DateTimeOffset]::UtcNow

    Write-Step 'Xac minh telemetry moi sau upload'
    $null = Wait-EdgeHealthy -TimeoutSeconds 90
    Wait-FreshHardwareTelemetry `
        -DeviceId $firmware['DEVICE_ID'] `
        -StartedAt $uploadCompletedUtc `
        -TimeoutSeconds 30
    Start-Process $script:DashboardUrl
    Write-Host '[OK] Hardware, MQTT, edge va dashboard da ket noi end-to-end.'
}

function Stop-System {
    Assert-DockerReady
    $compose = Get-ComposeBaseArguments
    Write-Step 'Dung service, giu nguyen Docker volumes'
    Invoke-Native -FilePath 'docker.exe' `
        -ArgumentList ($compose + @('down')) `
        -FailureMessage 'Khong dung duoc he thong'
    Write-Host '[OK] Da dung he thong; du lieu Mosquitto/SQLite van duoc giu.'
}

function Show-SystemStatus {
    Assert-DockerReady
    $compose = Get-ComposeBaseArguments
    Write-Step 'Trang thai Docker Compose'
    Invoke-Native -FilePath 'docker.exe' `
        -ArgumentList ($compose + @('ps')) `
        -FailureMessage 'Khong doc duoc trang thai Compose'
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $running = @(& docker.exe @($compose + @('ps', '--status', 'running', '--services')))
        $statusExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($statusExitCode -ne 0 -or
        $running -notcontains 'mosquitto' -or
        $running -notcontains 'edge') {
        throw 'Mosquitto hoac edge chua chay.'
    }
    $null = Wait-EdgeHealthy -TimeoutSeconds 5
    Write-Host "[OK] Mosquitto, edge, MQTT worker va dashboard healthy: $($script:DashboardUrl)"
}

function Show-SystemLogs {
    Assert-DockerReady
    $compose = Get-ComposeBaseArguments -UseEmptyEnv
    Write-Step "Log gioi han: service edge/mosquitto, since=$Since, tail=$Tail"
    Invoke-Native -FilePath 'docker.exe' `
        -ArgumentList ($compose + @(
            'logs', '--since', $Since, '--tail', $Tail.ToString(),
            'mosquitto', 'edge'
        )) `
        -FailureMessage 'Khong doc duoc log he thong'
}

try {
    Push-Location -LiteralPath $script:Root
    try {
        switch ($Action) {
            'Install' { Install-System }
            'StartSoftware' { Start-SoftwareStack -OpenDashboard }
            'StartHardware' { Start-HardwareStack }
            'StartLegacy' { Start-HardwareStack -AllowMissingHardware }
            'Stop' { Stop-System }
            'Status' { Show-SystemStatus }
            'Logs' { Show-SystemLogs }
        }
    }
    finally {
        Pop-Location
    }
    Write-Host "`n[OK] Action $Action hoan tat."
    exit 0
}
catch {
    Write-Host "`n[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
