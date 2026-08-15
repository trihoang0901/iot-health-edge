from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient

import simulator.experiment as experiment
from edge.app import DASHBOARD_ASSET_VERSION, _stop_runtime_services, create_app
from edge.db import isoformat_utc
from edge.schemas import TelemetryV3
from edge.service import InboundMessage
from simulator.experiment import PollObservation, SOURCE_FILES, SOURCE_FINGERPRINT_SCOPE


def ingest(client, kind, payload):
    return client.app.state.ingestion.process_message(
        InboundMessage(
            topic=f"iot-health/v1/devices/{payload['device_id']}/{kind}",
            payload=json.dumps(payload).encode(),
            received_at=datetime.now(UTC),
        )
    )


def test_health_and_static_dashboard(client):
    health = client.get("/healthz")
    dashboard = client.get("/")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["mqtt"]["enabled"] is False
    assert "last_error" not in health.json()["mqtt"]
    assert "last_error" not in health.json()["ingestion"]
    assert client.app.state.notifications is None
    assert "notifications" not in health.json()
    assert dashboard.status_code == 200
    assert "Prototype phi lâm sàng" in dashboard.text
    assert dashboard.headers["x-frame-options"] == "DENY"
    assert dashboard.headers["cache-control"] == "no-store"
    assert "__ASSET_VERSION__" not in dashboard.text
    assert f"/static/app.js?v={DASHBOARD_ASSET_VERSION}" in dashboard.text
    static_script = client.get(f"/static/app.js?v={DASHBOARD_ASSET_VERSION}")
    assert static_script.status_code == 200
    assert static_script.headers["cache-control"] == "no-store"


def test_runtime_is_sanitized_and_capabilities_are_truthful(client):
    client.app.state.ingestion._last_error = "password=secret C:\\private\\edge.db"

    runtime = client.get("/api/v1/runtime")
    capabilities = client.get("/api/v1/capabilities")

    assert runtime.status_code == 200
    assert runtime.json()["sanitized"] is True
    assert "last_error" not in runtime.json()["ingestion"]
    assert "secret" not in runtime.text
    assert capabilities.status_code == 200
    assert capabilities.json()["course_track"] == "IoT Protocol"
    assert capabilities.json()["protocol"]["version"] == "3.1.1"
    assert capabilities.json()["claims"]["measured_5g"] is False
    assert capabilities.json()["claims"]["primary_latency_kind"] == (
        "schedule_to_api_polling_upper_bound"
    )
    assert capabilities.json()["claims"]["diagnostic_latency_kind"] == (
        "publish_to_api_polling_upper_bound"
    )
    assert "latency_kind" not in capabilities.json()["claims"]
    assert all(
        profile["network_claim"] == "none"
        for profile in capabilities.json()["profiles"]
    )


def test_experiment_api_lists_only_reconciled_allowlisted_evidence(
    client, monkeypatch
):
    class FakePublisher:
        def __init__(self, _runtime, _stream):
            self.is_connected = False

        def connect(self):
            self.is_connected = True

        def publish(self, _message):
            return None

        def close(self):
            self.is_connected = False

    monkeypatch.setenv("SIMULATOR_MQTT_USERNAME", "simulator")
    monkeypatch.setenv("SIMULATOR_MQTT_PASSWORD", "test-only")
    monkeypatch.setattr(
        experiment,
        "source_provenance",
        lambda: {
            "scope": SOURCE_FINGERPRINT_SCOPE,
            "head_commit": "a" * 40,
            "source_state": "worktree_uncommitted",
            "source_sha256": "b" * 64,
            "source_files": list(SOURCE_FILES),
        },
    )
    monkeypatch.setattr(experiment, "_require_api_ready", lambda _base: None)
    monkeypatch.setattr(experiment, "MqttPublisher", FakePublisher)
    monkeypatch.setattr(
        experiment,
        "_poll_observed",
        lambda *_args, **_kwargs: PollObservation(True, None),
    )
    assert experiment.main(
        [
            "--count",
            "20",
            "--interval",
            "0.001",
            "--run-id",
            "run-api-1",
            "--output-dir",
            str(client.app.state.settings.experiment_evidence_dir),
        ]
    ) == 0

    listed = client.get("/api/v1/experiments")
    detail = client.get("/api/v1/experiments/run-api-1")
    escaped = client.get("/api/v1/experiments/%2E%2E%2Fescape")

    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert detail.status_code == 200
    assert detail.json()["manifest"]["artifact_version"] == "5.0"
    assert detail.json()["manifest"]["claims"]["primary_latency_kind"] == (
        "schedule_to_api_polling_upper_bound"
    )
    assert detail.json()["summary"]["scheduled_observation_ratio"] == 1.0
    assert "source_files" not in detail.text
    assert escaped.status_code in {404, 422}


