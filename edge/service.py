from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from pydantic import ValidationError

from .db import Database, utc_now
from .notifications import AlertNotification, NotificationSink
from .rules import RuleEngine
from .schemas import DeviceStatus, FallEvent, parse_telemetry, parse_topic


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class InboundMessage:
    topic: str
    payload: bytes
    received_at: datetime


@dataclass(frozen=True, slots=True)
class IngestResult:
    accepted: bool
    kind: str | None = None
    duplicate: bool = False
    error: str | None = None


class IngestionService:
    def __init__(
        self,
        database: Database,
        rules: RuleEngine,
        queue_size: int = 1000,
        max_payload_bytes: int = 4096,
        notifier: NotificationSink | None = None,
    ) -> None:
        if queue_size <= 0:
            raise ValueError("queue_size must be greater than zero")
        if max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be greater than zero")
        self.database = database
        self.rules = rules
        self.notifier = notifier
        self.max_payload_bytes = max_payload_bytes
        self.queue: queue.Queue[InboundMessage] = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._metrics_lock = threading.Lock()
        self._metrics = {
            "accepted": 0,
            "duplicates": 0,
            "rejected": 0,
            "queue_dropped": 0,
            "processing_errors": 0,
        }
        self._last_error: str | None = None

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(
            target=self._run, name="edge-sqlite-writer", daemon=True
        )
        self._worker.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=timeout)

    def submit(self, topic: str, payload: bytes, received_at: datetime | None = None) -> bool:
        try:
            self.queue.put_nowait(
                InboundMessage(topic=topic, payload=payload, received_at=received_at or utc_now())
            )
            return True
        except queue.Full:
            self._increment("queue_dropped")
            self._last_error = "ingestion queue is full"
            return False

    def process_message(self, message: InboundMessage) -> IngestResult:
        try:
            topic_device_id, kind = parse_topic(message.topic)
            if len(message.payload) > self.max_payload_bytes:
                raise ValueError(
                    f"MQTT payload exceeds {self.max_payload_bytes} bytes"
                )
            raw_json = message.payload.decode("utf-8", errors="strict")

            if kind == "telemetry":
                telemetry = parse_telemetry(raw_json)
                self._assert_topic_device(topic_device_id, telemetry.device_id)
                _, inserted = self.database.insert_telemetry(
                    telemetry, message.received_at, raw_json
                )
                if not inserted:
                    self._increment("duplicates")
                    return IngestResult(accepted=True, kind=kind, duplicate=True)
                changed_alerts = self.rules.evaluate(telemetry, message.received_at)
                for alert in changed_alerts:
                    if (
                        alert.get("state") == "open"
                        and alert.get("occurrence_count") == 1
                    ):
                        self._enqueue_alert(alert)
            elif kind == "event":
                event = FallEvent.model_validate_json(raw_json)
                self._assert_topic_device(topic_device_id, event.device_id)
                self.database.ensure_device(event.device_id, event.boot_id, message.received_at)
                alert, inserted = self.database.record_fall_event(
                    device_id=event.device_id,
                    event_id=event.event_id,
                    happened=message.received_at,
                )
                if not inserted:
                    self._increment("duplicates")
                    return IngestResult(accepted=True, kind=kind, duplicate=True)
                self._enqueue_alert(alert)
            else:
                status = DeviceStatus.model_validate_json(raw_json)
                self._assert_topic_device(topic_device_id, status.device_id)
                self.database.update_status(status, message.received_at)

            self._increment("accepted")
            return IngestResult(accepted=True, kind=kind)
        except (UnicodeDecodeError, ValueError, ValidationError) as exc:
            self._increment("rejected")
            self._last_error = str(exc)[:500]
            return IngestResult(accepted=False, error=self._last_error)

    def metrics(self) -> dict[str, object]:
        with self._metrics_lock:
            result: dict[str, object] = dict(self._metrics)
        result["queue_depth"] = self.queue.qsize()
        result["worker_alive"] = bool(self._worker and self._worker.is_alive())
        result["last_error"] = self._last_error
        return result

    def _run(self) -> None:
        while not self._stop.is_set() or not self.queue.empty():
            try:
                message = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.process_message(message)
            except Exception as exc:  # Keep one bad DB/runtime operation from killing ingestion.
                self._increment("processing_errors")
                self._last_error = f"{type(exc).__name__}: {exc}"[:500]
                LOGGER.exception("Unexpected ingestion worker failure")
            finally:
                self.queue.task_done()

    @staticmethod
    def _assert_topic_device(topic_device_id: str, payload_device_id: str) -> None:
        if topic_device_id != payload_device_id:
            raise ValueError("payload device_id does not match MQTT topic")

    def _increment(self, key: str) -> None:
        with self._metrics_lock:
            self._metrics[key] += 1

    def _enqueue_alert(self, alert: Mapping[str, object]) -> None:
        if self.notifier is None:
            return
        try:
            notification = AlertNotification.from_alert(alert)
            self.notifier.enqueue(notification)
        except Exception:
            LOGGER.warning(
                "Notification enqueue failed; alert ingestion continues",
            )
