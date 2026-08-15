import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from paho.mqtt.reasoncodes import PacketTypes, ReasonCode


ROOT = Path(__file__).resolve().parents[1]
BAT = ROOT / "START-IOT-HEALTH-EDGE.bat"
LAUNCHER = ROOT / "scripts" / "Start-IotHealthEdge.ps1"
DOCTOR = ROOT / "scripts" / "Test-MqttAccess.py"


def _function(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^function {re.escape(name)} \{{(.*?)(?=^function |^try \{{\s*$)",
        source,
    )
    assert match, f"missing PowerShell function {name}"
    return match.group(1)


def test_bat_is_only_a_powershell_51_wrapper():
    source = BAT.read_text(encoding="utf-8")
    assert "scripts\\Start-IotHealthEdge.ps1" in source
    assert "powershell.exe -NoLogo -NoProfile" in source
    assert "docker " not in source.lower()
    assert "platformio" not in source.lower()
    assert "upload" not in source.lower()


def test_launcher_declares_all_modes_and_defaults_to_start():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "[string]$Mode = 'Start'" in source
    for mode in ("Start", "Doctor", "Verify", "Flash", "OpenPortal", "ShowPortalAccess"):
        assert f"'{mode}'" in source


def test_only_flash_mode_can_upload_and_it_never_erases_littlefs():
    source = LAUNCHER.read_text(encoding="utf-8")
    flash = _function(source, "Invoke-FlashMode")
    assert "--target upload" in flash
    without_flash = source.replace(flash, "")
    assert "--target upload" not in without_flash
    assert "--target uploadfs" not in source
    assert "--target erase" not in source
    assert "erasefs" not in source.lower()


def test_start_and_verify_do_not_depend_on_bootstrap_or_usb():
    source = LAUNCHER.read_text(encoding="utf-8")
    start = _function(source, "Invoke-StartMode")
    verify = _function(source, "Invoke-VerifyMode")
    for body in (start, verify):
        assert "Assert-BootstrapConfig" not in body
        assert "Find-Ch340Port" not in body
        assert "--upload-port" not in body
    assert "Wait-NewTelemetry" in start
    assert "-IncludeFirmware" in verify


def test_fresh_telemetry_gate_is_locale_independent():
    source = LAUNCHER.read_text(encoding="utf-8")
    gate = _function(source, "Wait-NewTelemetry")
    assert "[Globalization.CultureInfo]::InvariantCulture" in gate
    assert "[Globalization.DateTimeStyles]::AssumeUniversal" in gate
    assert "[Globalization.DateTimeStyles]::AdjustToUniversal" in gate
    assert "Parse($latest.received_at, $culture, $styles)" in gate
    assert "$device.online -eq $true" in gate
    assert "$received -ge $StartedAt" in gate


def test_open_portal_uses_edge_command_and_execution_correlation():
    source = LAUNCHER.read_text(encoding="utf-8")
    body = _function(source, "Invoke-OpenPortalMode")
    wait = _function(source, "Wait-LiveCommandHeartbeat")
    assert "/commands/open-provisioning" in body
    assert "Wait-LiveCommandHeartbeat" in body
    assert "$device.last_status_reason -eq 'heartbeat'" in wait
    assert "$device.last_status_retained -eq $false" in wait
    assert "$ageSeconds -ge 0 -and $ageSeconds -le 10" in wait
    assert "$body = @{}" in body
    assert "[guid]::NewGuid" not in body
    assert "$webResponse.StatusCode -ne 202" in body
    assert "$response.qos" in body and "$response.retain -ne $false" in body
    assert "$device.status_reason -eq 'provisioning_started'" in body
    assert "$device.correlation_id -eq $response.command_id" in body


def test_portal_secret_uses_dpapi_and_clipboard_only_on_explicit_click():
    source = LAUNCHER.read_text(encoding="utf-8")
    assert "RNGCryptoServiceProvider" in source
    assert "ConvertFrom-SecureString" in source
    assert "ConvertTo-SecureString" in source
    assert "portal-access.dpapi" in source
    assert "PROVISIONING_AP_PASSWORD" in source
    assert "Write-Host $secret" not in source
    assert "Write-Output $secret" not in source
    assert "--portal" not in source.lower()
    show = _function(source, "Invoke-ShowPortalAccessMode")
    assert "Add_Click({ [Windows.Forms.Clipboard]::SetText($box.Text) })" in show
    assert show.count("Clipboard") == 1


def test_doctor_password_is_environment_only_not_an_argument():
    source = LAUNCHER.read_text(encoding="utf-8")
    helper = DOCTOR.read_text(encoding="utf-8")
    assert "$env:IOT_HEALTH_DOCTOR_MQTT_PASSWORD = $settings.MQTT_PASSWORD" in source
    assert "--password" not in source
    assert 'os.environ.get("IOT_HEALTH_DOCTOR_MQTT_PASSWORD")' in helper
    assert 'add_argument("--password"' not in helper
    assert "protocol=mqtt.MQTTv5" in helper
    assert "clean_session=" not in helper
    assert "retain=False" in helper


def test_doctor_handles_real_paho_v2_reason_codes_without_int_coercion():
    spec = importlib.util.spec_from_file_location("mqtt_doctor", DOCTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._reason_is_failure(
        ReasonCode(PacketTypes.CONNACK, "Success")
    ) is False
    assert module._reason_is_failure(
        ReasonCode(PacketTypes.SUBACK, "Granted QoS 1")
    ) is False
    assert module._reason_is_failure(
        ReasonCode(PacketTypes.PUBACK, "Not authorized")
    ) is True


def test_launcher_parses_in_windows_powershell_51():
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is required")
    command = (
        "$errors=$null; "
        f"[Management.Automation.Language.Parser]::ParseFile('{LAUNCHER}',"
        "[ref]$null,[ref]$errors)|Out-Null; if($errors.Count){exit 1}"
    )
    subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )


def test_verify_helper_is_build_only():
    source = (ROOT / "scripts" / "VERIFY-MVP.ps1").read_text(encoding="utf-8")
    assert "& $platformio test --project-dir $firmwareDir --environment native" in source
    assert "& $platformio run --project-dir $firmwareDir --environment nodemcuv2" in source
    assert "--target upload" not in source
    assert "--upload-port" not in source


def test_timestamp_style_keeps_z_and_offset_times_in_utc():
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is required")
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
