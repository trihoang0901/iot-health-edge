from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from edge.config import DemoRuleSettings
from edge.db import Database
from edge.rules import RuleEngine
from edge.service import InboundMessage, IngestionService


class RecordingNotifier:
    def __init__(self, *, accepted=True, error=None):
        self.accepted = accepted
        self.error = error
        self.notifications = []

    def enqueue(self, notification):
        if self.error is not None:
            raise self.error
        self.notifications.append(notification)
        return self.accepted


def make_service(
    tmp_path,
    *,
    hold_seconds=0.0,
    fall_recovery_seconds=0.0,
    max_payload_bytes=4096,
    notifier=None,
):
    database = Database(tmp_path / "edge.db")
    database.initialize()
    settings = DemoRuleSettings(
        hold_seconds=hold_seconds,
        fall_recovery_seconds=fall_recovery_seconds,
    )
    return database, IngestionService(
        database,
        RuleEngine(database, settings),
        max_payload_bytes=max_payload_bytes,
        notifier=notifier,
    )


def message(kind, payload, received=None):
    return InboundMessage(
        topic=f"iot-health/v1/devices/{payload['device_id']}/{kind}",
        payload=json.dumps(payload).encode(),
        received_at=received or datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
    )


def test_telemetry_is_persisted_once(tmp_path, valid_telemetry_payload):
    database, service = make_service(tmp_path)

    first = service.process_message(message("telemetry", valid_telemetry_payload))
    second = service.process_message(message("telemetry", valid_telemetry_payload))

    assert first.accepted and not first.duplicate
    assert second.accepted and second.duplicate
    assert len(database.telemetry_history("health-node-01")) == 1
    assert service.metrics()["duplicates"] == 1


def test_v2_telemetry_is_ingested_with_environment_normalization(
    tmp_path, valid_telemetry_v2_payload
):
    database, service = make_service(tmp_path)

    result = service.process_message(message("telemetry", valid_telemetry_v2_payload))

    assert result.accepted and not result.duplicate
    latest = database.latest_telemetry("health-node-01")
    assert latest["schema"] == "health.telemetry.v2"
    assert latest["environment"] == {"ambient_temp_c": 28.5, "humidity_pct": 63.0}
    assert latest["vitals"]["skin_temp_c"] is None


def test_v2_invalid_environment_flag_pair_is_rejected(
    tmp_path, valid_telemetry_v2_payload
):
    _, service = make_service(tmp_path)
    valid_telemetry_v2_payload["quality"]["humidity_valid"] = False

    result = service.process_message(message("telemetry", valid_telemetry_v2_payload))

    assert not result.accepted
    assert "must be null" in result.error


def test_v3_telemetry_is_ingested_with_wearable_normalization(
    tmp_path, valid_telemetry_v3_payload
):
    database, service = make_service(tmp_path)

    result = service.process_message(message("telemetry", valid_telemetry_v3_payload))

    assert result.accepted and not result.duplicate
    latest = database.latest_telemetry("health-node-01")
    assert latest["schema"] == "health.telemetry.v3"
    assert latest["wearable"] == {"wrist_surface_temp_c": 32.8}
    assert latest["quality"]["wrist_surface_temp_valid"] is True
    assert latest["environment"] == {"ambient_temp_c": None, "humidity_pct": None}
    assert latest["vitals"]["skin_temp_c"] is None


def test_v3_invalid_wrist_surface_flag_pair_is_rejected(
    tmp_path, valid_telemetry_v3_payload
):
    _, service = make_service(tmp_path)
    valid_telemetry_v3_payload["quality"]["wrist_surface_temp_valid"] = False

    result = service.process_message(message("telemetry", valid_telemetry_v3_payload))

    assert not result.accepted
    assert "must be null" in result.error


