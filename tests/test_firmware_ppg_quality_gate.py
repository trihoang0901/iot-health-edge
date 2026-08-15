from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware" / "health-node"
GATE_HEADER = FIRMWARE / "include" / "PpgQualityGate.h"
GATE_SOURCE = FIRMWARE / "src" / "PpgQualityGate.cpp"
NATIVE_TEST = FIRMWARE / "test" / "native" / "ppg_quality_gate_test.cpp"
MODEL = FIRMWARE / "include" / "Model.h"
SENSOR_HUB = FIRMWARE / "src" / "SensorHub.cpp"
MQTT_TRANSPORT = FIRMWARE / "src" / "MqttTransport.cpp"


def test_ppg_quality_gate_contract_is_fail_closed_and_versioned():
    header = GATE_HEADER.read_text(encoding="utf-8")
    source = GATE_SOURCE.read_text(encoding="utf-8")
    model = MODEL.read_text(encoding="utf-8")
    sensor_hub = SENSOR_HUB.read_text(encoding="utf-8")
    transport = MQTT_TRANSPORT.read_text(encoding="utf-8")

    assert "kCandidateWindow = 5" in header
    assert "kRequiredConsistentWindows = 3" in header
    assert "kJumpConfirmationBpm = 25.0F" in header
    assert "rrRelativeMad" in header
    assert "4.4478F" in source  # 3-sigma Hampel threshold
    for state in (
        "no_finger",
        "warming_up",
        "motion",
        "clipping",
        "low_perfusion",
        "unstable",
        "sample_loss",
    ):
        assert f'"{state}"' in source

    assert "NullableMeasurement heartRateRawBpm;" in model
    assert "NullableMeasurement spo2RawPct;" in model
    assert "const char* ppgState" in model
    assert "ppgQualityGate_.evaluate" in sensor_hub
    assert 'document_["schema"] = "health.telemetry.v4";' in transport
    assert '"heart_rate_raw_bpm"' in transport
    assert '"spo2_raw_pct"' in transport
    assert 'quality["ppg_state"]' in transport


def test_ppg_quality_gate_native_behavior(tmp_path: Path):
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("No native C++ compiler is available")

    executable = tmp_path / ("ppg_quality_gate_test.exe" if Path(compiler).name.endswith(".exe") else "ppg_quality_gate_test")
    completed = subprocess.run(
        [
            compiler,
            "-std=c++11",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{FIRMWARE / 'include'}",
            str(GATE_SOURCE),
            str(NATIVE_TEST),
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    run = subprocess.run(
        [str(executable)], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PpgQualityGate tests passed" in run.stdout
