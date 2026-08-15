import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ROTATE_SCRIPT = ROOT / "deploy" / "scripts" / "Rotate-LocalNodeMqttCredential.ps1"
INITIALIZE_SCRIPT = ROOT / "deploy" / "scripts" / "Initialize-Mosquitto.ps1"
SYNC_SCRIPT = ROOT / "deploy" / "scripts" / "Sync-FirmwareMqttCredential.ps1"


def test_rotation_contract_keeps_generated_password_off_argv_and_output():
    source = ROTATE_SCRIPT.read_text(encoding="utf-8")
    param_block = source.split("param(", 1)[1].split("\n)", 1)[0]

    assert "$PSScriptRoot" not in param_block
    assert "RandomNumberGenerator" in source
    assert "Invoke-DockerWithUtf8StdinQuiet" in source
    assert "ConvertTo-WindowsCommandLineArgument" in source
    assert "$startInfo.Arguments" in source
    assert "$standardInput.BaseStream.Write($inputBytes" in source
    assert "[Text.Encoding]::UTF8.GetBytes($InputText)" in source
    assert "[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)" in source
    assert "StandardInputEncoding" not in source
    assert "ArgumentList" not in source
    assert "-InputText $passwordInput" in source
    assert "$passwordInput | & docker" not in source
    assert "'mosquitto_passwd', ('/work/' + (Split-Path -Leaf $stagedPasswordFile))" in source
    assert "mosquitto_passwd -b" not in source
    assert "*> $null" in source
    assert "[IO.File]::ReadAllBytes($envPath)" in source
    assert "[IO.File]::WriteAllBytes($restoreItem.Path, $restoreItem.Bytes)" in source
    assert "Test-NodeMqttCredential.ps1" in source
    assert "-StaticOnly" in source
    assert "-HostBroker" in source
    assert "restart mosquitto" in source
    assert "secrets.' + $rotationId + '.h'" in source
    assert "'passwords.rotate.' + $rotationId + '.next'" in source
    assert "rollbackRestartExit" in source
    assert "rollbackServices -notcontains 'mosquitto'" in source


def test_all_credential_writers_share_an_exclusive_mutex():
    rotate_source = ROTATE_SCRIPT.read_text(encoding="utf-8")
    initialize_source = INITIALIZE_SCRIPT.read_text(encoding="utf-8")
    sync_source = SYNC_SCRIPT.read_text(encoding="utf-8")
    mutex_name = "Local\\IotHealthEdge.MqttCredentialFiles.v1"

    for source in (rotate_source, initialize_source, sync_source):
        assert mutex_name in source
        assert "$credentialMutex.WaitOne(0)" in source
        assert "$credentialMutex.ReleaseMutex()" in source
        assert "$credentialMutex.Dispose()" in source


def test_rotation_whatif_needs_no_files_or_docker_and_changes_nothing(tmp_path):
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is required for the rotation WhatIf check")

    completed = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROTATE_SCRIPT),
            "-ProjectRoot",
            str(tmp_path),
            "-WhatIf",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )

    assert completed.returncode == 0
    assert list(tmp_path.iterdir()) == []
