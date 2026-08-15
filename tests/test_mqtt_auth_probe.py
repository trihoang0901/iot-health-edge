import base64
import io
import json

import pytest

from edge import mqtt_auth_probe


class ReasonCode:
    def __init__(self, value: int) -> None:
        self.value = value


class FakeClient:
    def __init__(self, reason_code: int | None) -> None:
        self.reason_code = reason_code
        self.on_connect = None
        self.credentials = None
        self.loop_started = False
        self.disconnect_called = False

    def username_pw_set(self, username: str, password: str) -> None:
        self.credentials = (username, password)

    def connect_async(self, host: str, port: int, keepalive: int) -> None:
        self.endpoint = (host, port, keepalive)

    def loop_start(self) -> None:
        self.loop_started = True
        if self.reason_code is not None:
            self.on_connect(self, None, None, ReasonCode(self.reason_code), None)

    def disconnect(self) -> None:
        self.disconnect_called = True

    def loop_stop(self) -> None:
        self.loop_started = False


def request(password: str = "dummy-node-password") -> mqtt_auth_probe.ProbeRequest:
    return mqtt_auth_probe.ProbeRequest(
        host="mosquitto",
        port=1883,
        username="health_node",
        password=password,
        timeout_seconds=0.01,
    )


def test_probe_accepts_valid_credentials_without_publish_or_subscribe():
    client = FakeClient(reason_code=0)

    result = mqtt_auth_probe.probe(request(), client_factory=lambda *args, **kwargs: client)

    assert result == mqtt_auth_probe.AUTH_ACCEPTED
    assert client.credentials == ("health_node", "dummy-node-password")
    assert client.endpoint == ("mosquitto", 1883, 10)
    assert client.disconnect_called is True
    assert not hasattr(client, "will")
    assert not hasattr(client, "published")
    assert not hasattr(client, "subscribed")


def test_probe_distinguishes_auth_rejection_from_transport_failure():
    # Callback API v2 normalizes MQTT 3.1.1 CONNACK=5 to reason code 135.
    rejected = FakeClient(reason_code=135)
    timed_out = FakeClient(reason_code=None)

    assert (
        mqtt_auth_probe.probe(request(), client_factory=lambda *args, **kwargs: rejected)
        == mqtt_auth_probe.AUTH_REJECTED
    )
    assert (
        mqtt_auth_probe.probe(request(), client_factory=lambda *args, **kwargs: timed_out)
        == mqtt_auth_probe.PROBE_FAILED
    )


def test_main_never_echoes_password_or_raw_exception(monkeypatch, capsys):
    password = "sensitive-dummy-password"
    payload = json.dumps(
        {
            "host": "mosquitto",
            "port": 1883,
            "username": "health_node",
            "password": password,
            "timeout_seconds": 0.01,
        }
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))

    def fail(_request):
        raise RuntimeError(f"transport failed with {password}")

    monkeypatch.setattr(mqtt_auth_probe, "probe", fail)

    assert mqtt_auth_probe.main() == mqtt_auth_probe.PROBE_FAILED
    captured = capsys.readouterr()
    assert password not in captured.out
    assert password not in captured.err
    assert "transport failed" not in captured.out
    assert "transport failed" not in captured.err


@pytest.mark.parametrize("bom_prefix", ["\ufeff", "\u00ef\u00bb\u00bf"])
def test_main_accepts_base64_stdin_without_putting_secret_in_arguments(
    monkeypatch, bom_prefix
):
    password = "dummy-password-with-special-characters!@^"
    raw = json.dumps(
        {
            "host": "mosquitto",
            "port": 1883,
            "username": "health_node",
            "password": password,
            "timeout_seconds": 5,
        }
    ).encode()
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(bom_prefix + base64.b64encode(raw).decode("ascii") + "\r\n"),
    )
    captured = {}

    def accept(probe_request):
        captured["request"] = probe_request
        return mqtt_auth_probe.AUTH_ACCEPTED

    monkeypatch.setattr(mqtt_auth_probe, "probe", accept)

    assert mqtt_auth_probe.main(["--base64"]) == mqtt_auth_probe.AUTH_ACCEPTED
    assert captured["request"].password == password
