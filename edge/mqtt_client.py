from __future__ import annotations

import logging
import threading
from typing import Any

from paho.mqtt import client as mqtt

from .config import Settings
from .db import utc_now
from .service import IngestionService


LOGGER = logging.getLogger(__name__)
TOPIC_FILTERS = (
    "iot-health/v1/devices/+/telemetry",
    "iot-health/v1/devices/+/event",
    "iot-health/v1/devices/+/status",
)


class EdgeMqttClient:
    def __init__(self, settings: Settings, ingestion: IngestionService) -> None:
        self.settings = settings
        self.ingestion = ingestion
        self.connected = threading.Event()
        self.subscribed = threading.Event()
        self.last_error: str | None = None
        self._subscribe_mid: int | None = None
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
            protocol=mqtt.MQTTv311,
            reconnect_on_failure=True,
        )
        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        if settings.mqtt_tls:
            self.client.tls_set(
                ca_certs=str(settings.mqtt_ca_cert) if settings.mqtt_ca_cert else None
            )
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message

    def start(self) -> None:
        try:
            self.client.connect_async(
                self.settings.mqtt_host,
                self.settings.mqtt_port,
                self.settings.mqtt_keepalive,
            )
            self.client.loop_start()
        except (OSError, ValueError) as exc:
            self.last_error = str(exc)
            LOGGER.warning("MQTT startup failed: %s", exc)

    def stop(self) -> None:
        try:
            self.client.disconnect()
        finally:
            self.client.loop_stop()
            self.connected.clear()
            self.subscribed.clear()

    def health(self) -> dict[str, object]:
        return {
            "enabled": True,
            "connected": self.connected.is_set(),
            "subscribed": self.subscribed.is_set(),
            "last_error": self.last_error,
        }

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        if reason_code.is_failure:
            self.last_error = f"MQTT connection rejected: {reason_code}"
            self.connected.clear()
            self.subscribed.clear()
            return
        self.last_error = None
        self.connected.set()
        self.subscribed.clear()
        result, mid = client.subscribe([(topic_filter, 1) for topic_filter in TOPIC_FILTERS])
        if result != mqtt.MQTT_ERR_SUCCESS:
            self.last_error = f"MQTT subscribe request failed: rc={result}"
            return
        self._subscribe_mid = mid

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: mqtt.Properties | None,
    ) -> None:
        self.connected.clear()
        self.subscribed.clear()
        if reason_code.is_failure:
            self.last_error = f"MQTT disconnected: {reason_code}"

    def _on_subscribe(
        self,
        client: mqtt.Client,
        userdata: Any,
        mid: int,
        reason_code_list: list[mqtt.ReasonCode],
        properties: mqtt.Properties | None,
    ) -> None:
        if self._subscribe_mid is not None and mid != self._subscribe_mid:
            return
        denied = any(
            bool(getattr(code, "is_failure", False))
            or (isinstance(code, int) and code >= 128)
            for code in reason_code_list
        )
        if denied or len(reason_code_list) != len(TOPIC_FILTERS):
            self.subscribed.clear()
            self.last_error = "MQTT broker denied one or more subscriptions"
            return
        self.last_error = None
        self.subscribed.set()

    def _on_message(self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
        if not self.ingestion.submit(message.topic, bytes(message.payload), utc_now()):
            LOGGER.warning("MQTT payload dropped because ingestion queue is full")