def test_experiment_api_hides_well_typed_tampered_summary_and_raw(client, monkeypatch):
    test_experiment_api_lists_only_reconciled_allowlisted_evidence(client, monkeypatch)
    run_dir = client.app.state.settings.experiment_evidence_dir / "run-api-1"

    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["scheduled_observation_ratio"] = 0.5
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    assert client.get("/api/v1/experiments/run-api-1").status_code == 404
    assert client.get("/api/v1/experiments").json()["total"] == 0

    # Restore the summary, then alter a numeric raw field without changing its
    # JSON type.  Strict reconciliation must still hide the run.
    summary["scheduled_observation_ratio"] = 1.0
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    samples_path = run_dir / "samples.jsonl"
    samples = [
        json.loads(line)
        for line in samples_path.read_text(encoding="utf-8").splitlines()
    ]
    samples[0]["schedule_slip_ms"] += 10_000.0
    samples_path.write_text(
        "".join(json.dumps(item, separators=(",", ":")) + "\n" for item in samples),
        encoding="utf-8",
    )
    assert client.get("/api/v1/experiments/run-api-1").status_code == 404
    assert client.get("/api/v1/experiments").json()["total"] == 0


def test_enabled_telegram_worker_follows_application_lifecycle(app_settings):
    settings = replace(
        app_settings,
        telegram_enabled=True,
        telegram_bot_token="test-token",
        telegram_chat_id="test-chat",
    )
    app = create_app(settings)
    notifier = app.state.notifications

    assert notifier is not None
    assert notifier.metrics()["worker_alive"] is False
    with TestClient(app) as client:
        assert notifier.metrics()["worker_alive"] is True
        assert client.get("/healthz").json()["status"] == "ok"
    assert notifier.metrics()["worker_alive"] is False


@pytest.mark.parametrize("failing_service", ["mqtt", "ingestion"])
def test_shutdown_always_attempts_all_services(failing_service):
    calls = []

    class StopProbe:
        def __init__(self, name):
            self.name = name

        def stop(self):
            calls.append(self.name)
            if self.name == failing_service:
                raise RuntimeError(f"{self.name} stop failed")

    with pytest.raises(RuntimeError, match=f"{failing_service} stop failed"):
        _stop_runtime_services(
            StopProbe("mqtt"),
            StopProbe("ingestion"),
            StopProbe("notifier"),
        )

    assert calls == ["mqtt", "ingestion", "notifier"]