def test_superseded_telemetry_is_stale_and_does_not_rewind_device_liveness(
    tmp_path, clone_payload
):
    database, service = make_service(tmp_path)
    start = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    boot_a = clone_payload()
    boot_a["boot_id"] = "boot-a"
    boot_b = clone_payload()
    boot_b["boot_id"] = "boot-b"

    assert service.process_message(message("telemetry", boot_a, start)).accepted
    assert service.process_message(
        message("telemetry", boot_b, start + timedelta(seconds=1))
    ).accepted
    current = database.get_device("health-node-01")

    replay = service.process_message(
        message("telemetry", boot_a, start + timedelta(seconds=2))
    )
    after_replay = database.get_device("health-node-01")

    assert replay.accepted and replay.disposition == "stale"
    assert not replay.duplicate
    assert after_replay["boot_id"] == "boot-b"
    assert after_replay["last_seen_at"] == current["last_seen_at"]
    assert after_replay["updated_at"] == current["updated_at"]


def test_topic_device_mismatch_is_rejected(tmp_path, valid_telemetry_payload):
    _, service = make_service(tmp_path)
    inbound = InboundMessage(
        topic="iot-health/v1/devices/another-node/telemetry",
        payload=json.dumps(valid_telemetry_payload).encode(),
        received_at=datetime.now(UTC),
    )

    result = service.process_message(inbound)

    assert not result.accepted
    assert "does not match" in result.error


def test_invalid_json_is_rejected_without_crashing(tmp_path):
    _, service = make_service(tmp_path)
    inbound = InboundMessage(
        topic="iot-health/v1/devices/health-node-01/telemetry",
        payload=b"{not-json",
        received_at=datetime.now(UTC),
    )

    assert service.process_message(inbound).accepted is False
    assert service.metrics()["rejected"] == 1


def test_payload_larger_than_configured_cap_is_rejected(tmp_path):
    _, service = make_service(tmp_path, max_payload_bytes=128)
    inbound = InboundMessage(
        topic="iot-health/v1/devices/health-node-01/telemetry",
        payload=b"x" * 129,
        received_at=datetime.now(UTC),
    )

    result = service.process_message(inbound)

    assert result.accepted is False
    assert result.error == "MQTT payload exceeds 128 bytes"
    assert service.metrics()["rejected"] == 1


def test_fall_event_is_deduplicated_by_event_id(tmp_path):
    database, service = make_service(tmp_path)
    payload = {
        "schema": "health.event.v1",
        "device_id": "health-node-01",
        "boot_id": "boot-1",
        "event_id": "boot-1:9:fall",
        "seq": 9,
        "uptime_ms": 9000,
        "type": "fall_suspected_demo",
    }

    first = service.process_message(message("event", payload))
    second = service.process_message(message("event", payload))

    alerts = database.list_alerts(state="active")
    assert first.accepted and second.duplicate
    assert len(alerts) == 1
    assert alerts[0]["occurrence_count"] == 1


def test_threshold_notification_sends_only_on_open_and_reopen(
    tmp_path, clone_payload
):
    notifier = RecordingNotifier()
    database, service = make_service(tmp_path, notifier=notifier)
    start = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)

    first = clone_payload()
    first["vitals"]["spo2_pct"] = 90.0
    touch = clone_payload()
    touch["seq"] = 2
    touch["uptime_ms"] = 2000
    touch["vitals"]["spo2_pct"] = 89.0
    recovered = clone_payload()
    recovered["seq"] = 3
    recovered["uptime_ms"] = 3000
    recovered["vitals"]["spo2_pct"] = 95.0
    reopened = clone_payload()
    reopened["seq"] = 4
    reopened["uptime_ms"] = 4000
    reopened["vitals"]["spo2_pct"] = 90.0

    assert service.process_message(message("telemetry", first, start)).accepted
    assert service.process_message(
        message("telemetry", touch, start + timedelta(seconds=1))
    ).accepted
    assert service.process_message(
        message("telemetry", recovered, start + timedelta(seconds=2))
    ).accepted
    assert service.process_message(
        message("telemetry", reopened, start + timedelta(seconds=3))
    ).accepted

    assert len(notifier.notifications) == 2
    assert all(
        notification.rule_id == "demo_low_spo2"
        for notification in notifier.notifications
    )
    assert database.list_alerts(state="resolved")[0]["occurrence_count"] == 2
    assert database.list_alerts(state="open")[0]["occurrence_count"] == 1


