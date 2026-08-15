[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('Start', 'Doctor', 'Verify', 'Flash', 'OpenPortal', 'ShowPortalAccess')]
    [string]$Mode = 'Start',
    [string]$DeviceId,
    [string]$ApiBaseUrl,
    [string]$Port,
    [switch]$NoPause,
    [switch]$NoOpenBrowser
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$envFile = Join-Path $root '.env'
$composeFile = Join-Path $root 'deploy\docker-compose.yml'
$generatedDir = Join-Path $root 'deploy\mosquitto\generated'
$passwordFile = Join-Path $generatedDir 'passwords'
$aclFile = Join-Path $generatedDir 'acl'
$firmwareDir = Join-Path $root 'firmware\health-node'
$bootstrapHeader = Join-Path $firmwareDir 'include\secrets.h'
$portalHeader = Join-Path $firmwareDir 'include\provisioning_secret.h'
$portalSecretFile = Join-Path $generatedDir 'portal-access.dpapi'
$python = Join-Path $root '.venv\Scripts\python.exe'
$verifyScript = Join-Path $PSScriptRoot 'VERIFY-MVP.ps1'
$mqttDoctorScript = Join-Path $PSScriptRoot 'Test-MqttAccess.py'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-Step { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Cyan }

function Read-DotEnv {
    param([string]$Path)
    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $values }
    foreach ($line in [IO.File]::ReadAllLines($Path)) {
        if ($line -match '^\s*(?:#|$)') { continue }
        $match = [regex]::Match($line, '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$')
        if (-not $match.Success) { continue }
        $value = $match.Groups[2].Value.Trim()
        if ($value.Length -ge 2 -and (($value[0] -eq '"' -and $value[$value.Length - 1] -eq '"') -or ($value[0] -eq "'" -and $value[$value.Length - 1] -eq "'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$match.Groups[1].Value] = $value
    }
    return $values
}

function Assert-NonEmptyFile {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path) -or (Get-Item -LiteralPath $Path).Length -eq 0) { throw "Thieu hoac rong: $Label" }
}

function Assert-LocalRuntimeConfig {
    Assert-NonEmptyFile -Path $envFile -Label '.env'
    Assert-NonEmptyFile -Path $passwordFile -Label 'Mosquitto password database'
    Assert-NonEmptyFile -Path $aclFile -Label 'Mosquitto ACL'
    $settings = Read-DotEnv -Path $envFile
    if (-not $settings.ContainsKey('MQTT_PASSWORD') -or [string]::IsNullOrWhiteSpace($settings.MQTT_PASSWORD) -or $settings.MQTT_PASSWORD -match 'replace_with_local|placeholder|^<.*>$') {
        throw 'MQTT_PASSWORD trong .env chua duoc cau hinh.'
    }
    if ([IO.File]::ReadAllText($aclFile) -match '__DEVICE_ID__|\{device_id\}') { throw 'ACL Mosquitto van con placeholder device_id.' }
    return $settings
}

function Assert-DockerReady {
    if (-not (Get-Command docker.exe -ErrorAction SilentlyContinue)) { throw 'Khong tim thay Docker CLI. Hay cai va mo Docker Desktop.' }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop chua o trang thai Running.' }
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose khong san sang.' }
}

function Resolve-ProjectDeviceId {
    param([hashtable]$Settings)
    if (-not [string]::IsNullOrWhiteSpace($DeviceId)) { return $DeviceId }
    if ($Settings.ContainsKey('DEVICE_ID') -and -not [string]::IsNullOrWhiteSpace($Settings.DEVICE_ID)) { return $Settings.DEVICE_ID }
    return 'health-node-01'
}

function Resolve-ApiBaseUrl {
    param([hashtable]$Settings)
    $value = $ApiBaseUrl
    if ([string]::IsNullOrWhiteSpace($value) -and $Settings.ContainsKey('EDGE_API_BASE_URL')) { $value = $Settings.EDGE_API_BASE_URL }
    if ([string]::IsNullOrWhiteSpace($value)) { $value = 'http://127.0.0.1:8000' }
    return $value.TrimEnd('/')
}

function Wait-EdgeHealthy {
    param([string]$BaseUrl, [int]$TimeoutSeconds = 90)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $health = Invoke-RestMethod -Uri "$BaseUrl/healthz" -TimeoutSec 3
            if ($health.status -eq 'ok') { return }
        } catch {}
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "Edge API khong healthy sau $TimeoutSeconds giay."
}

