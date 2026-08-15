from __future__ import annotations

import base64
import binascii
import json
import sys
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from paho.mqtt import client as mqtt


AUTH_ACCEPTED = 0
AUTH_REJECTED = 16
PROBE_FAILED = 17
MAX_INPUT_CHARS = 16_384


@dataclass(frozen=True)
class ProbeRequest:
    host: str
    port: int
    username: str
    password: str
    timeout_seconds: float = 5.0


def _reason_value(reason_code: object) -> int:
    value = getattr(reason_code, "value", reason_code)
    return int(value)  # type: ignore[arg-type]


def probe(
    request: ProbeRequest,
    *,
    client_factory: Callable[..., Any] | None = None,
) -> int:
    """Perform an MQTT CONNECT-only credential check without logging secrets."""
    completed = threading.Event()
    result_code: int | None = None
    client: Any | None = None
    loop_started = False

    def on_connect(
        _client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        nonlocal result_code
        try:
            result_code = _reason_value(reason_code)
        except (TypeError, ValueError):
            result_code = None
        finally:
            completed.set()

    try:
        factory = client_factory or mqtt.Client
        client = factory(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"health-node-auth-probe-{uuid.uuid4().hex[:12]}",
            protocol=mqtt.MQTTv311,
            reconnect_on_failure=False,
        )
        client.username_pw_set(request.username, request.password)
        client.on_connect = on_connect
        client.connect_async(request.host, request.port, keepalive=10)
        client.loop_start()
        loop_started = True

        if not completed.wait(request.timeout_seconds):
            return PROBE_FAILED
        if result_code == 0:
            return AUTH_ACCEPTED
        # Callback API v2 reports MQTT 3.1.1 auth failures using the
        # corresponding MQTT 5 reason codes (134/135).
        if result_code in {4, 5, 134, 135}:
            return AUTH_REJECTED
        return PROBE_FAILED
    except Exception:
        return PROBE_FAILED
    finally:
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
            if loop_started:
                try:
                    client.loop_stop()
                except Exception:
                    pass


def _parse_request(raw: str) -> ProbeRequest:
    if len(raw) > MAX_INPUT_CHARS:
        raise ValueError("input too large")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("input must be an object")

    host = payload.get("host")
    port = payload.get("port")
    username = payload.get("username")
    password = payload.get("password")
    timeout_seconds = payload.get("timeout_seconds", 5.0)
    if not isinstance(host, str) or not host or len(host) > 253:
        raise ValueError("invalid host")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("invalid port")
    if not isinstance(username, str) or not username:
        raise ValueError("invalid username")
    if not isinstance(password, str) or not password:
        raise ValueError("invalid password")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not 0 < float(timeout_seconds) <= 30
    ):
        raise ValueError("invalid timeout")
    return ProbeRequest(
        host=host,
        port=port,
        username=username,
        password=password,
        timeout_seconds=float(timeout_seconds),
    )


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        raw = sys.stdin.read((MAX_INPUT_CHARS * 2) + 1)
        if arguments == ["--base64"]:
            encoded = raw.strip()
            for bom_prefix in ("\ufeff", "\u00ef\u00bb\u00bf"):
                if encoded.startswith(bom_prefix):
                    encoded = encoded[len(bom_prefix) :]
                    break
            raw = base64.b64decode(encoded, validate=True).decode("utf-8")
        elif arguments:
            return PROBE_FAILED
        request = _parse_request(raw)
        return probe(request)
    except (binascii.Error, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return PROBE_FAILED
    except Exception:
        return PROBE_FAILED


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