def test_each_new_fall_event_notifies_but_duplicate_does_not(tmp_path):
    notifier = RecordingNotifier()
    _, service = make_service(tmp_path, notifier=notifier)
    first_event = {
        "schema": "health.event.v1",
        "device_id": "health-node-01",
        "boot_id": "boot-1",
        "event_id": "boot-1:30:fall",
        "seq": 30,
        "uptime_ms": 30_000,
        "type": "fall_suspected_demo",
    }
    second_event = {
        **first_event,
        "event_id": "boot-1:31:fall",
        "seq": 31,
        "uptime_ms": 31_000,
    }

    assert service.process_message(message("event", first_event)).accepted
    duplicate = service.process_message(message("event", first_event))
    assert duplicate.accepted and duplicate.duplicate
    assert service.process_message(message("event", second_event)).accepted

    assert len(notifier.notifications) == 2
    assert all(
        notification.rule_id == "fall_suspected_demo"
        for notification in notifier.notifications
    )


def test_notification_enqueue_failure_never_rejects_valid_alert(tmp_path):
    notifier = RecordingNotifier(error=RuntimeError("simulated notifier failure"))
    database, service = make_service(tmp_path, notifier=notifier)
    event = {
        "schema": "health.event.v1",
        "device_id": "health-node-01",
        "boot_id": "boot-1",
        "event_id": "boot-1:40:fall",
        "seq": 40,
        "uptime_ms": 40_000,
        "type": "fall_suspected_demo",
    }

    result = service.process_message(message("event", event))

    assert result.accepted and not result.duplicate
    assert len(database.list_alerts(state="active")) == 1
    assert service.metrics()["processing_errors"] == 0


def test_notification_queue_full_never_rejects_valid_alert(tmp_path):
    notifier = RecordingNotifier(accepted=False)
    database, service = make_service(tmp_path, notifier=notifier)
    event = {
        "schema": "health.event.v1",
        "device_id": "health-node-01",
        "boot_id": "boot-1",
        "event_id": "boot-1:41:fall",
        "seq": 41,
        "uptime_ms": 41_000,
        "type": "fall_suspected_demo",
    }

    result = service.process_message(message("event", event))

    assert result.accepted and not result.duplicate
    assert len(database.list_alerts(state="active")) == 1
    assert len(notifier.notifications) == 1
    assert service.metrics()["accepted"] == 1
    assert service.metrics()["processing_errors"] == 0


def test_same_event_id_is_independent_across_devices(tmp_path):
    database, service = make_service(tmp_path)
    base = {
        "schema": "health.event.v1",
        "boot_id": "boot-1",
        "event_id": "shared-event-id",
        "seq": 9,
        "uptime_ms": 9000,
        "type": "fall_suspected_demo",
    }
    event_a = {**base, "device_id": "device-a"}
    event_b = {**base, "device_id": "device-b"}

    first = service.process_message(message("event", event_a))
    second = service.process_message(message("event", event_b))

    assert first.accepted and not first.duplicate
    assert second.accepted and not second.duplicate
    alerts = database.list_alerts(state="active")
    assert {alert["device_id"] for alert in alerts} == {"device-a", "device-b"}


def test_new_fall_event_reopens_acknowledged_alert(tmp_path):
    database, service = make_service(tmp_path)
    first_event = {
        "schema": "health.event.v1",
        "device_id": "health-node-01",
        "boot_id": "boot-1",
        "event_id": "boot-1:20:fall",
        "seq": 20,
        "uptime_ms": 20_000,
        "type": "fall_suspected_demo",
    }
    second_event = {
        **first_event,
        "event_id": "boot-1:21:fall",
        "seq": 21,
        "uptime_ms": 21_000,
    }

    assert service.process_message(message("event", first_event)).accepted
    alert = database.list_alerts(state="active")[0]
    acknowledged = database.acknowledge_alert(alert["id"], "Tri", "Đã xem")
    assert acknowledged["state"] == "acknowledged"

    result = service.process_message(message("event", second_event))
    reopened = database.get_alert(alert["id"])

    assert result.accepted and not result.duplicate
    assert reopened["state"] == "open"
    assert reopened["occurrence_count"] == 2
    assert reopened["acknowledged_at"] is None
    assert reopened["acknowledged_by"] is None
    assert reopened["acknowledgement_note"] is None


