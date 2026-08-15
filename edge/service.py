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
    qos: int | None = None
    retain: bool | None = None
    dup: bool | None = None

    @property
    def payload_size(self) -> int:
        return len(self.payload)


@dataclass(frozen=True, slots=True)
class IngestResult:
    accepted: bool
    kind: str | None = None
    duplicate: bool = False
    disposition: str | None = None
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
            "stale": 0,
            "out_of_order": 0,
            "rejected": 0,
            "queue_dropped": 0,
            "processing_errors": 0,
            "payload_bytes": 0,
            "qos0_messages": 0,
            "qos1_messages": 0,
            "retained_messages": 0,
            "mqtt_dup_flagged": 0,
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

    def submit(
        self,
        topic: str,
        payload: bytes,
        received_at: datetime | None = None,
        *,
        qos: int | None = None,
        retain: bool | None = None,
        dup: bool | None = None,
    ) -> bool:
        try:
            self.queue.put_nowait(
                InboundMessage(
                    topic=topic,
                    payload=payload,
                    received_at=received_at or utc_now(),
                    qos=qos,
                    retain=retain,
                    dup=dup,
                )
            )
            return True
        except queue.Full:
            self._increment("queue_dropped")
            self._last_error = "ingestion queue is full"
            return False

    def process_message(self, message: InboundMessage) -> IngestResult:
        try:
            self._record_protocol_metadata(message)
            topic_device_id, kind = parse_topic(message.topic)
            if len(message.payload) > self.max_payload_bytes:
                raise ValueError(
                    f"MQTT payload exceeds {self.max_payload_bytes} bytes"
                )
            raw_json = message.payload.decode("utf-8", errors="strict")

            if kind == "telemetry":
                telemetry = parse_telemetry(raw_json)
                self._assert_topic_device(topic_device_id, telemetry.device_id)
                rule_state = self.rules.snapshot_state()
                changed_alerts: list[dict[str, object]] = []
                try:
                    with self.database.transaction() as connection:
                        disposition = self.database.admit_session(
                            device_id=telemetry.device_id,
                            boot_id=telemetry.boot_id,
                            stream="telemetry",
                            seq=telemetry.seq,
                            received=message.received_at,
                            connection=connection,
                        )
                        if disposition != "accepted":
                            return self._disposition_result(kind, disposition)
                        _, inserted = self.database.insert_telemetry(
                            telemetry,
                            message.received_at,
                            raw_json,
                            connection=connection,
                        )
                        if not inserted:
                            return self._disposition_result(kind, "duplicate")
                        changed_alerts = self.rules.evaluate(
                            telemetry,
                            message.received_at,
                            connection=connection,
                        )
                except BaseException:
                    self.rules.restore_state(rule_state)
                    raise
                for alert in changed_alerts:
                    if (
                        alert.get("state") == "open"
                        and alert.get("occurrence_count") == 1
                    ):
                        self._enqueue_alert(alert)
            elif kind == "event":
                event = FallEvent.model_validate_json(raw_json)
                self._assert_topic_device(topic_device_id, event.device_id)
                with self.database.transaction() as connection:
                    disposition = self.database.admit_session(
                        device_id=event.device_id,
                        boot_id=event.boot_id,
                        stream="event",
                        seq=event.seq,
                        received=message.received_at,
                        connection=connection,
                    )
                    if disposition != "accepted":
                        return self._disposition_result(kind, disposition)
                    self.database.ensure_device(
                        event.device_id,
                        event.boot_id,
                        message.received_at,
                        connection=connection,
                    )
                    alert, inserted = self.database.record_fall_event(
                        device_id=event.device_id,
                        event_id=event.event_id,
                        happened=message.received_at,
                        connection=connection,
                    )
                    if not inserted:
                        return self._disposition_result(kind, "duplicate")
                self._enqueue_alert(alert)
            else:
                status = DeviceStatus.model_validate_json(raw_json)
                self._assert_topic_device(topic_device_id, status.device_id)
                with self.database.transaction() as connection:
                    disposition = self.database.admit_session(
                        device_id=status.device_id,
                        boot_id=status.boot_id,
                        stream="status",
                        seq=status.seq,
                        received=message.received_at,
                        online=status.online,
                        reason=status.reason,
                        connection=connection,
                    )
                    if disposition != "accepted":
                        return self._disposition_result(kind, disposition)
                    self.database.update_status(
                        status,
                        message.received_at,
                        retained=message.retain,
                        connection=connection,
                    )

            self._increment("accepted")
            return IngestResult(accepted=True, kind=kind, disposition="accepted")
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

    def _record_protocol_metadata(self, message: InboundMessage) -> None:
        with self._metrics_lock:
            self._metrics["payload_bytes"] += message.payload_size
            if message.qos == 0:
                self._metrics["qos0_messages"] += 1
            elif message.qos == 1:
                self._metrics["qos1_messages"] += 1
            if message.retain:
                self._metrics["retained_messages"] += 1
            if message.dup:
                self._metrics["mqtt_dup_flagged"] += 1

    def _disposition_result(self, kind: str, disposition: str) -> IngestResult:
        metric = "duplicates" if disposition == "duplicate" else disposition
        self._increment(metric)
        return IngestResult(
            accepted=True,
            kind=kind,
            duplicate=disposition == "duplicate",
            disposition=disposition,
        )

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
