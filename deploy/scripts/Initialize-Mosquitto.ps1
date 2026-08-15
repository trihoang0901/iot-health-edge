[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')]
    [string]$EdgeUsername = 'health_edge',

    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')]
    [string]$DeviceUsername = 'health_node',

    [ValidatePattern('^[a-z0-9][a-z0-9-]{0,31}$')]
    [string]$DeviceId = 'health-node-01',

    [string]$Image = 'eclipse-mosquitto:2.0.22',

    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$deployDir = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $deployDir 'docker-compose.yml'
$mosquittoDir = Join-Path $deployDir 'mosquitto'
$generatedDir = Join-Path $mosquittoDir 'generated'
$passwordFile = Join-Path $generatedDir 'passwords'
$aclFile = Join-Path $generatedDir 'acl'
$stagedPasswordFile = Join-Path $generatedDir 'passwords.next'
$stagedAclFile = Join-Path $generatedDir 'acl.next'
$aclTemplate = Join-Path $mosquittoDir 'acl.template'

function Invoke-DockerQuiet {
    param([string[]]$Arguments)

    $previousPreference = $ErrorActionPreference
    try {
        # Windows PowerShell converts redirected native stderr into ErrorRecord.
        # Continue here so the caller can handle the native exit code explicitly.
        $ErrorActionPreference = 'Continue'
        & docker @Arguments *> $null
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
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

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Khong tim thay Docker CLI. Hay khoi dong Docker Desktop roi chay lai.'
}

if ((Invoke-DockerQuiet -Arguments @('info')) -ne 0) {
    throw 'Docker Desktop chua san sang. Hay khoi dong Docker Desktop, doi engine Running roi chay lai.'
}

if ((Test-Path -LiteralPath $passwordFile) -and -not $Force) {
    throw "Tep mat khau da ton tai: $passwordFile. Dung -Force neu ban chu y muon tao lai."
}

if (-not (Test-Path -LiteralPath $aclTemplate)) {
    throw "Khong tim thay ACL template: $aclTemplate"
}

New-Item -ItemType Directory -Path $generatedDir -Force | Out-Null
$generatedPath = (Resolve-Path -LiteralPath $generatedDir).Path

Write-Host "Dang chuan bi image $Image ..."
if ((Invoke-DockerQuiet -Arguments @('image', 'inspect', $Image)) -ne 0) {
    & docker pull $Image
    if ($LASTEXITCODE -ne 0) {
        throw "Khong the tai image $Image."
    }
}

try {
    Remove-Item -LiteralPath $stagedPasswordFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stagedAclFile -Force -ErrorAction SilentlyContinue

    Write-Host "Nhap mat khau rieng cho tai khoan edge '$EdgeUsername'."
    Write-Host 'Mat khau duoc nhap truc tiep vao mosquitto_passwd, script khong doc hoac ghi plaintext.'
    & docker run --rm -it --mount "type=bind,source=$generatedPath,target=/work" $Image `
        mosquitto_passwd -c /work/passwords.next $EdgeUsername
    if ($LASTEXITCODE -ne 0) {
        throw 'Khong tao duoc tai khoan edge.'
    }

    Write-Host "Nhap mot mat khau KHAC cho tai khoan node/simulator '$DeviceUsername'."
    & docker run --rm -it --mount "type=bind,source=$generatedPath,target=/work" $Image `
        mosquitto_passwd /work/passwords.next $DeviceUsername
    if ($LASTEXITCODE -ne 0) {
        throw 'Khong tao duoc tai khoan node/simulator.'
    }

    $acl = Get-Content -Raw -LiteralPath $aclTemplate
    $acl = $acl.Replace('__EDGE_USERNAME__', $EdgeUsername)
    $acl = $acl.Replace('__DEVICE_USERNAME__', $DeviceUsername)
    $acl = $acl.Replace('__DEVICE_ID__', $DeviceId)
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($stagedAclFile, $acl, $utf8NoBom)

    Move-Item -LiteralPath $stagedPasswordFile -Destination $passwordFile -Force
    Move-Item -LiteralPath $stagedAclFile -Destination $aclFile -Force

    # mosquitto_passwd creates a root-owned 0600 file. The broker runs as the
    # image's `mosquitto` user, so normalize both ownership and permissions
    # without exposing plaintext credentials to PowerShell or command history.
    & docker run --rm --mount "type=bind,source=$generatedPath,target=/work" `
        --entrypoint sh $Image -c `
        'chown mosquitto:mosquitto /work/passwords /work/acl && chmod 0600 /work/passwords /work/acl'
    if ($LASTEXITCODE -ne 0) {
        throw 'Khong dat duoc quyen doc an toan cho password/ACL.'
    }
}
finally {
    Remove-Item -LiteralPath $stagedPasswordFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stagedAclFile -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host 'Da tao password hash va ACL trong deploy/mosquitto/generated/.'
Write-Host 'Thu muc nay bi .gitignore loai tru; khong commit, gui hoac chup man hinh mat khau.'
Write-Host "Edge MQTT username: $EdgeUsername"
Write-Host "Node/simulator MQTT username: $DeviceUsername"
Write-Host "Device ID duoc phep: $DeviceId"

$runningServices = @(& docker compose -f $composeFile ps --status running --services)
if ($LASTEXITCODE -ne 0) {
    throw 'Khong kiem tra duoc trang thai Docker Compose sau khi tao credential.'
}
if ($runningServices -contains 'mosquitto') {
    Write-Host 'Mosquitto dang chay; khoi dong lai de nap password va ACL moi.'
    & docker compose -f $composeFile restart mosquitto
    if ($LASTEXITCODE -ne 0) {
        throw 'Credential da duoc kich hoat tren dia nhung Mosquitto restart that bai.'
    }
    Write-Host 'Hay cap nhat MQTT_PASSWORD cua edge/firmware roi khoi dong lai cac client.'
}
else {
    Write-Host 'Buoc tiep theo: docker compose -f deploy/docker-compose.yml up -d'
}
}
finally {
    if ($credentialMutexAcquired) {
        $credentialMutex.ReleaseMutex()
    }
    $credentialMutex.Dispose()
}