def test_status_updates_online_state(tmp_path):
    database, service = make_service(tmp_path)
    online = {
        "schema": "health.status.v1",
        "device_id": "health-node-01",
        "boot_id": "boot-1",
        "seq": 1,
        "uptime_ms": 1000,
        "online": True,
        "reason": "connected",
        "system": {"rssi_dbm": -64, "free_heap": 28000, "fw": "0.1.0", "faults": []},
    }
    offline = {
        **online,
        "seq": 2,
        "uptime_ms": 2000,
        "online": False,
        "reason": "lwt",
    }

    assert service.process_message(message("status", online)).accepted
    result = service.process_message(message("status", offline))

    assert result.accepted
    device = database.get_device("health-node-01")
    assert device["online"] is False
    assert device["status_reason"] == "lwt"


def test_unknown_offline_lwt_is_stale_and_does_not_create_device(tmp_path):
    database, service = make_service(tmp_path)
    payload = {
        "schema": "health.status.v1",
        "device_id": "health-node-01",
        "boot_id": "boot-old",
        "seq": 9,
        "uptime_ms": 9000,
        "online": False,
        "reason": "connection_lost",
        "system": {"rssi_dbm": None, "free_heap": None, "fw": "0.1.0", "faults": []},
    }

    result = service.process_message(message("status", payload))

    assert result.accepted and result.disposition == "stale"
    assert database.get_device("health-node-01") is None
    assert service.metrics()["stale"] == 1


def test_old_lwt_after_new_boot_cannot_rewind_current_session(tmp_path, clone_payload):
    database, service = make_service(tmp_path)
    start = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    online_a = {
        "schema": "health.status.v1",
        "device_id": "health-node-01",
        "boot_id": "boot-a",
        "seq": 1,
        "uptime_ms": 1000,
        "online": True,
        "reason": "connected",
        "system": {"rssi_dbm": -60, "free_heap": 30000, "fw": "0.1.0", "faults": []},
    }
    telemetry_b = clone_payload()
    telemetry_b["boot_id"] = "boot-b"
    telemetry_b["seq"] = 1
    old_lwt = {**online_a, "seq": 2, "online": False, "reason": "connection_lost"}

    assert service.process_message(message("status", online_a, start)).disposition == "accepted"
    assert service.process_message(
        message("telemetry", telemetry_b, start + timedelta(seconds=1))
    ).disposition == "accepted"
    restarted = IngestionService(
        database,
        RuleEngine(database, DemoRuleSettings(hold_seconds=0.0)),
    )
    result = restarted.process_message(
        message("status", old_lwt, start + timedelta(seconds=2))
    )

    device = database.get_device("health-node-01")
    assert result.disposition == "stale"
    assert device["boot_id"] == "boot-b"
    assert device["online"] is True


def test_current_boot_lwt_uses_connection_epoch_not_payload_sequence(tmp_path):
    database, service = make_service(tmp_path)
    start = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

    def status(seq, online, reason):
        return {
            "schema": "health.status.v1",
            "device_id": "health-node-01",
            "boot_id": "boot-1",
            "seq": seq,
            "uptime_ms": seq * 1000,
            "online": online,
            "reason": reason,
            "system": {
                "rssi_dbm": -60 if online else None,
                "free_heap": 30000 if online else None,
                "fw": "0.3.1",
                "faults": [],
            },
        }

    assert service.process_message(
        message("status", status(10, True, "connected"), start)
    ).disposition == "accepted"

    # Firmware builds the retained LWT before publishing online=connected, so
    # its payload sequence is exactly one lower than that connection's status.
    first_lwt = service.process_message(
        message(
            "status",
            status(9, False, "mqtt_lost"),
            start + timedelta(seconds=1),
        )
    )
    assert first_lwt.disposition == "accepted"
    assert database.get_device("health-node-01")["online"] is False

    assert service.process_message(
        message(
            "status",
            status(20, True, "connected"),
            start + timedelta(seconds=2),
        )
    ).disposition == "accepted"
    assert database.get_device("health-node-01")["online"] is True

    late_old_lwt = service.process_message(
        message(
            "status",
            status(9, False, "mqtt_lost"),
            start + timedelta(seconds=3),
        )
    )
    assert late_old_lwt.disposition == "out_of_order"
    assert database.get_device("health-node-01")["online"] is True

    current_lwt = service.process_message(
        message(
            "status",
            status(19, False, "mqtt_lost"),
            start + timedelta(seconds=4),
        )
    )
    assert current_lwt.disposition == "accepted"
    assert database.get_device("health-node-01")["online"] is False

    with database.connection() as connection:
        session = connection.execute(
            """
            SELECT connection_epoch, expected_lwt_seq, last_status_seq
            FROM device_sessions
            WHERE device_id = ? AND boot_id = ?
            """,
            ("health-node-01", "boot-1"),
        ).fetchone()
    assert dict(session) == {
        "connection_epoch": 2,
        "expected_lwt_seq": 19,
        "last_status_seq": 20,
    }


