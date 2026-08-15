import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "START-IOT-HEALTH-EDGE.bat"
AUTH_PROBE_SCRIPT = ROOT / "deploy" / "scripts" / "Test-NodeMqttCredential.ps1"


def test_post_upload_gate_is_fresh_v4_node_specific_and_locale_independent():
    source = LAUNCHER.read_text(encoding="utf-8")

    assert "[Globalization.CultureInfo]::InvariantCulture" in source
    assert "[Globalization.DateTimeStyles]::AssumeUniversal" in source
    assert "[Globalization.DateTimeStyles]::AdjustToUniversal" in source
    assert "Parse($env:UPLOAD_STARTED_UTC,$culture,$styles)" in source
    assert "Parse($latest.received_at,$culture,$styles)" in source
    assert "$device.online -eq $true" in source
    assert "$received -ge $started" in source
    assert "$schema -eq 'health.telemetry.v4'" in source
    assert "$latest.system.fw -eq '0.4.0'" in source
    post_upload_gate = source.split("Cho telemetry moi tu NodeMCU", 1)[1].split(
        "echo [7/7] Mo dashboard", 1
    )[0]
    assert "set \"FINAL_CODE=1\"" in post_upload_gate
    assert "goto :finish" in post_upload_gate
    assert "set \"NODE_WARN=1\"" not in post_upload_gate


def test_launcher_timestamp_style_keeps_z_and_offset_times_in_utc():
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is required for the launcher timestamp check")

    command = r"""
[Globalization.CultureInfo]::CurrentCulture = [Globalization.CultureInfo]::GetCultureInfo('vi-VN')
$culture = [Globalization.CultureInfo]::InvariantCulture
$styles = [Globalization.DateTimeStyles]([int][Globalization.DateTimeStyles]::AssumeUniversal -bor [int][Globalization.DateTimeStyles]::AdjustToUniversal)
$started = [DateTimeOffset]::Parse('2026-08-12T15:18:08.0000000+00:00', $culture, $styles)
$received = [DateTimeOffset]::Parse('2026-08-12T15:18:09.123Z', $culture, $styles)
if ($started.Offset -ne [TimeSpan]::Zero -or $received.Offset -ne [TimeSpan]::Zero -or $received -lt $started) { exit 1 }
"""
    subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )


def test_launcher_uses_local_python_module_instead_of_copied_pio_executable():
    source = LAUNCHER.read_text(encoding="utf-8")

    assert '.platformio-venv\\Scripts\\python.exe' in source
    assert '-m platformio --version' in source
    assert '"%PIO_PYTHON%" -m platformio run' in source
    assert 'if exist "%ROOT%.platformio-venv\\Scripts\\pio.exe"' not in source


def test_node_mqtt_auth_probe_runs_after_compose_and_before_firmware_upload():
    source = LAUNCHER.read_text(encoding="utf-8")
    probe_source = AUTH_PROBE_SCRIPT.read_text(encoding="utf-8")

    compose_index = source.index("--profile full up -d --build")
    broker_reload_index = source.index("restart mosquitto")
    readiness_index = source.index("Cho edge API san sang cho MQTT auth probe")
    probe_index = source.index("Test-NodeMqttCredential.ps1")
    upload_index = source.index("--target upload")

    assert compose_index < broker_reload_index < readiness_index < probe_index < upload_index
    readiness_source = source[readiness_index:probe_index]
    assert "/healthz" in readiness_source
    assert "$health.database.healthy -eq $true" in readiness_source
    assert "$health.mqtt.connected -eq $true" in readiness_source
    assert "$health.mqtt.subscribed -eq $true" in readiness_source
    assert "$health.ingestion.worker_alive -eq $true" in readiness_source
    assert "$health.status -eq 'ok'" not in readiness_source
    assert "ConvertTo-Json -Compress" in probe_source
    assert "ToBase64String" in probe_source
    assert "device_id =" not in probe_source
    assert "will_set" not in (ROOT / "edge" / "mqtt_auth_probe.py").read_text(
        encoding="utf-8"
    )
    assert "Test-FirmwareWriteAcl" in probe_source
    assert "[switch]$HostBroker" in probe_source
    assert "[switch]$StaticOnly" in probe_source
    assert "127.0.0.1" in probe_source
    assert "iot-health/v1/devices/$DeviceId/telemetry" in probe_source
    assert "iot-health/v1/devices/$DeviceId/event" in probe_source
    assert "iot-health/v1/devices/$DeviceId/status" in probe_source
    assert "$encodedPayload | & docker compose" in probe_source
    assert "python -m edge.mqtt_auth_probe" in probe_source
    assert "--base64" in probe_source
    assert "*> $null" in probe_source
    assert "--password" not in probe_source
    param_block = probe_source.split("param(", 1)[1].split("\n)", 1)[0]
    assert "$PSScriptRoot" not in param_block
    assert "[string]::IsNullOrWhiteSpace($ProjectRoot)" in probe_source
    probe_call = next(
        line for line in source.splitlines() if "Test-NodeMqttCredential.ps1" in line
    )
    assert "-ProjectRoot" not in probe_call
    assert 'if "%NODE_AUTH_RC%"=="16"' in source
    assert "Credential hoac MQTT_USERNAME/DEVICE_ID" in source
    assert "Rotate-LocalNodeMqttCredential.ps1" in source
    assert "SIMULATOR_MQTT_PASSWORD=([^\\r\\n]*)" in source


