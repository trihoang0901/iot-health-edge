from __future__ import annotations

import argparse
import getpass
import json
import os
import random
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal


SCENARIOS = (
    "normal",
    "ds18b20_fault",
    "motion_artifact",
    "unstable_ppg",
    "low_spo2",
    "high_hr",
    "fall",
    "offline",
)
DEVICE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
UINT32_MAX = 4_294_967_295
SIMULATOR_FW = "simulator-1.3.0"


@dataclass(frozen=True, slots=True)
class Message:
    topic: str
    payload: dict[str, Any]
    qos: Literal[0, 1]
    retain: bool = False


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    broker: str
    port: int
    username: str | None
    password: str | None
    device_id: str
    scenario: str
    interval: float
    count: int
    seed: int
    tls: bool
    ca_cert: Path | None
    connect_timeout: float
    dry_run: bool


class ScenarioStream:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.boot_id = uuid.uuid4().hex
        self.seq = 0
        self.started_at = time.monotonic()
        self.random = random.Random(config.seed)

    def topic(self, kind: Literal["telemetry", "event", "status"]) -> str:
        return f"iot-health/v1/devices/{self.config.device_id}/{kind}"

    def uptime_ms(self, synthetic_step: int | None = None) -> int:
        if synthetic_step is None:
            value = int((time.monotonic() - self.started_at) * 1000)
        else:
            value = int(synthetic_step * self.config.interval * 1000)
        return min(value, UINT32_MAX)

    def system(self, faults: list[str] | None = None) -> dict[str, Any]:
        return {
            "rssi_dbm": -52,
            "free_heap": 38_000,
            "fw": SIMULATOR_FW,
            "faults": faults or [],
        }

    def status(
        self,
        online: bool,
        reason: str,
        *,
        synthetic_step: int | None = None,
    ) -> Message:
        return Message(
            topic=self.topic("status"),
            payload={
                "schema": "health.status.v1",
                "device_id": self.config.device_id,
                "boot_id": self.boot_id,
                "seq": self.seq,
                "uptime_ms": self.uptime_ms(synthetic_step),
                "online": online,
                "reason": reason,
                "system": self.system(),
            },
            qos=1,
            retain=True,
        )

    def telemetry(self, scenario: str, step: int, total: int | None) -> Message:
        self.seq += 1
        jitter = self.random.uniform(-1.0, 1.0)
        heart_rate: float | None = round(72.0 + (jitter * 2.0), 1)
        spo2: float | None = round(98.0 + (jitter * 0.3), 1)
        heart_rate_raw: float | None = heart_rate
        spo2_raw: float | None = spo2
        wrist_surface_temp: float | None = round(33.0 + (jitter * 0.4), 1)
        accel: float | None = round(1.0 + (jitter * 0.03), 3)
        gyro: float | None = round(abs(jitter) * 3.0, 2)
        fall_state = "idle"
        ppg: float | None = 0.94
        finger_present = True
        motion_artifact = False
        ppg_state = "valid"
        heart_rate_valid = True
        spo2_valid = True
        wrist_surface_temp_valid = True
        motion_valid = True
        faults: list[str] = []

        if scenario == "ds18b20_fault":
            wrist_surface_temp = None
            wrist_surface_temp_valid = False
            faults = ["ds18b20_unavailable"]
        elif scenario == "motion_artifact":
            heart_rate = None
            spo2 = None
            accel = round(1.7 + abs(jitter) * 0.5, 3)
            gyro = round(120.0 + abs(jitter) * 60.0, 2)
            ppg = 0.18
            motion_artifact = True
            ppg_state = "motion"
            heart_rate_valid = False
            spo2_valid = False
            faults = ["ppg_motion_artifact"]
        elif scenario == "unstable_ppg":
            heart_rate_raw = 180.0 if step % 2 == 0 else 66.0
            spo2_raw = 96.0 if step % 2 == 0 else 99.0
            heart_rate = None
            spo2 = None
            ppg = 0.58
            ppg_state = "unstable"
            heart_rate_valid = False
            spo2_valid = False
        elif scenario == "low_spo2":
            spo2 = round(88.5 + (jitter * 0.4), 1)
            spo2_raw = spo2
        elif scenario == "high_hr":
            heart_rate = round(136.0 + (jitter * 3.0), 1)
            heart_rate_raw = heart_rate
        elif scenario == "fall":
            trigger = 3 if total is None else max(0, total // 2)
            phase = step - trigger
            if phase == -3:
                fall_state = "low_g"
                accel = 0.25
                gyro = 45.0
            elif phase == -2:
                fall_state = "impact"
                accel = 3.4
                gyro = 285.0
            elif phase == -1:
                fall_state = "verify_stillness"
                accel = 1.01
                gyro = 1.2
            elif phase == 0:
                heart_rate = None
                spo2 = None
                accel = 1.0
                gyro = 0.8
                fall_state = "alarm"
                ppg = 0.12
                motion_artifact = True
                ppg_state = "motion"
                heart_rate_valid = False
                spo2_valid = False
                faults = ["fall_suspected_demo", "ppg_motion_artifact"]
            elif phase == 1:
                fall_state = "refractory"
            if phase in {-3, -2}:
                heart_rate = None
                spo2 = None
                ppg = 0.2
                motion_artifact = True
                ppg_state = "motion"
                heart_rate_valid = False
                spo2_valid = False
                faults = [f"fall_phase_{fall_state}", "ppg_motion_artifact"]

        return Message(
            topic=self.topic("telemetry"),
            payload={
                "schema": "health.telemetry.v4",
                "device_id": self.config.device_id,
                "boot_id": self.boot_id,
                "seq": self.seq,
                "uptime_ms": self.uptime_ms(step if self.config.dry_run else None),
                "vitals": {
                    "heart_rate_raw_bpm": heart_rate_raw,
                    "heart_rate_bpm": heart_rate,
                    "spo2_raw_pct": spo2_raw,
                    "spo2_pct": spo2,
                },
                "wearable": {
                    "wrist_surface_temp_c": wrist_surface_temp,
                },
                "motion": {
                    "accel_g": accel,
                    "gyro_dps": gyro,
                    "fall_state": fall_state,
                },
                "quality": {
                    "ppg": ppg,
                    "finger_present": finger_present,
                    "motion_artifact": motion_artifact,
                    "ppg_state": ppg_state,
                    "heart_rate_valid": heart_rate_valid,
                    "spo2_valid": spo2_valid,
                    "wrist_surface_temp_valid": wrist_surface_temp_valid,
                    "motion_valid": motion_valid,
                },
                "system": self.system(faults),
            },
            qos=0,
        )

    def fall_event(self, *, synthetic_step: int | None = None) -> Message:
        return Message(
            topic=self.topic("event"),
            payload={
                "schema": "health.event.v1",
                "device_id": self.config.device_id,
                "boot_id": self.boot_id,
                "event_id": f"evt-{uuid.uuid4().hex}",
                "seq": self.seq,
                "uptime_ms": self.uptime_ms(synthetic_step),
                "type": "fall_suspected_demo",
            },
            qos=1,
        )

    def messages(self) -> Iterator[Message]:
        yield self.status(True, "simulator_started", synthetic_step=0 if self.config.dry_run else None)

        if self.config.count == 0:
            total: int | None = None
            limit = 5 if self.config.dry_run else None
        else:
            total = self.config.count
            limit = self.config.count

        step = 0
        while limit is None or step < limit:
            telemetry = self.telemetry(self.config.scenario, step, total)
            yield telemetry
            if self.config.scenario == "fall" and telemetry.payload["motion"]["fall_state"] == "alarm":
                yield self.fall_event(synthetic_step=step if self.config.dry_run else None)
            step += 1
            if not self.config.dry_run and (limit is None or step < limit):
                time.sleep(self.config.interval)

        reason = "offline_scenario" if self.config.scenario == "offline" else "simulator_complete"
        yield self.status(False, reason, synthetic_step=step if self.config.dry_run else None)


class MqttPublisher:
    def __init__(self, config: RuntimeConfig, stream: ScenarioStream) -> None:
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError(
                "Thieu paho-mqtt. Cai dependencies cua du an roi chay lai."
            ) from exc

        self.mqtt = mqtt
        self.config = config
        self.stream = stream
        self.connected = threading.Event()
        self.is_connected = False
        self.connection_error: str | None = None
        client_id = f"sim-{config.device_id}-{stream.boot_id[:8]}"
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        if config.username is not None:
            self.client.username_pw_set(config.username, config.password)
        if config.tls:
            self.client.tls_set(ca_certs=str(config.ca_cert) if config.ca_cert else None)

        will = stream.status(False, "connection_lost")
        self.client.will_set(
            will.topic,
            encode_payload(will.payload),
            qos=will.qos,
            retain=will.retain,
        )

    def _on_connect(self, _client: Any, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any) -> None:
        if reason_code == 0:
            self.is_connected = True
            self.connected.set()
            return
        self.connection_error = str(reason_code)
        self.connected.set()

    def _on_disconnect(
        self,
        _client: Any,
        _userdata: Any,
        _disconnect_flags: Any,
        _reason_code: Any,
        _properties: Any,
    ) -> None:
        self.is_connected = False

    def connect(self) -> None:
        self.client.connect(self.config.broker, self.config.port, keepalive=30)
        self.client.loop_start()
        if not self.connected.wait(self.config.connect_timeout):
            self.client.loop_stop()
            raise RuntimeError("Het thoi gian cho ket noi MQTT.")
        if self.connection_error is not None:
            self.client.loop_stop()
            raise RuntimeError(f"Broker tu choi ket noi MQTT: {self.connection_error}")

    def publish(self, message: Message) -> None:
        info = self.client.publish(
            message.topic,
            encode_payload(message.payload),
            qos=message.qos,
            retain=message.retain,
        )
        if info.rc != self.mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"Publish that bai cho {message.topic}: rc={info.rc}")
        info.wait_for_publish(timeout=5.0)
        if not info.is_published():
            raise RuntimeError(f"Publish khong duoc broker xac nhan: {message.topic}")

    def close(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()
        self.is_connected = False


def encode_payload(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("gia tri phai lon hon 0")
    return parsed


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("gia tri phai lon hon hoac bang 0")
    return parsed


def parse_args(argv: list[str] | None = None) -> RuntimeConfig:
    parser = argparse.ArgumentParser(
        description="Phat MQTT de mo phong node IoT suc khoe phi lam sang.",
    )
    parser.add_argument("--broker", default=os.getenv("MQTT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MQTT_PORT", "1883")))
    parser.add_argument(
        "--username",
        default=os.getenv("SIMULATOR_MQTT_USERNAME"),
        help="Mac dinh tu SIMULATOR_MQTT_USERNAME.",
    )
    parser.add_argument(
        "--prompt-password",
        action="store_true",
        help="Nhap mat khau an, ghi de bien moi truong.",
    )
    parser.add_argument("--device-id", default=os.getenv("DEVICE_ID", "health-node-01"))
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument(
        "--interval",
        type=positive_float,
        default=1.0,
        help="So giay giua hai telemetry.",
    )
    parser.add_argument(
        "--count",
        type=non_negative_int,
        default=20,
        help="So telemetry; 0 de chay den khi dung.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tls", action="store_true", default=env_bool("MQTT_TLS"))
    parser.add_argument(
        "--ca-cert",
        type=Path,
        default=Path(value) if (value := os.getenv("MQTT_CA_CERT")) else None,
    )
    parser.add_argument("--connect-timeout", type=positive_float, default=10.0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Khong ket noi broker; in topic va payload JSON de kiem tra.",
    )
    args = parser.parse_args(argv)

    if not DEVICE_ID_RE.fullmatch(args.device_id):
        parser.error("--device-id phai khop ^[a-z0-9][a-z0-9-]{0,31}$")
    if not 1 <= args.port <= 65_535:
        parser.error("--port phai trong khoang 1..65535")
    if args.ca_cert is not None and not args.tls:
        parser.error("--ca-cert chi hop le khi dung --tls")
    if args.ca_cert is not None and not args.ca_cert.is_file():
        parser.error(f"khong tim thay CA certificate: {args.ca_cert}")

    password = (
        getpass.getpass("MQTT password: ")
        if args.prompt_password
        else os.getenv("SIMULATOR_MQTT_PASSWORD")
    )
    if not args.dry_run and (not args.username or not password):
        parser.error(
            "broker yeu cau xac thuc: dat SIMULATOR_MQTT_USERNAME va "
            "SIMULATOR_MQTT_PASSWORD, hoac dung --prompt-password"
        )

    return RuntimeConfig(
        broker=args.broker,
        port=args.port,
        username=args.username,
        password=password,
        device_id=args.device_id,
        scenario=args.scenario,
        interval=args.interval,
        count=args.count,
        seed=args.seed,
        tls=args.tls,
        ca_cert=args.ca_cert,
        connect_timeout=args.connect_timeout,
        dry_run=args.dry_run,
    )


def print_message(message: Message) -> None:
    print(
        json.dumps(
            {
                "topic": message.topic,
                "qos": message.qos,
                "retain": message.retain,
                "payload": message.payload,
            },
            ensure_ascii=False,
            allow_nan=False,
        )
    )


def main(argv: list[str] | None = None) -> int:
    try:
        config = parse_args(argv)
    except ValueError as exc:
        print(f"Simulator configuration error: {exc}", file=sys.stderr)
        return 2
    stream = ScenarioStream(config)

    if config.dry_run:
        for message in stream.messages():
            print_message(message)
        return 0

    publisher: MqttPublisher | None = None
    offline_sent = False
    exit_code = 0
    try:
        publisher = MqttPublisher(config, stream)
        publisher.connect()
        for message in stream.messages():
            publisher.publish(message)
            if message.topic.endswith("/status") and message.payload["online"] is False:
                offline_sent = True
            print(f"published {message.topic} seq={message.payload['seq']}")
    except KeyboardInterrupt:
        print("Dung simulator theo yeu cau nguoi dung.", file=sys.stderr)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Simulator loi: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        if publisher is not None:
            if publisher.is_connected and not offline_sent:
                try:
                    publisher.publish(stream.status(False, "simulator_stopped"))
                except Exception:
                    pass
            try:
                publisher.close()
            except Exception:
                pass
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
