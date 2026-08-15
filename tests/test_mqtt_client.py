from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from edge.config import Settings
from edge.mqtt_client import EdgeMqttClient
from edge.schemas import DeviceCommand


ROOT = Path(__file__).resolve().parents[1]


def make_client(tmp_path):
    settings = Settings(
        database_path=tmp_path / "mqtt.db",
        mqtt_enabled=True,
        mqtt_username="edge_reader",
        mqtt_password="test-password",
    )
    return EdgeMqttClient(settings, ingestion=object())


@pytest.mark.parametrize("reason_codes", [[1, 128, 1], [1, 1]])
def test_failed_or_incomplete_suback_never_reports_ready(tmp_path, reason_codes):
    edge_client = make_client(tmp_path)
    edge_client.connected.set()
    edge_client.subscribed.set()
    edge_client._subscribe_mid = 7

    edge_client._on_subscribe(None, None, 7, reason_codes, None)

    health = edge_client.health()
    assert health["connected"] is True
    assert health["subscribed"] is False
    assert "denied" in health["last_error"]


def test_complete_successful_suback_reports_ready(tmp_path):
    edge_client = make_client(tmp_path)
    edge_client.connected.set()
    edge_client._subscribe_mid = 7

    edge_client._on_subscribe(None, None, 7, [1, 1, 1], None)

    health = edge_client.health()
    assert health["connected"] is True
    assert health["subscribed"] is True
    assert health["last_error"] is None


def test_on_message_forwards_mqtt_delivery_metadata(tmp_path):
    class RecordingIngestion:
        def __init__(self):
            self.call = None

        def submit(self, topic, payload, received_at, **metadata):
            self.call = (topic, payload, received_at, metadata)
            return True

    ingestion = RecordingIngestion()
    settings = Settings(
        database_path=tmp_path / "mqtt.db",
        mqtt_enabled=True,
        mqtt_username="edge_reader",
        mqtt_password="test-password",
    )
    edge_client = EdgeMqttClient(settings, ingestion=ingestion)
    mqtt_message = SimpleNamespace(
        topic="iot-health/v1/devices/health-node-01/telemetry",
        payload=b"{\"schema\":\"health.telemetry.v3\"}",
        qos=1,
        retain=True,
        dup=True,
    )

    edge_client._on_message(None, None, mqtt_message)

    topic, payload, received_at, metadata = ingestion.call
    assert topic == mqtt_message.topic
    assert payload == mqtt_message.payload
    assert received_at.tzinfo is not None
    assert metadata == {"qos": 1, "retain": True, "dup": True}


def command() -> DeviceCommand:
    return DeviceCommand(
        schema="health.command.v1",
        device_id="health-node-01",
        target_boot_id="boot-0001",
        command_id=UUID("d442ba67-ab7f-4260-880d-3eb2f03ae0bf"),
        command_session_id=UUID("3bd40a56-6e62-4bdf-9b1e-74f8611dcd5a"),
        action="open_provisioning",
        expires_uptime_ms=31000,
    )


def test_command_publish_is_qos1_non_retained_and_waits_bounded_puback(
    tmp_path, monkeypatch
):
    edge_client = make_client(tmp_path)
    edge_client.connected.set()
    edge_client.subscribed.set()
    captured = {}

    class PublishInfo:
        rc = 0
        mid = 27

        def wait_for_publish(self, timeout):
            captured["timeout"] = timeout

        def is_published(self):
            return True

    def publish(topic, payload, *, qos, retain):
        captured.update(
            topic=topic,
            payload=json.loads(payload),
            qos=qos,
            retain=retain,
        )
        return PublishInfo()

    monkeypatch.setattr(edge_client.client, "publish", publish)

    assert edge_client.publish_command(command(), timeout_seconds=0.25) == 27
    assert captured["topic"] == (
        "iot-health/v1/devices/health-node-01/command/boot-0001"
    )
    assert captured["payload"]["schema"] == "health.command.v1"
    assert captured["payload"]["command_session_id"] == (
        "3bd40a56-6e62-4bdf-9b1e-74f8611dcd5a"
    )
    assert captured["qos"] == 1
    assert captured["retain"] is False
    assert captured["timeout"] == 0.25


def test_command_publish_timeout_is_not_reported_as_published(tmp_path, monkeypatch):
    edge_client = make_client(tmp_path)
    edge_client.connected.set()
    edge_client.subscribed.set()

    class PublishInfo:
        rc = 0
        mid = 28

        def wait_for_publish(self, timeout):
            assert timeout == 0.01

        def is_published(self):
            return False

    monkeypatch.setattr(
        edge_client.client,
        "publish",
        lambda *_args, **_kwargs: PublishInfo(),
    )

    with pytest.raises(RuntimeError, match="PUBACK timed out"):
        edge_client.publish_command(command(), timeout_seconds=0.01)


def test_acl_only_migration_never_invokes_or_rewrites_password_database():
    script = (ROOT / "deploy" / "scripts" / "Initialize-Mosquitto.ps1").read_text(
        encoding="utf-8"
    )
    migration_start = script.index(
        "if ($AclOnly) {\n    $passwordHashBefore ="
    )
    rotation_start = script.index("\ntry {\n    Remove-Item -LiteralPath $stagedPasswordFile")
    migration = script[migration_start:rotation_start]

    assert "mosquitto_passwd" not in migration
    assert "Get-FileHash -Algorithm SHA256 -LiteralPath $passwordFile" in migration
    assert "[System.IO.File]::Replace($stagedAclFile, $aclFile" in migration
    assert "Test-CommandAclPermissions" in migration
    assert "Test-EdgeRuntimeReady" in migration
    assert "exit 0" in migration
    assert "mosquitto_passwd -c /work/passwords.next" in script[rotation_start:]


def test_acl_probe_requires_node_delivery_and_cross_device_suback_denial():
    script = (ROOT / "deploy" / "scripts" / "Initialize-Mosquitto.ps1").read_text(
        encoding="utf-8"
    )
    acl = (ROOT / "deploy" / "mosquitto" / "acl.template").read_text(
        encoding="utf-8"
    )

    node_subscribe = script.index(
        'allowed = subscribe_codes(node, f"iot-health/v1/devices/{device_id}/command/+")'
    )
    edge_publish = script.index("info = edge.publish(", node_subscribe)
    assert node_subscribe < edge_publish
    assert "if not delivered.wait(4):" in script[edge_publish:]
    assert "cross-device command subscription was not denied" in script
    assert "protocol=mqtt.MQTTv5" in script
    assert "topic write iot-health/v1/devices/+/command/+" in acl
    assert "topic read iot-health/v1/devices/__DEVICE_ID__/command/+" in acl