@pytest.mark.parametrize(
    (
        "firmware_username",
        "firmware_device_id",
        "acl_device_id",
        "extra_acl",
        "expected_exit",
    ),
    [
        ("health_node", "health-node-01", "health-node-01", "", 0),
        ("health_node", "health-node-01", "different-node", "", 16),
        ("health_edge", "health-node-01", "health-node-01", "", 16),
        ("Health_Node", "health-node-01", "health-node-01", "", 16),
        ("health_node", "Health-node-01", "Health-node-01", "", 16),
        (
            "health_node",
            "health-node-01",
            "health-node-01",
            "topic write iot-health/v1/devices/+/status\n",
            16,
        ),
        (
            "health_node",
            "health-node-01",
            "health-node-01",
            "topic write iot-health/v1/devices/health-node-01/status\n",
            16,
        ),
    ],
    ids=(
        "exact-node-acl",
        "wrong-device-acl",
        "read-only-account",
        "username-case-mismatch",
        "uppercase-device-id",
        "extra-wildcard-rule",
        "duplicate-rule",
    ),
)
def test_node_probe_rejects_acl_mismatch_before_live_handshake(
    tmp_path,
    firmware_username,
    firmware_device_id,
    acl_device_id,
    extra_acl,
    expected_exit,
):
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is required for the launcher ACL check")

    secrets = tmp_path / "firmware" / "health-node" / "include" / "secrets.h"
    secrets.parent.mkdir(parents=True)
    secrets.write_text(
        f'#define DEVICE_ID "{firmware_device_id}"\n'
        f'#define MQTT_USERNAME "{firmware_username}"\n'
        '#define MQTT_PASSWORD "dummy-node-password"\n',
        encoding="utf-8",
    )
    generated = tmp_path / "deploy" / "mosquitto" / "generated"
    generated.mkdir(parents=True)
    (generated / "acl").write_text(
        "user health_edge\n"
        "topic read iot-health/v1/devices/+/telemetry\n"
        "user health_node\n"
        f"topic write iot-health/v1/devices/{acl_device_id}/telemetry\n"
        f"topic write iot-health/v1/devices/{acl_device_id}/event\n"
        f"topic write iot-health/v1/devices/{acl_device_id}/status\n"
        f"{extra_acl}",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("DUMMY=true\n", encoding="utf-8")
    (tmp_path / "deploy" / "docker-compose.yml").write_text(
        "services: {}\n", encoding="utf-8"
    )
    mock_bin = tmp_path / "mock-bin"
    mock_bin.mkdir()
    (mock_bin / "docker.cmd").write_text("@echo off\nexit /b 0\n", encoding="ascii")
    environment = os.environ.copy()
    environment["PATH"] = str(mock_bin) + os.pathsep + environment["PATH"]

    completed = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(AUTH_PROBE_SCRIPT),
            "-ProjectRoot",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=10,
    )

    assert completed.returncode == expected_exit
    assert "dummy-node-password" not in completed.stdout + completed.stderr


@pytest.mark.parametrize(
    "credential_defines",
    [
        '#define MQTT_USERNAME "health_node"\n'
        '#define MQTT_USERNAME "health_node"\n'
        '#define MQTT_PASSWORD "dummy-node-password"\n',
        '#define MQTT_USERNAME "health_" "node"\n'
        '#define MQTT_PASSWORD "dummy-node-password"\n',
        '#define MQTT_USERNAME "health_node"\n'
        '#define MQTT_PASSWORD "dummy\\npassword"\n',
    ],
    ids=("duplicate", "adjacent-literals", "escaped-literal"),
)
def test_node_probe_rejects_ambiguous_firmware_defines(tmp_path, credential_defines):
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is required for the launcher define check")

    secrets = tmp_path / "firmware" / "health-node" / "include" / "secrets.h"
    secrets.parent.mkdir(parents=True)
    secrets.write_text(
        '#define DEVICE_ID "health-node-01"\n'
        + credential_defines,
        encoding="utf-8",
    )
    generated = tmp_path / "deploy" / "mosquitto" / "generated"
    generated.mkdir(parents=True)
    (generated / "acl").write_text(
        "user health_node\n"
        "topic write iot-health/v1/devices/health-node-01/telemetry\n"
        "topic write iot-health/v1/devices/health-node-01/event\n"
        "topic write iot-health/v1/devices/health-node-01/status\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("DUMMY=true\n", encoding="utf-8")
    (tmp_path / "deploy" / "docker-compose.yml").write_text(
        "services: {}\n", encoding="utf-8"
    )

    completed = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(AUTH_PROBE_SCRIPT),
            "-ProjectRoot",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )

    assert completed.returncode == 17
    assert "dummy-node-password" not in completed.stdout + completed.stderr
