"""Launcher Doctor MQTT authentication/ACL probe.

The password is read only from a temporary process environment variable. It is
never accepted as an argument or printed.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import uuid

import paho.mqtt.client as mqtt


def _reason_is_failure(reason_code: object | None) -> bool:
    """Read Paho v2 MQTT 5 ReasonCode objects without coercing them to int."""
    return bool(getattr(reason_code, "is_failure", False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--device-id", required=True)
    args = parser.parse_args()

    password = os.environ.get("IOT_HEALTH_DOCTOR_MQTT_PASSWORD")
    if not password:
        return 2

    connected = threading.Event()
    subscribed = threading.Event()
    published = threading.Event()
    failure: list[str] = []
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"health-edge-doctor-{uuid.uuid4().hex[:12]}",
        protocol=mqtt.MQTTv5,
    )
    client.username_pw_set(args.username, password)

    def on_connect(_client, _userdata, _flags, reason_code, _properties):
        if _reason_is_failure(reason_code):
            failure.append("authentication_failed")
            connected.set()
            return
        connected.set()
        _client.subscribe(f"iot-health/v1/devices/{args.device_id}/status", qos=1)

    def on_subscribe(_client, _userdata, _mid, reason_codes, _properties):
        if not reason_codes or any(_reason_is_failure(code) for code in reason_codes):
            failure.append("read_acl_denied")
        subscribed.set()

    def on_publish(_client, _userdata, _mid, reason_code, _properties):
        if _reason_is_failure(reason_code):
            failure.append("write_acl_denied")
        published.set()

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_publish = on_publish
    client.connect(args.host, args.port, keepalive=10)
    client.loop_start()
    try:
        if not connected.wait(5) or failure:
            return 3
        if not subscribed.wait(5) or failure:
            return 4
        topic = f"iot-health/v1/devices/{args.device_id}/command/doctor"
        payload = json.dumps(
            {"schema": "health.doctor.v1", "probe_id": str(uuid.uuid4())},
            separators=(",", ":"),
        )
        info = client.publish(topic, payload, qos=1, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS or not published.wait(5) or failure:
            return 5
        return 0
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    raise SystemExit(main())
