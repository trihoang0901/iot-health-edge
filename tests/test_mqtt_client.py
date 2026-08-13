from __future__ import annotations

import pytest

from edge.config import Settings
from edge.mqtt_client import EdgeMqttClient


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
