[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')]
    [string]$EdgeUsername = 'health_edge',

    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')]
    [string]$DeviceUsername = 'health_node',

    [ValidatePattern('^[a-z0-9][a-z0-9-]{0,31}$')]
    [string]$DeviceId = 'health-node-01',

    [string]$Image = 'eclipse-mosquitto:2.0.22',

    [switch]$AclOnly,

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
$backupAclFile = Join-Path $generatedDir 'acl.rollback'
$discardedAclFile = Join-Path $generatedDir 'acl.discarded'
$probePasswordFile = Join-Path $generatedDir 'passwords.probe'
$aclTemplate = Join-Path $mosquittoDir 'acl.template'
$mosquittoConfig = Join-Path $mosquittoDir 'mosquitto.conf'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

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

function Get-RunningComposeServices {
    $services = @(& docker compose -f $composeFile ps --status running --services)
    if ($LASTEXITCODE -ne 0) {
        throw 'Khong kiem tra duoc trang thai Docker Compose.'
    }
    return $services
}

function Write-AclCandidate {
    $acl = Get-Content -Raw -LiteralPath $aclTemplate
    $acl = $acl.Replace('__EDGE_USERNAME__', $EdgeUsername)
    $acl = $acl.Replace('__DEVICE_USERNAME__', $DeviceUsername)
    $acl = $acl.Replace('__DEVICE_ID__', $DeviceId)

    if ($acl -match '__[A-Z0-9_]+__') {
        throw 'ACL con placeholder chua duoc thay the.'
    }
    $requiredRules = @(
        "user $EdgeUsername",
        'topic read iot-health/v1/devices/+/telemetry',
        'topic read iot-health/v1/devices/+/event',
        'topic read iot-health/v1/devices/+/status',
        'topic write iot-health/v1/devices/+/command/+',
        "user $DeviceUsername",
        "topic write iot-health/v1/devices/$DeviceId/telemetry",
        "topic write iot-health/v1/devices/$DeviceId/event",
        "topic write iot-health/v1/devices/$DeviceId/status",
        "topic read iot-health/v1/devices/$DeviceId/command/+"
    )
    foreach ($rule in $requiredRules) {
        if (-not $acl.Contains($rule)) {
            throw "ACL thieu rule bat buoc: $rule"
        }
    }
    [System.IO.File]::WriteAllText($stagedAclFile, $acl, $utf8NoBom)
}

function Set-GeneratedFilePermissions {
    param([string[]]$Names)

    $quotedNames = ($Names | ForEach-Object { "/work/$_" }) -join ' '
    $permissionCommand = "chown mosquitto:mosquitto $quotedNames && chmod 0600 $quotedNames"
    & docker run --rm --mount "type=bind,source=$generatedPath,target=/work" `
        --entrypoint sh $Image -c $permissionCommand
    if ($LASTEXITCODE -ne 0) {
        throw 'Khong dat duoc quyen doc an toan cho tep Mosquitto.'
    }
}

function Test-EdgeRuntimeReady {
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/healthz' `
                -Method Get -TimeoutSec 2
            if ($health.mqtt.connected -eq $true -and $health.mqtt.subscribed -eq $true) {
                return $true
            }
        }
        catch {
            # Broker and edge need a short bounded interval to reconnect.
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Test-CommandAclPermissions {
    $runningServices = Get-RunningComposeServices
    if ($runningServices -notcontains 'edge') {
        throw 'ACL-only can chay edge profile de probe SUBACK/quyen ma khong doc plaintext credential.'
    }

    $edgeContainerId = [string](& docker compose -f $composeFile ps -q edge)
    $edgeContainerId = $edgeContainerId.Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($edgeContainerId)) {
        throw 'Khong tim thay edge container de probe ACL.'
    }
    $networkJson = & docker inspect --format '{{json .NetworkSettings.Networks}}' $edgeContainerId
    if ($LASTEXITCODE -ne 0) {
        throw 'Khong doc duoc Docker network cua edge.'
    }
    $networkObject = $networkJson | ConvertFrom-Json
    $networkName = ($networkObject.PSObject.Properties | Select-Object -First 1).Name
    if ([string]::IsNullOrWhiteSpace($networkName)) {
        throw 'Edge container khong co Docker network de probe ACL.'
    }

    # Duplicate the existing edge hash under the device username in a temporary
    # probe-only password file. The real password file and its hashes are never
    # changed, and the plaintext remains inside the already-running edge container.
    $passwordLines = [System.IO.File]::ReadAllLines($passwordFile)
    $edgeHashLine = $passwordLines | Where-Object {
        $separator = $_.IndexOf(':')
        $separator -gt 0 -and $_.Substring(0, $separator) -ceq $EdgeUsername
    } | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($edgeHashLine) -or $edgeHashLine.IndexOf(':') -lt 1) {
        throw "Khong tim thay hash cua edge user '$EdgeUsername'."
    }
    $hashSuffix = $edgeHashLine.Substring($edgeHashLine.IndexOf(':'))
    [System.IO.File]::WriteAllLines(
        $probePasswordFile,
        [string[]]@($edgeHashLine, "$DeviceUsername$hashSuffix"),
        $utf8NoBom
    )
    Set-GeneratedFilePermissions -Names @('passwords.probe', 'acl.next')

    $probeName = 'iot-health-acl-probe-' + [Guid]::NewGuid().ToString('N').Substring(0, 12)
    $configPath = (Resolve-Path -LiteralPath $mosquittoConfig).Path
    $candidateAclPath = (Resolve-Path -LiteralPath $stagedAclFile).Path
    $probePasswordPath = (Resolve-Path -LiteralPath $probePasswordFile).Path
    try {
        $startArgs = @(
            'run', '--rm', '-d', '--name', $probeName,
            '--network', $networkName,
            '--tmpfs', '/mosquitto/data:size=16m,mode=0700',
            '--mount', "type=bind,source=$configPath,target=/mosquitto/config/mosquitto.conf,readonly",
            '--mount', "type=bind,source=$candidateAclPath,target=/mosquitto/config/generated/acl,readonly",
            '--mount', "type=bind,source=$probePasswordPath,target=/mosquitto/config/generated/passwords,readonly",
            $Image
        )
        if ((Invoke-DockerQuiet -Arguments $startArgs) -ne 0) {
            throw 'Mosquitto tu choi config/ACL candidate.'
        }

        $started = $false
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            if ((Invoke-DockerQuiet -Arguments @('inspect', $probeName)) -eq 0) {
                $started = $true
                break
            }
            Start-Sleep -Milliseconds 250
        }
        if (-not $started) {
            throw 'Broker probe khong khoi dong trong thoi gian cho.'
        }

        $probeCode = @'
import os
import sys
import threading
import time
import uuid
from paho.mqtt import client as mqtt

host, edge_user, node_user, device_id = sys.argv[1:]
password = os.environ.get("MQTT_PASSWORD")
if not password:
    raise SystemExit("edge container has no MQTT_PASSWORD")

def connect(username):
    ready = threading.Event()
    result = {"ok": False}
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="acl-probe-" + uuid.uuid4().hex,
        protocol=mqtt.MQTTv5,
    )
    client.username_pw_set(username, password)
    def on_connect(_client, _userdata, _flags, reason_code, _properties):
        result["ok"] = not reason_code.is_failure
        ready.set()
    client.on_connect = on_connect
    deadline = time.monotonic() + 4
    while True:
        try:
            client.connect(host, 1883, 5)
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise SystemExit("ACL probe broker was not reachable")
            time.sleep(0.1)
    client.loop_start()
    if not ready.wait(4) or not result["ok"]:
        client.loop_stop()
        raise SystemExit("ACL probe authentication failed for " + username)
    return client

