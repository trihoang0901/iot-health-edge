from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from edge.schemas import (
    DeviceStatus,
    FallEvent,
    Telemetry,
    TelemetryV2,
    TelemetryV3,
    TelemetryV4,
    parse_telemetry,
    parse_topic,
)


def test_valid_exact_telemetry_schema_is_accepted(valid_telemetry_payload):
    telemetry = Telemetry.model_validate(valid_telemetry_payload)

    assert telemetry.schema_version == "health.telemetry.v1"
    assert telemetry.motion.accel_g == 1.01
    assert telemetry.quality.ppg == 0.88


def test_parser_accepts_strict_v1_through_v4_without_weakening_older_classes(
    valid_telemetry_payload,
    valid_telemetry_v2_payload,
    valid_telemetry_v3_payload,
    valid_telemetry_v4_payload,
):
    v1 = parse_telemetry(json.dumps(valid_telemetry_payload))
    v2 = parse_telemetry(json.dumps(valid_telemetry_v2_payload).encode())
    v3 = parse_telemetry(bytearray(json.dumps(valid_telemetry_v3_payload).encode()))
    v4 = parse_telemetry(json.dumps(valid_telemetry_v4_payload))

    assert isinstance(v1, Telemetry)
    assert isinstance(v2, TelemetryV2)
    assert isinstance(v3, TelemetryV3)
    assert isinstance(v4, TelemetryV4)
    assert v2.environment.ambient_temp_c == 28.5
    assert v3.wearable.wrist_surface_temp_c == 32.8
    assert v4.vitals.heart_rate_raw_bpm == 76.4
    with pytest.raises(ValidationError):
        Telemetry.model_validate(valid_telemetry_v2_payload)
    with pytest.raises(ValidationError):
        TelemetryV2.model_validate(valid_telemetry_v3_payload)
    with pytest.raises(ValidationError):
        TelemetryV3.model_validate(valid_telemetry_v4_payload)


def test_v2_environment_bounds_and_validity_are_strict(valid_telemetry_v2_payload):
    payload = json.loads(json.dumps(valid_telemetry_v2_payload))
    payload["environment"] = {"ambient_temp_c": 0.0, "humidity_pct": 100.0}
    parsed = TelemetryV2.model_validate(payload)
    assert parsed.environment.ambient_temp_c == 0.0
    assert parsed.environment.humidity_pct == 100.0

    for field, value in (("ambient_temp_c", -0.1), ("ambient_temp_c", 50.1)):
        invalid = json.loads(json.dumps(valid_telemetry_v2_payload))
        invalid["environment"][field] = value
        with pytest.raises(ValidationError):
            TelemetryV2.model_validate(invalid)
    for value in (-0.1, 100.1):
        invalid = json.loads(json.dumps(valid_telemetry_v2_payload))
        invalid["environment"]["humidity_pct"] = value
        with pytest.raises(ValidationError):
            TelemetryV2.model_validate(invalid)


@pytest.mark.parametrize(
    ("field", "validity_flag"),
    (("ambient_temp_c", "ambient_temp_valid"), ("humidity_pct", "humidity_valid")),
)
def test_v2_environment_values_follow_independent_validity_flags(
    valid_telemetry_v2_payload, field, validity_flag
):
    payload = json.loads(json.dumps(valid_telemetry_v2_payload))
    payload["quality"][validity_flag] = False
    with pytest.raises(ValidationError, match="must be null"):
        TelemetryV2.model_validate(payload)

    payload["environment"][field] = None
    assert getattr(TelemetryV2.model_validate(payload).environment, field) is None

    payload["quality"][validity_flag] = True
    with pytest.raises(ValidationError, match="value is null"):
        TelemetryV2.model_validate(payload)


def test_v2_dht_failure_and_only_exact_v2_fields_are_accepted(
    valid_telemetry_v2_payload
):
    payload = json.loads(json.dumps(valid_telemetry_v2_payload))
    payload["environment"] = {"ambient_temp_c": None, "humidity_pct": None}
    payload["quality"]["ambient_temp_valid"] = False
    payload["quality"]["humidity_valid"] = False
    payload["system"]["faults"] = ["dht11_unavailable"]
    assert TelemetryV2.model_validate(payload).system.faults == ["dht11_unavailable"]

    payload["vitals"]["skin_temp_c"] = 34.0
    payload["quality"]["skin_temp_valid"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TelemetryV2.model_validate(payload)


def test_v3_wrist_surface_temperature_bounds_and_finite_values_are_strict(
    valid_telemetry_v3_payload,
):
    for value in (0.0, 50.0):
        payload = json.loads(json.dumps(valid_telemetry_v3_payload))
        payload["wearable"]["wrist_surface_temp_c"] = value
        parsed = TelemetryV3.model_validate(payload)
        assert parsed.wearable.wrist_surface_temp_c == value

    for value in (-0.1, 50.1, float("nan"), float("inf"), float("-inf")):
        payload = json.loads(json.dumps(valid_telemetry_v3_payload))
        payload["wearable"]["wrist_surface_temp_c"] = value
        with pytest.raises(ValidationError):
            TelemetryV3.model_validate(payload)


def test_v3_wrist_surface_value_follows_validity_flag(valid_telemetry_v3_payload):
    payload = json.loads(json.dumps(valid_telemetry_v3_payload))
    payload["quality"]["wrist_surface_temp_valid"] = False
    with pytest.raises(ValidationError, match="must be null"):
        TelemetryV3.model_validate(payload)

    payload["wearable"]["wrist_surface_temp_c"] = None
    payload["system"]["faults"] = ["ds18b20_unavailable"]
    assert TelemetryV3.model_validate(payload).wearable.wrist_surface_temp_c is None

    payload["quality"]["wrist_surface_temp_valid"] = True
    with pytest.raises(ValidationError, match="value is null"):
        TelemetryV3.model_validate(payload)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("wearable", "wrist_surface_temp_c", "32.8"),
        ("wearable", "wrist_surface_temp_c", True),
        ("quality", "wrist_surface_temp_valid", 1),
        ("quality", "finger_present", 1),
        ("motion", "accel_g", "1.0"),
    ],
)
def test_v3_rejects_coercible_non_json_types(
    valid_telemetry_v3_payload, section, field, value
):
    payload = json.loads(json.dumps(valid_telemetry_v3_payload))
    payload[section][field] = value

    with pytest.raises(ValidationError):
        TelemetryV3.model_validate(payload)


