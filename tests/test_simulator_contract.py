from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from edge.config import DemoRuleSettings
from edge.db import Database
from edge.rules import RuleEngine
from edge.service import InboundMessage, IngestionService
from simulator import mqtt_simulator
from simulator.mqtt_simulator import (
    Message,
    MqttPublisher,
    RuntimeConfig,
    ScenarioStream,
    main,
    parse_args,
)


def test_fall_simulator_stream_matches_edge_contract(tmp_path):
    database = Database(tmp_path / "simulator.db")
    database.initialize()
    service = IngestionService(
        database,
        RuleEngine(database, DemoRuleSettings(hold_seconds=0.0)),
    )
    stream = ScenarioStream(
        RuntimeConfig(
            broker="127.0.0.1",
            port=1883,
            username=None,
            password=None,
            device_id="health-node-01",
            scenario="fall",
            interval=1.0,
            count=8,
            seed=42,
            tls=False,
            ca_cert=None,
            connect_timeout=1.0,
            dry_run=True,
        )
    )

    results = [
        service.process_message(
            InboundMessage(
                topic=item.topic,
                payload=json.dumps(item.payload, allow_nan=False).encode(),
                received_at=datetime.now(UTC),
            )
        )
        for item in stream.messages()
    ]

    assert all(result.accepted for result in results)
    fall_alerts = [
        alert
        for alert in database.list_alerts(limit=20)
        if alert["rule_id"] == "fall_suspected_demo"
    ]
    assert len(fall_alerts) == 1
    assert fall_alerts[0]["occurrence_count"] == 1


def test_publisher_raises_when_qos_ack_times_out():
    class PublishInfo:
        rc = 0
        timeout = None

        def wait_for_publish(self, timeout):
            self.timeout = timeout

        def is_published(self):
            return False

    class Client:
        def __init__(self):
            self.info = PublishInfo()

        def publish(self, topic, payload, qos, retain):
            return self.info

    publisher = MqttPublisher.__new__(MqttPublisher)
    publisher.mqtt = SimpleNamespace(MQTT_ERR_SUCCESS=0)
    publisher.client = Client()
    outbound = Message(
        topic="iot-health/v1/devices/health-node-01/event",
        payload={"schema": "health.event.v1"},
        qos=1,
    )

    with pytest.raises(RuntimeError, match="broker xac nhan"):
        publisher.publish(outbound)

    assert publisher.client.info.timeout == 5.0


def test_main_rejects_invalid_boolean_environment(monkeypatch, capsys):
    monkeypatch.setenv("MQTT_TLS", "sometimes")

    assert main(["--dry-run", "--count", "1"]) == 2
    assert "MQTT_TLS must be a boolean value" in capsys.readouterr().err


def test_main_dry_run_prints_machine_readable_stream(monkeypatch, capsys):
    monkeypatch.delenv("MQTT_TLS", raising=False)

    assert main(["--dry-run", "--count", "1", "--seed", "7"]) == 0
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert len(output) == 3
    assert output[0]["payload"]["online"] is True
    assert output[1]["topic"].endswith("/telemetry")
    assert output[1]["payload"]["schema"] == "health.telemetry.v2"
    assert output[2]["payload"]["online"] is False


def test_normal_scenario_emits_strict_v2_environment_contract(monkeypatch, capsys):
    monkeypatch.delenv("MQTT_TLS", raising=False)

    assert main(["--dry-run", "--scenario", "normal", "--count", "1"]) == 0
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    telemetry = output[1]["payload"]

    assert telemetry["schema"] == "health.telemetry.v2"
    assert set(telemetry["vitals"]) == {"heart_rate_bpm", "spo2_pct"}
    assert set(telemetry["environment"]) == {"ambient_temp_c", "humidity_pct"}
    assert -40 <= telemetry["environment"]["ambient_temp_c"] <= 80
    assert 0 <= telemetry["environment"]["humidity_pct"] <= 100
    assert telemetry["quality"]["ambient_temp_valid"] is True
    assert telemetry["quality"]["humidity_valid"] is True
    assert "skin_temp_c" not in telemetry["vitals"]
    assert "skin_temp_valid" not in telemetry["quality"]
    assert telemetry["system"]["fw"] == "simulator-1.1.0"


def test_dht_fault_scenario_keeps_publishing_null_environment(monkeypatch, capsys):
    monkeypatch.delenv("MQTT_TLS", raising=False)

    assert main(["--dry-run", "--scenario", "dht_fault", "--count", "2"]) == 0
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    telemetry_messages = [
        item["payload"] for item in output if item["topic"].endswith("/telemetry")
    ]

    assert len(telemetry_messages) == 2
    for telemetry in telemetry_messages:
        assert telemetry["schema"] == "health.telemetry.v2"
        assert telemetry["environment"] == {
            "ambient_temp_c": None,
            "humidity_pct": None,
        }
        assert telemetry["quality"]["ambient_temp_valid"] is False
        assert telemetry["quality"]["humidity_valid"] is False
        assert "dht11_unavailable" in telemetry["system"]["faults"]


@pytest.mark.parametrize(
    "arguments",
    [
        ["--dry-run", "--device-id", "INVALID"],
        ["--dry-run", "--port", "0"],
        ["--dry-run", "--interval", "0"],
        ["--dry-run", "--count", "-1"],
    ],
)
def test_parse_args_rejects_invalid_cli_values(monkeypatch, arguments):
    monkeypatch.delenv("MQTT_TLS", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        parse_args(arguments)

    assert exc_info.value.code == 2


def test_parse_args_rejects_ca_certificate_without_tls(monkeypatch, tmp_path):
    monkeypatch.delenv("MQTT_TLS", raising=False)
    ca_cert = tmp_path / "ca.pem"
    ca_cert.touch()

    with pytest.raises(SystemExit) as exc_info:
        parse_args(["--dry-run", "--ca-cert", str(ca_cert)])

    assert exc_info.value.code == 2


def test_main_reports_publisher_runtime_error(monkeypatch, capsys):
    monkeypatch.delenv("MQTT_TLS", raising=False)
    config = RuntimeConfig(
        broker="127.0.0.1",
        port=1883,
        username="simulator",
        password="test-password",
        device_id="health-node-01",
        scenario="normal",
        interval=1.0,
        count=1,
        seed=42,
        tls=False,
        ca_cert=None,
        connect_timeout=1.0,
        dry_run=False,
    )

    class FailingPublisher:
        is_connected = False

        def __init__(self, _config, _stream):
            self.closed = False

        def connect(self):
            raise RuntimeError("simulated broker failure")

        def close(self):
            self.closed = True

    monkeypatch.setattr(mqtt_simulator, "parse_args", lambda _argv: config)
    monkeypatch.setattr(mqtt_simulator, "MqttPublisher", FailingPublisher)

    assert mqtt_simulator.main([]) == 1
    assert "simulated broker failure" in capsys.readouterr().err
