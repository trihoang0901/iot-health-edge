from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from starlette.testclient import TestClient

from edge.app import DASHBOARD_ASSET_VERSION, _stop_runtime_services, create_app
from edge.service import InboundMessage


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
    assert health.status_code == 200
    assert health.json()["status"] == "degraded"
    assert health.json()["ingestion"]["worker_alive"] is True
    assert health.json()["ingestion"]["processing_errors"] == 1


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