def subscribe_codes(client, topic):
    done = threading.Event()
    result = {"codes": None}
    def on_subscribe(_client, _userdata, _mid, reason_codes, _properties):
        result["codes"] = list(reason_codes)
        done.set()
    client.on_subscribe = on_subscribe
    rc, _mid = client.subscribe(topic, qos=1)
    if rc != mqtt.MQTT_ERR_SUCCESS or not done.wait(4):
        raise SystemExit("ACL probe SUBACK timeout")
    return result["codes"]

def is_failure(code):
    return bool(getattr(code, "is_failure", False)) or (
        isinstance(code, int) and code >= 128
    )

edge = connect(edge_user)
node = None
try:
    node = connect(node_user)
    allowed = subscribe_codes(node, f"iot-health/v1/devices/{device_id}/command/+")
    if not allowed or any(is_failure(code) for code in allowed):
        raise SystemExit("node command subscription was denied")
    denied = subscribe_codes(node, "iot-health/v1/devices/acl-cross-device/command/+")
    if not denied or not all(is_failure(code) for code in denied):
        raise SystemExit("cross-device command subscription was not denied")

    expected_topic = f"iot-health/v1/devices/{device_id}/command/acl-probe"
    expected_payload = ("acl-probe:" + uuid.uuid4().hex).encode("ascii")
    delivered = threading.Event()
    received = {"topic": None, "payload": None}
    def on_message(_client, _userdata, message):
        received["topic"] = message.topic
        received["payload"] = bytes(message.payload)
        delivered.set()
    node.on_message = on_message

    info = edge.publish(
        expected_topic,
        expected_payload,
        qos=1,
        retain=False,
    )
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        raise SystemExit("edge command publish was rejected")
    info.wait_for_publish(timeout=4)
    if not info.is_published():
        raise SystemExit("edge command publish PUBACK timeout")
    if not delivered.wait(4):
        raise SystemExit("node did not receive edge command probe")
    if received != {"topic": expected_topic, "payload": expected_payload}:
        raise SystemExit("node received a mismatched command probe")
