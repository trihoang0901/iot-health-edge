from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SENSOR_HUB = ROOT / "firmware" / "health-node" / "src" / "SensorHub.cpp"
APP_CONFIG = ROOT / "firmware" / "health-node" / "include" / "AppConfig.h"
PLATFORMIO = ROOT / "firmware" / "health-node" / "platformio.ini"


def test_ppg_continuity_guards_do_not_pre_gate_on_overflow_counter():
    source = SENSOR_HUB.read_text(encoding="utf-8")

    assert "ppgTickGapMs > config::kPpgMaximumSamplingGapMs" in source
    assert "fetched >= kSparkFunFifoStorageSize" in source
    assert "kFifoOverflowCounterRegister" not in source
    assert "hardwareOverflow" not in source


def test_production_firmware_has_no_ppg_diagnostic_build_path():
    source = SENSOR_HUB.read_text(encoding="utf-8")
    platformio = PLATFORMIO.read_text(encoding="utf-8")

    assert "PPG_DIAGNOSTICS" not in source
    assert "PPG_DIAGNOSTICS" not in platformio
    assert "nodemcuv2_ppg_diag" not in platformio


def test_ppg_recovery_remains_in_current_firmware_release():
    config = APP_CONFIG.read_text(encoding="utf-8")

    assert 'constexpr char kFirmwareVersion[] = "0.3.0";' in config
