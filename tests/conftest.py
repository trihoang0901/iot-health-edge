from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator

import pytest
from starlette.testclient import TestClient

# Never let a developer's shell credentials trigger real MQTT or Telegram I/O
# during test collection. Tests opt into either transport with explicit fakes.
os.environ["MQTT_ENABLED"] = "false"
os.environ["TELEGRAM_ENABLED"] = "false"

from edge.app import create_app
from edge.config import DemoRuleSettings, Settings


@pytest.fixture
def valid_telemetry_payload() -> dict[str, Any]:
    return {
        "schema": "health.telemetry.v1",
        "device_id": "health-node-01",
        "boot_id": "boot-0001",
        "seq": 1,
        "uptime_ms": 1000,
        "vitals": {
            "heart_rate_bpm": 76.0,
            "spo2_pct": 97.0,
            "skin_temp_c": 34.5,
        },
        "motion": {
            "accel_g": 1.01,
            "gyro_dps": 2.5,
            "fall_state": "idle",
        },
        "quality": {
            "ppg": 0.88,
            "finger_present": True,
            "motion_artifact": False,
            "heart_rate_valid": True,
            "spo2_valid": True,
            "skin_temp_valid": True,
            "motion_valid": True,
        },
        "system": {
            "rssi_dbm": -55,
            "free_heap": 31_000,
            "fw": "0.1.0",
            "faults": [],
        },
    }


@pytest.fixture
def valid_telemetry_v2_payload() -> dict[str, Any]:
    return {
        "schema": "health.telemetry.v2",
        "device_id": "health-node-01",
        "boot_id": "boot-0002",
        "seq": 2,
        "uptime_ms": 2000,
        "vitals": {
            "heart_rate_bpm": 76.0,
            "spo2_pct": 97.0,
        },
        "environment": {
            "ambient_temp_c": 28.5,
            "humidity_pct": 63.0,
        },
        "motion": {
            "accel_g": 1.01,
            "gyro_dps": 2.5,
            "fall_state": "idle",
        },
        "quality": {
            "ppg": 0.88,
            "finger_present": True,
            "motion_artifact": False,
            "heart_rate_valid": True,
            "spo2_valid": True,
            "motion_valid": True,
            "ambient_temp_valid": True,
            "humidity_valid": True,
        },
        "system": {
            "rssi_dbm": -55,
            "free_heap": 31_000,
            "fw": "0.2.0",
            "faults": [],
        },
    }


@pytest.fixture
def valid_telemetry_v3_payload() -> dict[str, Any]:
    return {
        "schema": "health.telemetry.v3",
        "device_id": "health-node-01",
        "boot_id": "boot-0003",
        "seq": 3,
        "uptime_ms": 3000,
        "vitals": {
            "heart_rate_bpm": 76.0,
            "spo2_pct": 97.0,
        },
        "wearable": {
            "wrist_surface_temp_c": 32.8,
        },
        "motion": {
            "accel_g": 1.01,
            "gyro_dps": 2.5,
            "fall_state": "idle",
        },
        "quality": {
            "ppg": 0.88,
            "finger_present": True,
            "motion_artifact": False,
            "heart_rate_valid": True,
            "spo2_valid": True,
            "motion_valid": True,
            "wrist_surface_temp_valid": True,
        },
        "system": {
            "rssi_dbm": -55,
            "free_heap": 31_000,
            "fw": "0.3.1",
            "faults": [],
        },
    }


@pytest.fixture
def app_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "test.db",
        mqtt_enabled=False,
        telegram_enabled=False,
        telegram_bot_token=None,
        telegram_chat_id=None,
        offline_after_seconds=30.0,
        rules=DemoRuleSettings(
            low_spo2_threshold=92.0,
            high_hr_threshold=120.0,
            hold_seconds=0.0,
            spo2_hysteresis=2.0,
            hr_hysteresis=5.0,
            min_ppg_quality=0.5,
            fall_recovery_seconds=0.0,
        ),
    )


@pytest.fixture
def client(app_settings: Settings) -> Iterator[TestClient]:
    app = create_app(app_settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def clone_payload(valid_telemetry_payload: dict[str, Any]):
    def clone() -> dict[str, Any]:
        return deepcopy(valid_telemetry_payload)

    return clone