finally:
    for client in (node, edge):
        if client is not None:
            client.disconnect()
            client.loop_stop()
'@
        & docker compose -f $composeFile exec -T edge python -c $probeCode `
            $probeName $EdgeUsername $DeviceUsername $DeviceId
        if ($LASTEXITCODE -ne 0) {
            throw 'Command ACL read/write probe that bai.'
        }
    }
    finally {
        Invoke-DockerQuiet -Arguments @('rm', '-f', $probeName) | Out-Null
        Remove-Item -LiteralPath $probePasswordFile -Force -ErrorAction SilentlyContinue
    }
}

if ($AclOnly -and $Force) {
    throw 'Khong duoc ket hop -AclOnly va -Force.'
}
if ($EdgeUsername -ceq $DeviceUsername) {
    throw 'Edge va node phai dung hai username khac nhau.'
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Khong tim thay Docker CLI. Hay khoi dong Docker Desktop roi chay lai.'
}
if ((Invoke-DockerQuiet -Arguments @('info')) -ne 0) {
    throw 'Docker Desktop chua san sang. Hay khoi dong Docker Desktop, doi engine Running roi chay lai.'
}
if (-not (Test-Path -LiteralPath $aclTemplate)) {
    throw "Khong tim thay ACL template: $aclTemplate"
}
if ($AclOnly) {
    if (-not (Test-Path -LiteralPath $passwordFile)) {
        throw 'ACL-only yeu cau password file hien co; script se khong tao lai credential.'
    }
    if (-not (Test-Path -LiteralPath $aclFile)) {
        throw 'ACL-only yeu cau ACL hien co de co the rollback.'
    }
    $runningServices = Get-RunningComposeServices
    if ($runningServices -notcontains 'mosquitto') {
        throw 'ACL-only yeu cau Mosquitto dang chay de restart va xac minh rollback.'
    }
}
elseif ((Test-Path -LiteralPath $passwordFile) -and -not $Force) {
    throw "Tep mat khau da ton tai: $passwordFile. Dung -AclOnly de cap nhat ACL an toan, hoac -Force neu chu y xoay credential."
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

if ($AclOnly) {
    $passwordHashBefore = (Get-FileHash -Algorithm SHA256 -LiteralPath $passwordFile).Hash
    try {
        Remove-Item -LiteralPath $stagedAclFile, $backupAclFile, $discardedAclFile, `
            $probePasswordFile -Force -ErrorAction SilentlyContinue
        Write-AclCandidate
        Test-CommandAclPermissions

        [System.IO.File]::Replace($stagedAclFile, $aclFile, $backupAclFile, $true)
        try {
            & docker compose -f $composeFile restart mosquitto
            if ($LASTEXITCODE -ne 0 -or -not (Test-EdgeRuntimeReady)) {
                throw 'Broker/Edge khong vuot qua probe SUBACK sau khi kich hoat ACL.'
            }
            $passwordHashAfter = (Get-FileHash -Algorithm SHA256 -LiteralPath $passwordFile).Hash
            if ($passwordHashBefore -cne $passwordHashAfter) {
                throw 'Password hash da thay doi bat ngo trong ACL-only migration.'
            }
        }
        catch {
            if (Test-Path -LiteralPath $backupAclFile) {
                [System.IO.File]::Replace(
                    $backupAclFile,
                    $aclFile,
                    $discardedAclFile,
                    $true
                )
                & docker compose -f $composeFile restart mosquitto
            }
            throw
        }
    }
    finally {
        Remove-Item -LiteralPath $stagedAclFile, $backupAclFile, $discardedAclFile, `
            $probePasswordFile -Force -ErrorAction SilentlyContinue
    }
    Write-Host 'Da cap nhat ACL command theo transaction; password hash duoc giu nguyen.'
    exit 0
}

try {
    Remove-Item -LiteralPath $stagedPasswordFile, $stagedAclFile -Force `
        -ErrorAction SilentlyContinue

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

    Write-AclCandidate
    Move-Item -LiteralPath $stagedPasswordFile -Destination $passwordFile -Force
    Move-Item -LiteralPath $stagedAclFile -Destination $aclFile -Force
    Set-GeneratedFilePermissions -Names @('passwords', 'acl')
}
finally {
    Remove-Item -LiteralPath $stagedPasswordFile, $stagedAclFile -Force `
        -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host 'Da tao password hash va ACL trong deploy/mosquitto/generated/.'
Write-Host 'Thu muc nay bi .gitignore loai tru; khong commit, gui hoac chup man hinh mat khau.'
Write-Host "Edge MQTT username: $EdgeUsername"
Write-Host "Node/simulator MQTT username: $DeviceUsername"
Write-Host "Device ID duoc phep: $DeviceId"

$runningServices = Get-RunningComposeServices
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