def test_migrated_unknown_status_watermark_cannot_rewind_online_state(tmp_path):
    database, service = make_service(tmp_path)
    start = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    online = {
        "schema": "health.status.v1",
        "device_id": "health-node-01",
        "boot_id": "boot-1",
        "seq": 10,
        "uptime_ms": 10000,
        "online": True,
        "reason": "heartbeat",
        "system": {"rssi_dbm": -60, "free_heap": 30000, "fw": "0.3.1", "faults": []},
    }
    assert service.process_message(message("status", online, start)).accepted

    with database.connection() as connection:
        connection.execute("DROP TABLE device_sessions")
        connection.commit()
    database.initialize()
    restarted = IngestionService(
        database,
        RuleEngine(database, DemoRuleSettings(hold_seconds=0.0)),
    )

    unanchored_offline = {
        **online,
        "seq": 1,
        "online": False,
        "reason": "simulator_complete",
    }
    result = restarted.process_message(
        message("status", unanchored_offline, start + timedelta(seconds=1))
    )
    assert result.disposition == "out_of_order"
    assert database.get_device("health-node-01")["online"] is True

    heartbeat = {**online, "seq": 11}
    assert restarted.process_message(
        message("status", heartbeat, start + timedelta(seconds=2))
    ).disposition == "accepted"
    ordered_offline = {
        **heartbeat,
        "seq": 12,
        "online": False,
        "reason": "simulator_complete",
    }
    assert restarted.process_message(
        message("status", ordered_offline, start + timedelta(seconds=3))
    ).disposition == "accepted"
    assert database.get_device("health-node-01")["online"] is False


def test_sequence_is_classified_independently_per_stream(tmp_path, clone_payload):
    database, service = make_service(tmp_path)
    start = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    status = {
        "schema": "health.status.v1",
        "device_id": "health-node-01",
        "boot_id": "boot-1",
        "seq": 10,
        "uptime_ms": 1000,
        "online": True,
        "reason": "connected",
        "system": {"rssi_dbm": -60, "free_heap": 30000, "fw": "0.1.0", "faults": []},
    }
    telemetry = clone_payload()
    telemetry["boot_id"] = "boot-1"
    telemetry["seq"] = 2

    assert service.process_message(message("status", status, start)).disposition == "accepted"
    assert service.process_message(
        message("telemetry", telemetry, start + timedelta(seconds=1))
    ).disposition == "accepted"
    event = {
        "schema": "health.event.v1",
        "device_id": "health-node-01",
        "boot_id": "boot-1",
        "event_id": "evt-stream-1",
        "seq": 1,
        "uptime_ms": 1500,
        "type": "fall_suspected_demo",
    }
    assert service.process_message(
        message("event", event, start + timedelta(milliseconds=1500))
    ).disposition == "accepted"

    older_telemetry = json.loads(json.dumps(telemetry))
    older_telemetry["seq"] = 1
    older_status = {**status, "seq": 9, "online": False, "reason": "late_lwt"}
    older_event = {**event, "event_id": "evt-stream-0", "seq": 0}
    telemetry_result = service.process_message(
        message("telemetry", older_telemetry, start + timedelta(seconds=2))
    )
    status_result = service.process_message(
        message("status", older_status, start + timedelta(seconds=3))
    )
    event_result = service.process_message(
        message("event", older_event, start + timedelta(seconds=4))
    )

    assert telemetry_result.disposition == "out_of_order"
    assert status_result.disposition == "out_of_order"
    assert event_result.disposition == "out_of_order"
    assert len(database.telemetry_history("health-node-01")) == 1
    assert database.get_device("health-node-01")["online"] is True
    assert service.metrics()["out_of_order"] == 3