function Wait-NewTelemetry {
    param([string]$BaseUrl, [string]$TargetDeviceId, [DateTimeOffset]$StartedAt, [int]$TimeoutSeconds = 15)
    $culture = [Globalization.CultureInfo]::InvariantCulture
    $styles = [Globalization.DateTimeStyles]([int][Globalization.DateTimeStyles]::AssumeUniversal -bor [int][Globalization.DateTimeStyles]::AdjustToUniversal)
    $deviceUrl = "$BaseUrl/api/v1/devices/$([uri]::EscapeDataString($TargetDeviceId))"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $device = Invoke-RestMethod -Uri $deviceUrl -TimeoutSec 3
            $latest = Invoke-RestMethod -Uri "$deviceUrl/latest" -TimeoutSec 3
            $received = [DateTimeOffset]::Parse($latest.received_at, $culture, $styles)
            if ($device.online -eq $true -and $received -ge $StartedAt) { return $true }
        } catch {}
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Invoke-StartMode {
    $settings = Assert-LocalRuntimeConfig
    Assert-DockerReady
    $baseUrl = Resolve-ApiBaseUrl -Settings $settings
    $targetDeviceId = Resolve-ProjectDeviceId -Settings $settings
    $startedAt = [DateTimeOffset]::UtcNow
    Write-Step 'Khoi dong Mosquitto, edge API va dashboard'
    & docker compose --env-file $envFile -f $composeFile --profile full up -d --build
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose khoi dong that bai.' }
    Wait-EdgeHealthy -BaseUrl $baseUrl
    Write-Host '[OK] Edge API healthy.' -ForegroundColor Green
    Write-Step 'Kiem tra telemetry moi (khong dung bootstrap secrets.h lam gate)'
    if (Wait-NewTelemetry -BaseUrl $baseUrl -TargetDeviceId $targetDeviceId -StartedAt $startedAt) {
        Write-Host '[OK] Da nhan telemetry moi tu node.' -ForegroundColor Green
    } else {
        Write-Warning 'Stack da chay nhung chua thay telemetry moi; node co the dang offline hoac dang tu phuc hoi mang.'
    }
    if (-not $NoOpenBrowser) { Start-Process $baseUrl }
}