def test_worker_survives_unexpected_error_and_health_degrades(
    client, monkeypatch, valid_telemetry_payload
):
    ingestion = client.app.state.ingestion
    original_process_message = ingestion.process_message
    should_fail = True

    def fail_once(inbound):
        nonlocal should_fail
        if should_fail:
            should_fail = False
            raise RuntimeError("simulated database failure")
        return original_process_message(inbound)

    def wait_until(predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False

    monkeypatch.setattr(ingestion, "process_message", fail_once)
    assert ingestion.submit(
        "iot-health/v1/devices/health-node-01/telemetry", b"{}"
    )
    assert wait_until(lambda: ingestion.metrics()["processing_errors"] == 1)
    assert ingestion.metrics()["worker_alive"] is True

    assert ingestion.submit(
        "iot-health/v1/devices/health-node-01/telemetry",
        json.dumps(valid_telemetry_payload).encode(),
    )
    assert wait_until(lambda: ingestion.metrics()["accepted"] == 1)

    health = client.get("/healthz")
    runtime = client.get("/api/v1/runtime")
    assert health.status_code == 200
    assert runtime.status_code == 200
    assert health.json()["status"] == "degraded"
    assert runtime.json()["edge"]["status"] == health.json()["status"]
    assert runtime.json()["edge"]["database_healthy"] == health.json()["database"]["healthy"]
    assert health.json()["ingestion"]["worker_alive"] is True
    assert health.json()["ingestion"]["processing_errors"] == 1
    assert runtime.json()["ingestion"]["worker_alive"] is True
    assert runtime.json()["ingestion"]["processing_errors"] == 1


def test_devices_latest_history_and_overview(client, valid_telemetry_payload):
    assert ingest(client, "telemetry", valid_telemetry_payload).accepted

    devices = client.get("/api/v1/devices")
    latest = client.get("/api/v1/devices/health-node-01/latest")
    history = client.get("/api/v1/devices/health-node-01/telemetry")
    overview = client.get("/api/v1/overview?device_id=health-node-01&window=15m")

    assert devices.status_code == 200 and devices.json()["total"] == 1
    assert latest.json()["quality"]["ppg"] == 0.88
    assert latest.json()["wearable"] == {"wrist_surface_temp_c": None}
    assert latest.json()["quality"]["wrist_surface_temp_valid"] is False
    assert history.json()["total"] == 1
    assert overview.json()["device"]["device_id"] == "health-node-01"
    assert overview.json()["non_clinical"] is True
    assert overview.json()["window_minutes"] == 15
    assert overview.json()["history_meta"]["total_available"] == 1
    assert overview.json()["history_meta"]["returned"] == 1
    assert overview.json()["history_meta"]["truncated"] is False
    assert overview.json()["history_meta"]["downsampling"] == "none"
    assert overview.json()["history_meta"]["validity"] == {
        "heart_rate_bpm": {"valid": 1, "total": 1},
        "spo2_pct": {"valid": 1, "total": 1},
        "wrist_surface_temp_c": {"valid": 0, "total": 1},
    }


def test_empty_overview_reports_explicit_zero_coverage_window(client):
    body = client.get("/api/v1/overview?window=15m").json()
    metadata = body["history_meta"]

    assert body["history"] == []
    assert metadata["coverage_from"] is None
    assert metadata["coverage_to"] is None
    assert metadata["total_available"] == metadata["returned"] == 0
    assert metadata["truncated"] is False
    assert metadata["downsampling"] == "none"
    assert metadata["validity"] == {
        "heart_rate_bpm": {"valid": 0, "total": 0},
        "spo2_pct": {"valid": 0, "total": 0},
        "wrist_surface_temp_c": {"valid": 0, "total": 0},
    }
    requested_from = datetime.fromisoformat(
        metadata["requested_from"].replace("Z", "+00:00")
    )
    requested_to = datetime.fromisoformat(
        metadata["requested_to"].replace("Z", "+00:00")
    )
    assert requested_to - requested_from == timedelta(minutes=15)


def test_overview_discloses_last_1000_truncation_and_full_window_validity(
    client, valid_telemetry_v3_payload
):
    database = client.app.state.database
    end = datetime.now(UTC) - timedelta(seconds=1)
    start = end - timedelta(seconds=100)
    with database.transaction() as connection:
        for seq in range(1, 1002):
            payload = json.loads(json.dumps(valid_telemetry_v3_payload))
            payload["seq"] = seq
            payload["uptime_ms"] = seq * 100
            if seq % 10 == 0:
                payload["vitals"]["heart_rate_bpm"] = None
                payload["quality"]["heart_rate_valid"] = False
            if seq % 5 == 0:
                payload["vitals"]["spo2_pct"] = None
                payload["quality"]["spo2_valid"] = False
            if seq % 4 == 0:
                payload["wearable"]["wrist_surface_temp_c"] = None
                payload["quality"]["wrist_surface_temp_valid"] = False
                payload["system"]["faults"] = ["ds18b20_unavailable"]
            received = start + timedelta(milliseconds=seq * 100)
            database.insert_telemetry(
                TelemetryV3.model_validate(payload),
                received,
                json.dumps(payload),
                connection=connection,
            )

    body = client.get(
        "/api/v1/overview?device_id=health-node-01&window=15m"
    ).json()
    metadata = body["history_meta"]

    assert len(body["history"]) == 1000
    assert metadata["total_available"] == 1001
    assert metadata["returned"] == 1000
    assert metadata["truncated"] is True
    assert metadata["downsampling"] == "none"
    assert metadata["coverage_from"] == isoformat_utc(
        start + timedelta(milliseconds=100)
    )
    assert metadata["coverage_to"] == isoformat_utc(
        start + timedelta(milliseconds=100100)
    )
    assert metadata["validity"] == {
        "heart_rate_bpm": {"valid": 901, "total": 1001},
        "spo2_pct": {"valid": 801, "total": 1001},
        "wrist_surface_temp_c": {"valid": 751, "total": 1001},
    }


def test_existing_api_routes_expose_normalized_v2_environment(
    client, valid_telemetry_v2_payload
):
    assert ingest(client, "telemetry", valid_telemetry_v2_payload).accepted

    latest = client.get("/api/v1/devices/health-node-01/latest").json()
    history = client.get(
        "/api/v1/devices/health-node-01/telemetry"
    ).json()["data"]
    overview = client.get(
        "/api/v1/overview?device_id=health-node-01&window=15m"
    ).json()

    for item in (latest, history[0], overview["latest"]):
        assert item["schema"] == item["schema_version"] == "health.telemetry.v2"
        assert item["environment"] == {
            "ambient_temp_c": 28.5,
            "humidity_pct": 63.0,
        }
        assert item["quality"]["ambient_temp_valid"] is True
        assert item["quality"]["humidity_valid"] is True
        assert item["quality"]["wrist_surface_temp_valid"] is False
        assert item["vitals"]["skin_temp_c"] is None
        assert item["wearable"] == {"wrist_surface_temp_c": None}


def test_existing_api_routes_expose_normalized_v3_wearable(
    client, valid_telemetry_v3_payload
):
    assert ingest(client, "telemetry", valid_telemetry_v3_payload).accepted

    latest = client.get("/api/v1/devices/health-node-01/latest").json()
    history = client.get(
        "/api/v1/devices/health-node-01/telemetry"
    ).json()["data"]
    overview = client.get(
        "/api/v1/overview?device_id=health-node-01&window=15m"
    ).json()

    for item in (latest, history[0], overview["latest"]):
        assert item["schema"] == item["schema_version"] == "health.telemetry.v3"
        assert item["wearable"] == {"wrist_surface_temp_c": 32.8}
        assert item["quality"]["wrist_surface_temp_valid"] is True
        assert item["environment"] == {
            "ambient_temp_c": None,
            "humidity_pct": None,
        }
        assert item["quality"]["ambient_temp_valid"] is False
        assert item["quality"]["humidity_valid"] is False
        assert item["vitals"]["skin_temp_c"] is None
        assert item["quality"]["skin_temp_valid"] is False


def test_existing_api_routes_expose_v4_raw_and_confirmed_measurements(
    client, valid_telemetry_v4_payload
):
    assert ingest(client, "telemetry", valid_telemetry_v4_payload).accepted

    latest = client.get("/api/v1/devices/health-node-01/latest").json()
    history = client.get(
        "/api/v1/devices/health-node-01/telemetry"
    ).json()["data"]
    overview = client.get(
        "/api/v1/overview?device_id=health-node-01&window=15m"
    ).json()

    for item in (latest, history[0], overview["latest"]):
        assert item["schema"] == item["schema_version"] == "health.telemetry.v4"
        assert item["vitals"] == {
            "heart_rate_bpm": 76.0,
            "spo2_pct": 97.0,
            "skin_temp_c": None,
        }
        assert item["measurements"]["heart_rate"] == {
            "raw_value": 76.4,
            "confirmed_value": 76.0,
            "valid": True,
            "state": "valid",
            "reason": None,
            "unit": "bpm",
        }
        assert item["measurements"]["spo2"] == {
            "raw_value": 97.2,
            "confirmed_value": 97.0,
            "valid": True,
            "state": "valid",
            "reason": None,
            "unit": "%",
        }
        assert item["quality"]["ppg_state"] == "valid"


def test_v4_unstable_raw_candidate_is_auditable_but_never_exposed_as_confirmed(
    client, valid_telemetry_v4_payload
):
    payload = json.loads(json.dumps(valid_telemetry_v4_payload))
    payload["vitals"].update(
        heart_rate_raw_bpm=180.0,
        heart_rate_bpm=None,
        spo2_raw_pct=97.0,
        spo2_pct=None,
    )
    payload["quality"].update(
        ppg_state="unstable",
        heart_rate_valid=False,
        spo2_valid=False,
    )

    assert ingest(client, "telemetry", payload).accepted
    latest = client.get("/api/v1/devices/health-node-01/latest").json()

    assert latest["vitals"]["heart_rate_bpm"] is None
    assert latest["measurements"]["heart_rate"] == {
        "raw_value": 180.0,
        "confirmed_value": None,
        "valid": False,
        "state": "unstable",
        "reason": "unstable",
        "unit": "bpm",
    }


def test_overview_accepts_plain_minutes_and_rejects_invalid_window(client):
    assert client.get("/api/v1/overview?window=30").status_code == 200
    assert client.get("/api/v1/overview?window=15m").status_code == 200
    assert client.get("/api/v1/overview?window=0m").status_code == 422
    assert client.get("/api/v1/overview?window=2h").status_code == 422
    assert client.get("/api/v1/overview?window=1441m").status_code == 422


def test_ack_is_idempotent_and_does_not_resolve(client):
    event = {
        "schema": "health.event.v1",
        "device_id": "health-node-01",
        "boot_id": "boot-1",
        "event_id": "boot-1:11:fall",
        "seq": 11,
        "uptime_ms": 11000,
        "type": "fall_suspected_demo",
    }
    ingest(client, "event", event)
    alert = client.get("/api/v1/alerts?state=active").json()["data"][0]

    first = client.post(
        f"/api/v1/alerts/{alert['id']}/ack",
        json={"actor": "Tri", "note": "Đã kiểm tra"},
    )
    second = client.post(
        f"/api/v1/alerts/{alert['id']}/ack",
        json={"actor": "Người khác", "note": "Không ghi đè"},
    )

    assert first.status_code == 200
    assert first.json()["state"] == "acknowledged"
    assert "Đã xem" in first.json()["acknowledgement_meaning"]
    assert second.status_code == 200
    assert second.json()["acknowledged_by"] == "Tri"
    assert client.get("/api/v1/alerts?state=active").json()["total"] == 1


def test_ack_resolved_alert_returns_conflict(client):
    event = {
        "schema": "health.event.v1",
        "device_id": "health-node-01",
        "boot_id": "boot-1",
        "event_id": "boot-1:12:fall",
        "seq": 12,
        "uptime_ms": 12000,
        "type": "fall_suspected_demo",
    }
    ingest(client, "event", event)
    alert = client.get("/api/v1/alerts?state=active").json()["data"][0]
    client.app.state.database.resolve_alert(
        "health-node-01", "fall_suspected_demo", datetime.now(UTC)
    )

    response = client.post(
        f"/api/v1/alerts/{alert['id']}/ack", json={"actor": "Tri", "note": ""}
    )

    assert response.status_code == 409


def test_rules_are_explicitly_non_clinical(client):
    response = client.get("/api/v1/rules")

    assert response.status_code == 200
    rule_ids = {rule["rule_id"] for rule in response.json()["data"]}
    assert rule_ids == {
        "demo_low_spo2",
        "demo_high_hr",
        "fall_suspected_demo",
    }
    assert all(rule["non_clinical"] for rule in response.json()["data"])


def test_missing_resources_and_invalid_ack_are_rejected(client):
    assert client.get("/api/v1/devices/missing").status_code == 404
    assert client.get("/api/v1/alerts/missing").status_code == 404
    response = client.post(
        "/api/v1/alerts/missing/ack", json={"actor": "   ", "note": ""}
    )
    assert response.status_code == 422