def test_fault_after_telemetry_insert_rolls_back_and_retry_opens_one_alert(
    tmp_path, clone_payload, monkeypatch
):
    database, service = make_service(tmp_path, hold_seconds=0.0)
    payload = clone_payload()
    payload["vitals"]["spo2_pct"] = 88.0
    original_evaluate = service.rules.evaluate

    def fail_after_insert(*_args, **_kwargs):
        raise RuntimeError("fault after telemetry insert")

    monkeypatch.setattr(service.rules, "evaluate", fail_after_insert)
    with pytest.raises(RuntimeError, match="fault after telemetry insert"):
        service.process_message(message("telemetry", payload))

    assert database.get_device("health-node-01") is None
    assert database.telemetry_history("health-node-01") == []
    assert database.list_alerts() == []

    monkeypatch.setattr(service.rules, "evaluate", original_evaluate)
    restarted = IngestionService(
        database,
        RuleEngine(database, DemoRuleSettings(hold_seconds=0.0)),
    )
    retry = restarted.process_message(message("telemetry", payload))

    assert retry.disposition == "accepted"
    assert len(database.telemetry_history("health-node-01")) == 1
    assert len(database.list_alerts(state="active")) == 1
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM alert_history").fetchone()[0] == 1


def test_fault_after_alert_write_restores_rule_state_and_notifies_only_after_commit(
    tmp_path, clone_payload, monkeypatch
):
    notifier = RecordingNotifier()
    database, service = make_service(
        tmp_path, hold_seconds=0.0, notifier=notifier
    )
    payload = clone_payload()
    payload["vitals"]["spo2_pct"] = 88.0
    original_open = database.open_or_touch_alert

    def fail_after_alert_write(*args, **kwargs):
        original_open(*args, **kwargs)
        raise RuntimeError("fault before outer commit")

    monkeypatch.setattr(database, "open_or_touch_alert", fail_after_alert_write)
    with pytest.raises(RuntimeError, match="fault before outer commit"):
        service.process_message(message("telemetry", payload))

    snapshot = service.rules.snapshot_state()
    assert snapshot.pending_since == {}
    assert snapshot.last_rule_sample == {}
    assert snapshot.fall_recovery_since == {}
    assert snapshot.fall_recovery_last_sample == {}
    assert database.telemetry_history("health-node-01") == []
    assert database.list_alerts() == []
    assert notifier.notifications == []

    monkeypatch.setattr(database, "open_or_touch_alert", original_open)
    restarted = IngestionService(
        database,
        RuleEngine(database, DemoRuleSettings(hold_seconds=0.0)),
        notifier=notifier,
    )
    assert restarted.process_message(message("telemetry", payload)).accepted
    assert len(notifier.notifications) == 1


def test_protocol_metadata_is_counted_without_changing_payload_contract(
    tmp_path, valid_telemetry_payload
):
    _, service = make_service(tmp_path)
    inbound = message("telemetry", valid_telemetry_payload)
    inbound = InboundMessage(
        topic=inbound.topic,
        payload=inbound.payload,
        received_at=inbound.received_at,
        qos=1,
        retain=True,
        dup=True,
    )

    assert service.process_message(inbound).accepted
    metrics = service.metrics()
    assert metrics["qos1_messages"] == 1
    assert metrics["retained_messages"] == 1
    assert metrics["mqtt_dup_flagged"] == 1
    assert metrics["payload_bytes"] == len(inbound.payload)
