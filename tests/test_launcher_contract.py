import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "START-IOT-HEALTH-EDGE.bat"


def test_post_upload_gate_is_fresh_v2_node_specific_and_locale_independent():
    source = LAUNCHER.read_text(encoding="utf-8")

    assert "[Globalization.CultureInfo]::InvariantCulture" in source
    assert "[Globalization.DateTimeStyles]::AssumeUniversal" in source
    assert "[Globalization.DateTimeStyles]::AdjustToUniversal" in source
    assert "Parse($env:UPLOAD_STARTED_UTC,$culture,$styles)" in source
    assert "Parse($latest.received_at,$culture,$styles)" in source
    assert "$device.online -eq $true" in source
    assert "$received -ge $started" in source
    assert "$schema -eq 'health.telemetry.v2'" in source
    assert "$latest.system.fw -eq '0.2.1'" in source


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
