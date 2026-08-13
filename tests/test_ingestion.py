from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

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


def test_duplicate_telemetry_does_not_rewind_device_liveness(tmp_path, clone_payload):
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

    assert replay.accepted and replay.duplicate
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
    payload = {
        "schema": "health.status.v1",
        "device_id": "health-node-01",
        "boot_id": "boot-1",
        "seq": 2,
        "uptime_ms": 2000,
        "online": False,
        "reason": "lwt",
        "system": {"rssi_dbm": -64, "free_heap": 28000, "fw": "0.1.0", "faults": []},
    }

    result = service.process_message(message("status", payload))

    assert result.accepted
    device = database.get_device("health-node-01")
    assert device["online"] is False
    assert device["status_reason"] == "lwt"