function Test-HostSyntax {
    param([string]$HostName)
    if ([string]::IsNullOrWhiteSpace($HostName) -or $HostName.Length -gt 253 -or $HostName -match '://|/|\s') { return $false }
    if ($HostName -ieq 'localhost') { return $false }
    $address = $null
    if ([Net.IPAddress]::TryParse($HostName, [ref]$address)) {
        if ($address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { return $false }
        $bytes = $address.GetAddressBytes()
        return -not ([Net.IPAddress]::IsLoopback($address) -or $bytes[0] -eq 0 -or $bytes[0] -ge 224 -or $bytes[3] -eq 0 -or $bytes[3] -eq 255)
    }
    return $HostName -match '^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$'
}

function Get-BootstrapValue {
    param([string]$Name, [string]$Text)
    $quote = [char]34
    $match = [regex]::Match($Text, '(?m)^\s*#define\s+' + [regex]::Escape($Name) + '\s+' + $quote + '([^' + $quote + ']*)' + $quote)
    if (-not $match.Success) { return $null }
    return $match.Groups[1].Value
}

function Assert-BootstrapConfig {
    Assert-NonEmptyFile -Path $bootstrapHeader -Label 'firmware bootstrap secrets.h'
    $text = [IO.File]::ReadAllText($bootstrapHeader)
    foreach ($name in @('WIFI_SSID', 'WIFI_PASSWORD', 'DEVICE_ID', 'MQTT_HOST', 'MQTT_USERNAME', 'MQTT_PASSWORD')) {
        $value = Get-BootstrapValue -Name $name -Text $text
        if ([string]::IsNullOrWhiteSpace($value) -or $value -match 'your-|replace-|placeholder') { throw "Bootstrap $name trong secrets.h chua hop le." }
    }
    if (-not (Test-HostSyntax -HostName (Get-BootstrapValue -Name 'MQTT_HOST' -Text $text))) {
        throw 'MQTT_HOST bootstrap phai la hostname/IPv4 hop le, khong phai URL, loopback, multicast hoac broadcast.'
    }
    $portMatch = [regex]::Match($text, '(?m)^\s*#define\s+MQTT_PORT\s+(\d+)\s*$')
    if (-not $portMatch.Success -or [int]$portMatch.Groups[1].Value -lt 1 -or [int]$portMatch.Groups[1].Value -gt 65535) {
        throw 'MQTT_PORT bootstrap phai nam trong khoang 1..65535.'
    }
}

function New-PortalSecret {
    $alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
    $rng = New-Object Security.Cryptography.RNGCryptoServiceProvider
    try {
        $chars = New-Object char[] 20
        $buffer = New-Object byte[] 1
        for ($index = 0; $index -lt $chars.Length; $index++) {
            do { $rng.GetBytes($buffer) } while ($buffer[0] -ge (256 - (256 % $alphabet.Length)))
            $chars[$index] = $alphabet[$buffer[0] % $alphabet.Length]
        }
        return (-join $chars)
    } finally { $rng.Dispose() }
}

function Protect-PortalSecret {
    param([string]$PlainText)
    New-Item -ItemType Directory -Path $generatedDir -Force | Out-Null
    $secure = ConvertTo-SecureString -String $PlainText -AsPlainText -Force
    [IO.File]::WriteAllText($portalSecretFile, (ConvertFrom-SecureString -SecureString $secure), $utf8NoBom)
}

function Unprotect-PortalSecret {
    Assert-NonEmptyFile -Path $portalSecretFile -Label 'portal access DPAPI'
    $secure = ConvertTo-SecureString -String ([IO.File]::ReadAllText($portalSecretFile))
    $pointer = [IntPtr]::Zero
    try {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        if ($pointer -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    }
}

function Ensure-PortalSecret {
    if (Test-Path -LiteralPath $portalSecretFile) { $plainText = Unprotect-PortalSecret } else { $plainText = New-PortalSecret; Protect-PortalSecret -PlainText $plainText }
    try {
        $header = "#pragma once`r`n`r`n// Generated locally by the Flash launcher mode; never commit this file.`r`n#define PROVISIONING_AP_PASSWORD `"$plainText`"`r`n"
        [IO.File]::WriteAllText($portalHeader, $header, $utf8NoBom)
    } finally { $plainText = $null }
}

function Find-PlatformIo {
    foreach ($candidate in @((Join-Path $root '.platformio-venv\Scripts\pio.exe'), (Join-Path $root '.venv\Scripts\pio.exe'))) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    foreach ($name in @('pio.exe', 'platformio.exe')) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) { return $command.Source }
    }
    throw 'Khong tim thay PlatformIO. PlatformIO chi bat buoc trong mode Flash.'
}

function Find-Ch340Port {
    if (-not [string]::IsNullOrWhiteSpace($Port)) { return $Port }
    $numbers = New-Object 'System.Collections.Generic.List[int]'
    foreach ($device in @(Get-PnpDevice -Class Ports -PresentOnly -ErrorAction Stop)) {
        if ($device.FriendlyName -match 'CH340' -or $device.InstanceId -match 'VID_1A86.PID_7523') {
            $match = [regex]::Match($device.FriendlyName, 'COM(\d+)')
            if ($match.Success) { $numbers.Add([int]$match.Groups[1].Value) }
        }
    }
    if ($numbers.Count -eq 0) { throw 'Khong tim thay NodeMCU CH340. Dung -Port COMx neu adapter co ten khac.' }
    $items = $numbers.ToArray(); [array]::Sort($items); return "COM$($items[0])"
}

function Invoke-FlashMode {
    Assert-BootstrapConfig
    Ensure-PortalSecret
    $pio = Find-PlatformIo
    $serialPort = Find-Ch340Port
    Write-Step "Nap firmware qua $serialPort"
    # Intentionally only the application image target. Never add erase or filesystem targets here.
    & $pio run -d $firmwareDir --target upload --upload-port $serialPort
    if ($LASTEXITCODE -ne 0) { throw "Khong nap duoc firmware qua $serialPort." }
    Write-Host '[OK] Da nap firmware; LittleFS khong bi erase.' -ForegroundColor Green
}

function Invoke-VerifyMode {
    Assert-NonEmptyFile -Path $verifyScript -Label 'VERIFY-MVP.ps1'
    Write-Step 'Chay verify khong can COM/USB'
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File $verifyScript -IncludeFirmware
    if ($LASTEXITCODE -ne 0) { throw 'Verify that bai.' }
}

function Invoke-DoctorMode {
    $settings = Assert-LocalRuntimeConfig
    Assert-DockerReady
    $hostName = if ($settings.ContainsKey('MQTT_HOST')) { $settings.MQTT_HOST } else { '127.0.0.1' }
    $mqttPort = if ($settings.ContainsKey('MQTT_PORT')) { [int]$settings.MQTT_PORT } else { 1883 }
    $targetDeviceId = Resolve-ProjectDeviceId -Settings $settings
    if ([string]::IsNullOrWhiteSpace($hostName) -or $hostName -match '://|/|\s') { throw 'MQTT_HOST trong .env sai syntax.' }
    if ($mqttPort -lt 1 -or $mqttPort -gt 65535) { throw 'MQTT_PORT trong .env phai nam trong khoang 1..65535.' }
    if (-not $settings.ContainsKey('MQTT_USERNAME') -or [string]::IsNullOrWhiteSpace($settings.MQTT_USERNAME)) { throw 'MQTT_USERNAME trong .env chua duoc cau hinh.' }
    Write-Step 'Kiem tra DNS tren Windows'
    $addresses = @(); $parsedAddress = $null
    if ([Net.IPAddress]::TryParse($hostName, [ref]$parsedAddress)) { $addresses = @($parsedAddress.IPAddressToString) } else {
        $addresses = @([Net.Dns]::GetHostAddresses($hostName) | Where-Object AddressFamily -eq ([Net.Sockets.AddressFamily]::InterNetwork) | ForEach-Object IPAddressToString)
    }
    if ($addresses.Count -eq 0) { throw 'Windows khong phan giai duoc MQTT_HOST sang IPv4.' }
    Write-Host '[OK] Windows resolve duoc broker. Day khong chung minh ESP8266 resolve duoc hostname.' -ForegroundColor Green
    Write-Step "Kiem tra TCP $mqttPort"
    $client = New-Object Net.Sockets.TcpClient
    try {
        $pending = $client.BeginConnect($hostName, $mqttPort, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne(2000) -or -not $client.Connected) { throw 'TCP timeout.' }
        $client.EndConnect($pending)
    } finally { $client.Dispose() }
    Write-Host '[OK] TCP broker co the truy cap.' -ForegroundColor Green
    Write-Step 'Kiem tra MQTT authentication va ACL edge'
    Assert-NonEmptyFile -Path $python -Label 'Python .venv'
    Assert-NonEmptyFile -Path $mqttDoctorScript -Label 'MQTT doctor helper'
    $previousPassword = $env:IOT_HEALTH_DOCTOR_MQTT_PASSWORD
    try {
        $env:IOT_HEALTH_DOCTOR_MQTT_PASSWORD = $settings.MQTT_PASSWORD
        & $python $mqttDoctorScript --host $hostName --port $mqttPort --username $settings.MQTT_USERNAME --device-id $targetDeviceId
        if ($LASTEXITCODE -ne 0) { throw 'MQTT authentication/ACL probe that bai.' }
    } finally { $env:IOT_HEALTH_DOCTOR_MQTT_PASSWORD = $previousPassword }
    Write-Host '[OK] Doctor hoan tat; khong in credential.' -ForegroundColor Green
}

function Wait-LiveCommandHeartbeat {
    param(
        [string]$BaseUrl,
        [string]$TargetDeviceId,
        [int]$TimeoutSeconds = 20
    )
    $culture = [Globalization.CultureInfo]::InvariantCulture
    $styles = [Globalization.DateTimeStyles]([int][Globalization.DateTimeStyles]::AssumeUniversal -bor [int][Globalization.DateTimeStyles]::AdjustToUniversal)
    $deviceUrl = "$BaseUrl/api/v1/devices/$([uri]::EscapeDataString($TargetDeviceId))"
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $device = Invoke-RestMethod -Uri $deviceUrl -TimeoutSec 3
            if ($device.online -ne $true) {
                throw 'Node dang offline; MQTT command khong the mo portal.'
            }
            if ($device.last_status_reason -eq 'heartbeat' -and
                $device.last_status_retained -eq $false -and
                -not [string]::IsNullOrWhiteSpace($device.command_session_id) -and
                -not [string]::IsNullOrWhiteSpace($device.last_status_at)) {
                $received = [DateTimeOffset]::Parse($device.last_status_at, $culture, $styles)
                $ageSeconds = ([DateTimeOffset]::UtcNow - $received).TotalSeconds
                if ($ageSeconds -ge 0 -and $ageSeconds -le 10) {
                    return
                }
            }
        }
        catch {
            if ($_.Exception.Message -like 'Node dang offline*') { throw }
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw 'Khong nhan duoc heartbeat MQTT truc tiep, non-retained va con moi trong thoi gian cho.'
}

function Invoke-OpenPortalMode {
    $settings = Assert-LocalRuntimeConfig
    $baseUrl = Resolve-ApiBaseUrl -Settings $settings
    $targetDeviceId = Resolve-ProjectDeviceId -Settings $settings
    $escapedDeviceId = [uri]::EscapeDataString($targetDeviceId)
    # The nonce belongs to the current node boot and is stored by edge from a
    # live, non-retained status. Edge rejects missing or stale node sessions.
    $body = @{} | ConvertTo-Json -Compress
    $commandUrl = "$baseUrl/api/v1/devices/$escapedDeviceId/commands/open-provisioning"
    Write-Step 'Cho heartbeat MQTT truc tiep, non-retained va command session hien tai'
    Wait-LiveCommandHeartbeat -BaseUrl $baseUrl -TargetDeviceId $targetDeviceId
    Write-Step 'Yeu cau edge xac nhan node online bang du lieu song va gui lenh khong-retain'
    try {
        $webResponse = Invoke-WebRequest -UseBasicParsing -Method Post -Uri $commandUrl -ContentType 'application/json' -Body $body -TimeoutSec 10
        if ([int]$webResponse.StatusCode -ne 202) { throw "Edge tra ve HTTP $($webResponse.StatusCode), can HTTP 202." }
        $response = $webResponse.Content | ConvertFrom-Json
    } catch {
        throw "Khong mo duoc portal: edge tu choi, node offline/heartbeat cu, hoac API khong san sang. $($_.Exception.Message)"
    }
    if ([string]::IsNullOrWhiteSpace($response.command_id) -or [string]::IsNullOrWhiteSpace($response.command_session_id) -or [int]$response.qos -ne 1 -or $response.retain -ne $false) {
        throw 'Edge tra ve command receipt khong dung contract QoS 1/retain=false/session correlation.'
    }
    $deadline = (Get-Date).AddSeconds(35)
    $deviceUrl = "$baseUrl/api/v1/devices/$escapedDeviceId"
    do {
        try {
            $device = Invoke-RestMethod -Uri $deviceUrl -TimeoutSec 3
            if ($device.status_reason -eq 'provisioning_started' -and $device.correlation_id -eq $response.command_id) {
                Write-Host '[OK] Node da xac nhan portal provisioning_started dung correlation ID.' -ForegroundColor Green
                return
            }
        } catch {}
        Start-Sleep -Milliseconds 750
    } while ((Get-Date) -lt $deadline)
    throw 'Da gui command nhung khong nhan execution receipt provisioning_started dung correlation ID; khong coi day la thanh cong.'
}

function Invoke-ShowPortalAccessMode {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $secret = Unprotect-PortalSecret
    try {
        $form = New-Object Windows.Forms.Form
        $form.Text = 'IoT Health Edge - Portal access'; $form.Width = 520; $form.Height = 205; $form.StartPosition = 'CenterScreen'; $form.FormBorderStyle = 'FixedDialog'; $form.MaximizeBox = $false
        $label = New-Object Windows.Forms.Label
        $label.Text = 'Mat khau AP provisioning (chi hien thi cuc bo):'; $label.AutoSize = $true; $label.Left = 18; $label.Top = 20; $form.Controls.Add($label)
        $box = New-Object Windows.Forms.TextBox
        $box.Text = $secret; $box.ReadOnly = $true; $box.UseSystemPasswordChar = $true; $box.Left = 18; $box.Top = 48; $box.Width = 466; $form.Controls.Add($box)
        $show = New-Object Windows.Forms.CheckBox
        $show.Text = 'Hien mat khau'; $show.Left = 18; $show.Top = 82; $show.Width = 140; $show.Add_CheckedChanged({ $box.UseSystemPasswordChar = -not $show.Checked }); $form.Controls.Add($show)
        $copy = New-Object Windows.Forms.Button
        $copy.Text = 'Sao chep'; $copy.Left = 300; $copy.Top = 110; $copy.Width = 88; $copy.Add_Click({ [Windows.Forms.Clipboard]::SetText($box.Text) }); $form.Controls.Add($copy)
        $close = New-Object Windows.Forms.Button
        $close.Text = 'Dong'; $close.Left = 396; $close.Top = 110; $close.Width = 88; $close.Add_Click({ $form.Close() }); $form.Controls.Add($close); $form.AcceptButton = $close
        [void]$form.ShowDialog()
    } finally { $secret = $null }
}

try {
    Push-Location $root
    switch ($Mode) {
        'Start' { Invoke-StartMode }
        'Doctor' { Invoke-DoctorMode }
        'Verify' { Invoke-VerifyMode }
        'Flash' { Invoke-FlashMode }
        'OpenPortal' { Invoke-OpenPortalMode }
        'ShowPortalAccess' { Invoke-ShowPortalAccessMode }
    }
    exit 0
} catch {
    Write-Error $_.Exception.Message
    exit 1
} finally {
    Pop-Location -ErrorAction SilentlyContinue
    if (-not $NoPause -and $Host.Name -eq 'ConsoleHost') { Write-Host ''; Write-Host 'Nhan Enter de dong...'; [void][Console]::ReadLine() }
}