def test_v3_wrist_validity_and_ds18b20_fault_are_consistent(
    valid_telemetry_v3_payload,
):
    valid_payload = json.loads(json.dumps(valid_telemetry_v3_payload))
    valid_payload["system"]["faults"] = ["ds18b20_unavailable"]
    with pytest.raises(ValidationError, match="valid wrist temperature"):
        TelemetryV3.model_validate(valid_payload)

    invalid_payload = json.loads(json.dumps(valid_telemetry_v3_payload))
    invalid_payload["wearable"]["wrist_surface_temp_c"] = None
    invalid_payload["quality"]["wrist_surface_temp_valid"] = False
    with pytest.raises(ValidationError, match="must report ds18b20_unavailable"):
        TelemetryV3.model_validate(invalid_payload)

    invalid_payload["system"]["faults"] = ["ds18b20_unavailable"]
    assert TelemetryV3.model_validate(invalid_payload).wearable.wrist_surface_temp_c is None


def test_v3_ds18b20_failure_and_only_exact_v3_fields_are_accepted(
    valid_telemetry_v3_payload,
):
    payload = json.loads(json.dumps(valid_telemetry_v3_payload))
    payload["wearable"]["wrist_surface_temp_c"] = None
    payload["quality"]["wrist_surface_temp_valid"] = False
    payload["system"]["faults"] = ["ds18b20_unavailable"]
    assert TelemetryV3.model_validate(payload).system.faults == [
        "ds18b20_unavailable"
    ]

    payload["environment"] = {"ambient_temp_c": 28.5, "humidity_pct": 63.0}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TelemetryV3.model_validate(payload)


def test_v4_raw_values_can_survive_unconfirmed_ppg(
    valid_telemetry_v4_payload,
):
    payload = json.loads(json.dumps(valid_telemetry_v4_payload))
    payload["vitals"]["heart_rate_bpm"] = None
    payload["vitals"]["spo2_pct"] = None
    payload["quality"]["heart_rate_valid"] = False
    payload["quality"]["spo2_valid"] = False
    payload["quality"]["ppg_state"] = "unstable"

    telemetry = TelemetryV4.model_validate(payload)

    assert telemetry.vitals.heart_rate_raw_bpm == 76.4
    assert telemetry.vitals.spo2_raw_pct == 97.2
    assert telemetry.vitals.heart_rate_bpm is None
    assert telemetry.vitals.spo2_pct is None


@pytest.mark.parametrize("ppg_state", ["no_finger", "sample_loss"])
def test_v4_no_finger_or_sample_loss_requires_null_raw_and_confirmed_values(
    valid_telemetry_v4_payload,
    ppg_state,
):
    payload = json.loads(json.dumps(valid_telemetry_v4_payload))
    payload["vitals"] = {
        "heart_rate_raw_bpm": None,
        "heart_rate_bpm": None,
        "spo2_raw_pct": None,
        "spo2_pct": None,
    }
    payload["quality"].update(
        {
            "ppg": None,
            "ppg_state": ppg_state,
            "finger_present": False,
            "heart_rate_valid": False,
            "spo2_valid": False,
        }
    )

    assert TelemetryV4.model_validate(payload).quality.ppg_state == ppg_state

    payload["vitals"]["heart_rate_raw_bpm"] = 81.0
    with pytest.raises(ValidationError, match="raw PPG values must be null"):
        TelemetryV4.model_validate(payload)


def test_v4_confirmed_values_require_valid_flags_and_valid_ppg_state(
    valid_telemetry_v4_payload,
):
    invalid_flag = json.loads(json.dumps(valid_telemetry_v4_payload))
    invalid_flag["quality"]["heart_rate_valid"] = False
    with pytest.raises(ValidationError, match="must be null"):
        TelemetryV4.model_validate(invalid_flag)

    invalid_state = json.loads(json.dumps(valid_telemetry_v4_payload))
    invalid_state["quality"]["ppg_state"] = "warming_up"
    with pytest.raises(ValidationError, match="require ppg_state='valid'"):
        TelemetryV4.model_validate(invalid_state)


