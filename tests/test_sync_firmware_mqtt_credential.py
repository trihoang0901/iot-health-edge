import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SYNC_SCRIPT = ROOT / "deploy" / "scripts" / "Sync-FirmwareMqttCredential.ps1"


def test_sync_resolves_script_root_after_windows_powershell_parameter_binding():
    source = SYNC_SCRIPT.read_text(encoding="utf-8")
    param_block = source.split("param(", 1)[1].split("\n)", 1)[0]

    assert "$PSScriptRoot" not in param_block
    assert "[string]::IsNullOrWhiteSpace($ProjectRoot)" in source
    assert "[IO.File]::ReadAllLines($envPath)" in source
    assert "('secrets.' + [guid]::NewGuid().ToString('N') + '.h')" in source


def test_sync_uses_node_environment_credential_without_echoing_it(tmp_path):
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is required for the credential sync check")

    password = f"unit-only-{tmp_path.name}-credential"
    secrets = tmp_path / "firmware" / "health-node" / "include" / "secrets.h"
    secrets.parent.mkdir(parents=True)
    secrets.write_text(
        '#define WIFI_SSID "keep-this"\n'
        '#define MQTT_USERNAME "stale-user"\n'
        '#define MQTT_PASSWORD "stale-password"\n',
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "SIMULATOR_MQTT_USERNAME=health_node\n"
        f"SIMULATOR_MQTT_PASSWORD={password}\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SYNC_SCRIPT),
            "-ProjectRoot",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )

    assert completed.returncode == 0
    updated = secrets.read_text(encoding="utf-8")
    assert '#define WIFI_SSID "keep-this"' in updated
    assert '#define MQTT_USERNAME "health_node"' in updated
    assert f'#define MQTT_PASSWORD "{password}"' in updated
    assert password not in completed.stdout
    assert password not in completed.stderr


@pytest.mark.parametrize(
    "environment",
    [
        "SIMULATOR_MQTT_USERNAME=health_node\n"
        "SIMULATOR_MQTT_PASSWORD=\n"
        "DEVICE_ID=health-node-01\n",
        "SIMULATOR_MQTT_USERNAME=health_node\n"
        "SIMULATOR_MQTT_PASSWORD=first-dummy\n"
        "SIMULATOR_MQTT_PASSWORD=second-dummy\n",
        "SIMULATOR_MQTT_USERNAME=health_node\n"
        "SIMULATOR_MQTT_PASSWORD=replace_with_local_node_password\n",
        "SIMULATOR_MQTT_USERNAME=health_node\n"
        "SIMULATOR_MQTT_PASSWORD= # local comment only\n",
    ],
    ids=(
        "empty-does-not-consume-next-line",
        "duplicate",
        "placeholder",
        "comment-only",
    ),
)
def test_sync_rejects_ambiguous_or_placeholder_values_without_changing_secrets(
    tmp_path, environment
):
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is required for the credential sync check")

    original = (
        '#define MQTT_USERNAME "stale-user"\n'
        '#define MQTT_PASSWORD "stale-password"\n'
    )
    secrets = tmp_path / "firmware" / "health-node" / "include" / "secrets.h"
    secrets.parent.mkdir(parents=True)
    secrets.write_text(original, encoding="utf-8")
    (tmp_path / ".env").write_text(environment, encoding="utf-8")

    completed = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SYNC_SCRIPT),
            "-ProjectRoot",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )

    assert completed.returncode != 0
    assert secrets.read_text(encoding="utf-8") == original
    assert "first-dummy" not in completed.stdout + completed.stderr
    assert "second-dummy" not in completed.stdout + completed.stderr
    assert "replace_with_local_node_password" not in completed.stdout + completed.stderr


@pytest.mark.parametrize(
    ("password_setting", "expected_password"),
    [
        ('"dummy # password" # local only', "dummy # password"),
        ("#literal-password", "#literal-password"),
    ],
    ids=("quoted-with-comment", "literal-leading-hash"),
)
def test_sync_supports_compose_dotenv_comment_rules(
    tmp_path, password_setting, expected_password
):
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is required for the credential sync check")

    secrets = tmp_path / "firmware" / "health-node" / "include" / "secrets.h"
    secrets.parent.mkdir(parents=True)
    secrets.write_text(
        '#define MQTT_USERNAME "stale-user"\n'
        '#define MQTT_PASSWORD "stale-password"\n',
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "SIMULATOR_MQTT_USERNAME=health_node # local account\n"
        f"SIMULATOR_MQTT_PASSWORD={password_setting}\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SYNC_SCRIPT),
            "-ProjectRoot",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )

    assert completed.returncode == 0
    updated = secrets.read_text(encoding="utf-8")
    assert '#define MQTT_USERNAME "health_node"' in updated
    assert f'#define MQTT_PASSWORD "{expected_password}"' in updated
    assert expected_password not in completed.stdout + completed.stderr
