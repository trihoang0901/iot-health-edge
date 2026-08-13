from __future__ import annotations

from datetime import UTC, datetime, timedelta

from edge.config import DemoRuleSettings
from edge.db import Database
from edge.rules import RuleEngine
from edge.schemas import Telemetry, TelemetryV2


def build_engine(tmp_path, *, hold=5.0, fall_recovery=5.0, max_sample_gap=3.0):
    database = Database(tmp_path / "rules.db")
    database.initialize()
    engine = RuleEngine(
        database,
        DemoRuleSettings(
            low_spo2_threshold=92.0,
            high_hr_threshold=120.0,
            hold_seconds=hold,
            spo2_hysteresis=2.0,
            hr_hysteresis=5.0,
            min_ppg_quality=0.5,
            fall_recovery_seconds=fall_recovery,
            max_sample_gap_seconds=max_sample_gap,
        ),
    )
    return database, engine


def test_public_rules_do_not_advertise_retired_surface_temperature(tmp_path):
    _, engine = build_engine(tmp_path)

    rule_ids = {rule["rule_id"] for rule in engine.public_rules()}

    assert rule_ids == {"demo_low_spo2", "demo_high_hr", "fall_suspected_demo"}


def test_v2_environment_never_opens_a_threshold_alert(
    tmp_path, valid_telemetry_v2_payload
):
    database, engine = build_engine(tmp_path, hold=0.0)
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    database.ensure_device("health-node-01", "boot-0002", now)
    valid_telemetry_v2_payload["environment"] = {
        "ambient_temp_c": 50.0,
        "humidity_pct": 100.0,
    }

    engine.evaluate(TelemetryV2.model_validate(valid_telemetry_v2_payload), now)

    assert database.list_alerts(state="active") == []


def telemetry_from(payload, **vitals):
    copied = {**payload, "vitals": {**payload["vitals"], **vitals}}
    return Telemetry.model_validate(copied)


def test_rule_requires_hold_duration_and_deduplicates(tmp_path, valid_telemetry_payload):
    database, engine = build_engine(tmp_path, hold=5.0)
    database.ensure_device("health-node-01", "boot-1", datetime.now(UTC))
    low = telemetry_from(valid_telemetry_payload, spo2_pct=90.0)
    start = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

    engine.evaluate(low, start)
    engine.evaluate(low, start + timedelta(seconds=2))
    engine.evaluate(low, start + timedelta(seconds=4))
    assert database.list_alerts(state="active") == []

    engine.evaluate(low, start + timedelta(seconds=5))
    engine.evaluate(low, start + timedelta(seconds=6))
    alerts = database.list_alerts(state="active")
    assert len(alerts) == 1
    assert alerts[0]["rule_id"] == "demo_low_spo2"
    assert alerts[0]["occurrence_count"] == 2


def test_rule_hold_resets_after_sample_gap(tmp_path, valid_telemetry_payload):
    database, engine = build_engine(tmp_path, hold=5.0, max_sample_gap=3.0)
    start = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    database.ensure_device("health-node-01", "boot-1", start)
    low = telemetry_from(valid_telemetry_payload, spo2_pct=90.0)

    engine.evaluate(low, start)
    engine.evaluate(low, start + timedelta(seconds=4))
    engine.evaluate(low, start + timedelta(seconds=6))
    assert database.list_alerts(state="active") == []

    engine.evaluate(low, start + timedelta(seconds=9))
    alerts = database.list_alerts(state="active")
    assert len(alerts) == 1
    assert alerts[0]["first_seen_at"].endswith("12:00:09.000Z")


def test_hysteresis_prevents_alert_flapping(tmp_path, valid_telemetry_payload):
    database, engine = build_engine(tmp_path, hold=0.0)
    now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    database.ensure_device("health-node-01", "boot-1", now)

    engine.evaluate(telemetry_from(valid_telemetry_payload, spo2_pct=90.0), now)
    engine.evaluate(
        telemetry_from(valid_telemetry_payload, spo2_pct=93.0),
        now + timedelta(seconds=1),
    )
    assert len(database.list_alerts(state="active")) == 1

    engine.evaluate(
        telemetry_from(valid_telemetry_payload, spo2_pct=94.0),
        now + timedelta(seconds=2),
    )
    assert database.list_alerts(state="active") == []
    assert database.list_alerts(state="resolved")[0]["rule_id"] == "demo_low_spo2"


def test_invalid_quality_suppresses_rule(tmp_path, clone_payload):
    database, engine = build_engine(tmp_path, hold=0.0)
    now = datetime.now(UTC)
    database.ensure_device("health-node-01", "boot-1", now)
    payload = clone_payload()
    payload["quality"]["spo2_valid"] = False
    payload["vitals"]["spo2_pct"] = None

    engine.evaluate(Telemetry.model_validate(payload), now)

    assert database.list_alerts(state="active") == []


def test_fall_alert_only_opens_from_event_and_idle_resolves_it(
    tmp_path, valid_telemetry_payload
):
    database, engine = build_engine(tmp_path, hold=0.0, fall_recovery=5.0)
    start = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    database.ensure_device("health-node-01", "boot-1", start)
    alarm_payload = {
        **valid_telemetry_payload,
        "motion": {**valid_telemetry_payload["motion"], "fall_state": "alarm"},
    }

    engine.evaluate(Telemetry.model_validate(alarm_payload), start)
    assert database.get_active_alert("health-node-01", "fall_suspected_demo") is None

    database.record_fall_event(
        device_id="health-node-01", event_id="boot-1:9:fall", happened=start
    )
    idle = Telemetry.model_validate(valid_telemetry_payload)
    engine.evaluate(idle, start + timedelta(seconds=1))
    assert database.get_active_alert("health-node-01", "fall_suspected_demo") is not None

    engine.evaluate(idle, start + timedelta(seconds=3))
    engine.evaluate(idle, start + timedelta(seconds=5))
    engine.evaluate(idle, start + timedelta(seconds=6))
    assert database.get_active_alert("health-node-01", "fall_suspected_demo") is None


def test_fall_recovery_resets_after_sample_gap(tmp_path, valid_telemetry_payload):
    database, engine = build_engine(
        tmp_path,
        hold=0.0,
        fall_recovery=5.0,
        max_sample_gap=3.0,
    )
    start = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    database.ensure_device("health-node-01", "boot-1", start)
    database.record_fall_event(
        device_id="health-node-01", event_id="boot-1:10:fall", happened=start
    )
    idle = Telemetry.model_validate(valid_telemetry_payload)

    engine.evaluate(idle, start + timedelta(seconds=1))
    engine.evaluate(idle, start + timedelta(seconds=5))
    engine.evaluate(idle, start + timedelta(seconds=7))
    assert database.get_active_alert("health-node-01", "fall_suspected_demo") is not None

    engine.evaluate(idle, start + timedelta(seconds=10))
    assert database.get_active_alert("health-node-01", "fall_suspected_demo") is None