def test_telemetry_parser_rejects_unknown_or_non_object_schema():
    with pytest.raises(ValueError, match="unsupported telemetry schema"):
        parse_telemetry('{"schema":"health.telemetry.v5"}')
    with pytest.raises(ValueError, match="JSON object"):
        parse_telemetry("[]")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_are_rejected(clone_payload, value):
    payload = clone_payload()
    payload["vitals"]["heart_rate_bpm"] = value

    with pytest.raises(ValidationError):
        Telemetry.model_validate(payload)


def test_invalid_vital_must_be_null(clone_payload):
    payload = clone_payload()
    payload["quality"]["spo2_valid"] = False

    with pytest.raises(ValidationError, match="must be null"):
        Telemetry.model_validate(payload)

    payload["vitals"]["spo2_pct"] = None
    assert Telemetry.model_validate(payload).vitals.spo2_pct is None


def test_valid_vital_cannot_be_null(clone_payload):
    payload = clone_payload()
    payload["vitals"]["skin_temp_c"] = None

    with pytest.raises(ValidationError, match="value is null"):
        Telemetry.model_validate(payload)


def test_no_finger_suppresses_ppg_vitals(clone_payload):
    payload = clone_payload()
    payload["quality"]["finger_present"] = False
    payload["quality"]["heart_rate_valid"] = False
    payload["quality"]["spo2_valid"] = False
    payload["vitals"]["heart_rate_bpm"] = None
    payload["vitals"]["spo2_pct"] = None

    assert Telemetry.model_validate(payload).quality.finger_present is False

    payload["quality"]["heart_rate_valid"] = True
    payload["vitals"]["heart_rate_bpm"] = 75.0
    with pytest.raises(ValidationError, match="without a finger"):
        Telemetry.model_validate(payload)


def test_valid_ppg_vitals_require_quality_score(clone_payload):
    payload = clone_payload()
    payload["quality"]["ppg"] = None

    with pytest.raises(ValidationError, match="non-null ppg quality score"):
        Telemetry.model_validate(payload)


def test_motion_values_follow_motion_validity(clone_payload):
    payload = clone_payload()
    payload["motion"]["accel_g"] = None
    with pytest.raises(ValidationError, match="motion is valid"):
        Telemetry.model_validate(payload)

    payload = clone_payload()
    payload["quality"]["motion_valid"] = False
    payload["motion"]["fall_state"] = "unknown"
    with pytest.raises(ValidationError, match="motion values must be null"):
        Telemetry.model_validate(payload)

    payload["motion"]["accel_g"] = None
    payload["motion"]["gyro_dps"] = None
    with pytest.raises(ValidationError, match="valid motion quality data"):
        Telemetry.model_validate(payload)

    payload["quality"]["heart_rate_valid"] = False
    payload["quality"]["spo2_valid"] = False
    payload["vitals"]["heart_rate_bpm"] = None
    payload["vitals"]["spo2_pct"] = None
    assert Telemetry.model_validate(payload).motion.fall_state == "unknown"

    payload["motion"]["fall_state"] = "idle"
    with pytest.raises(ValidationError, match="fall_state='unknown'"):
        Telemetry.model_validate(payload)


def test_public_fall_state_machine_values_are_accepted(clone_payload):
    for state in (
        "idle",
        "low_g",
        "impact",
        "verify_stillness",
        "alarm",
        "acked",
        "refractory",
    ):
        payload = clone_payload()
        payload["motion"]["fall_state"] = state
        assert Telemetry.model_validate(payload).motion.fall_state == state


def test_unknown_fields_are_rejected(clone_payload):
    payload = clone_payload()
    payload["sent_at"] = "2026-08-04T10:00:00Z"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Telemetry.model_validate(payload)


def test_event_and_status_contracts():
    event = FallEvent.model_validate(
        {
            "schema": "health.event.v1",
            "device_id": "health-node-01",
            "boot_id": "boot-1",
            "event_id": "boot-1:7:fall",
            "seq": 7,
            "uptime_ms": 7000,
            "type": "fall_suspected_demo",
        }
    )
    status = DeviceStatus.model_validate(
        {
            "schema": "health.status.v1",
            "device_id": "health-node-01",
            "boot_id": "boot-1",
            "seq": 8,
            "uptime_ms": 8000,
            "online": False,
            "reason": "lwt",
            "system": {"rssi_dbm": -60, "free_heap": 30000, "fw": "0.1.0", "faults": []},
        }
    )

    assert event.type == "fall_suspected_demo"
    assert status.online is False


def test_topic_contract_is_exact():
    assert parse_topic("iot-health/v1/devices/health-node-01/telemetry") == (
        "health-node-01",
        "telemetry",
    )
    with pytest.raises(ValueError):
        parse_topic("health/v1/health-node-01/telemetry")
