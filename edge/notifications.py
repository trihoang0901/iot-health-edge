from __future__ import annotations

import json
import logging
import queue
import threading
from dataclasses import dataclass
from http.client import HTTPException as HttpClientError
from json import JSONDecodeError
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError
from urllib.request import Request, urlopen


LOGGER = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 64 * 1024
MAX_MESSAGE_LENGTH = 4096

HttpPost = Callable[[str, bytes, float], tuple[int, bytes]]
StopWaiter = Callable[[threading.Event, float], bool]


@dataclass(frozen=True, slots=True)
class AlertNotification:
    device_id: str
    rule_id: str
    severity: str
    message: str
    happened_at: str
    value: float | None = None

    @classmethod
    def from_alert(cls, alert: Mapping[str, object]) -> "AlertNotification":
        required = ("device_id", "rule_id", "severity", "message")
        values: dict[str, str] = {}
        for name in required:
            value = alert.get(name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"alert {name} is required for notification")
            values[name] = value

        happened_at = alert.get("last_seen_at") or alert.get("first_seen_at")
        if not isinstance(happened_at, str) or not happened_at:
            raise ValueError("alert timestamp is required for notification")

        raw_value = alert.get("last_value")
        value = (
            float(raw_value)
            if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool)
            else None
        )
        return cls(
            device_id=values["device_id"],
            rule_id=values["rule_id"],
            severity=values["severity"],
            message=values["message"],
            happened_at=happened_at,
            value=value,
        )


class NotificationSink(Protocol):
    def enqueue(self, notification: AlertNotification) -> bool: ...


class MessageClient(Protocol):
    def send_message(self, text: str) -> None: ...


class DeliveryFailure(Exception):
    def __init__(
        self,
        reason: str,
        *,
        retryable: bool,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable
        self.retry_after = retry_after


def _single_line(value: str, limit: int) -> str:
    return " ".join(value.split())[:limit]


def _retry_after(response: object) -> float | None:
    if not isinstance(response, dict):
        return None
    parameters = response.get("parameters")
    if not isinstance(parameters, dict):
        return None
    raw_retry_after = parameters.get("retry_after")
    if (
        isinstance(raw_retry_after, (int, float))
        and not isinstance(raw_retry_after, bool)
        and raw_retry_after > 0
    ):
        return float(raw_retry_after)
    return None


def build_alert_message(notification: AlertNotification) -> str:
    is_fall = notification.rule_id == "fall_suspected_demo"
    title = (
        "🚨 NGHI NGỜ NGÃ — CẢNH BÁO DEMO"
        if is_fall
        else "⚠️ CẢNH BÁO NGƯỠNG DEMO"
    )
    lines = [
        title,
        f"Thiết bị: {_single_line(notification.device_id, 128)}",
        f"Nội dung: {_single_line(notification.message, 500)}",
    ]
    if notification.value is not None:
        units = {
            "demo_low_spo2": "%",
            "demo_high_hr": "bpm",
            "surface_temp_demo": "°C",
        }
        suffix = units.get(notification.rule_id, "")
        formatted_value = f"{notification.value:.2f}".rstrip("0").rstrip(".")
        lines.append(f"Giá trị tham khảo: {formatted_value} {suffix}".rstrip())
    lines.extend(
        [
            f"Thời gian edge: {_single_line(notification.happened_at, 64)}",
            "",
            "Prototype phi lâm sàng. Hãy kiểm tra trực tiếp; Telegram không "
            "phải kênh cấp cứu và không bảo đảm giao nhận.",
        ]
    )
    text = "\n".join(lines)
    if len(text) <= MAX_MESSAGE_LENGTH:
        return text
    return text[: MAX_MESSAGE_LENGTH - 1] + "…"


def _default_http_post(url: str, data: bytes, timeout: float) -> tuple[int, bytes]:
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS host
            status = response.status
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        status = exc.code
        body = exc.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        return status, b""
    return status, body


class TelegramApiClient:
    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        timeout_seconds: float,
        http_post: HttpPost = _default_http_post,
    ) -> None:
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id
        self._timeout_seconds = timeout_seconds
        self._http_post = http_post

    def send_message(self, text: str) -> None:
        body = json.dumps(
            {"chat_id": self._chat_id, "text": text},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            status, response_body = self._http_post(
                self._url, body, self._timeout_seconds
            )
        except (OSError, TimeoutError, HttpClientError):
            raise DeliveryFailure("network_error", retryable=True) from None

        try:
            parsed_response: object | None = json.loads(
                response_body.decode("utf-8")
            )
        except (UnicodeDecodeError, JSONDecodeError):
            parsed_response = None
        response = parsed_response if isinstance(parsed_response, dict) else None

        if 200 <= status <= 299 and response and response.get("ok") is True:
            return
        # HTTP status is authoritative. A malformed or contradictory response
        # body must not turn 429/5xx into permanent errors or 4xx into retries.
        if status == 429:
            raise DeliveryFailure(
                "rate_limited",
                retryable=True,
                retry_after=_retry_after(response),
            )
        if 500 <= status <= 599:
            raise DeliveryFailure("telegram_server_error", retryable=True)
        if 400 <= status <= 499:
            raise DeliveryFailure("telegram_client_error", retryable=False)
        if response is None:
            raise DeliveryFailure("invalid_response", retryable=False)

        error_code = response.get("error_code")
        if error_code == 429:
            raise DeliveryFailure(
                "rate_limited",
                retryable=True,
                retry_after=_retry_after(response),
            )
        if isinstance(error_code, int) and 500 <= error_code <= 599:
            raise DeliveryFailure("telegram_server_error", retryable=True)
        if isinstance(error_code, int) and 400 <= error_code <= 499:
            raise DeliveryFailure("telegram_client_error", retryable=False)
        raise DeliveryFailure("telegram_api_error", retryable=False)


class TelegramNotifier:
    def __init__(
        self,
        *,
        client: MessageClient,
        queue_size: int,
        max_attempts: int,
        retry_base_seconds: float,
        retry_max_seconds: float,
        shutdown_timeout_seconds: float,
        stop_waiter: StopWaiter | None = None,
    ) -> None:
        self._client = client
        self._queue: queue.Queue[AlertNotification] = queue.Queue(maxsize=queue_size)
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._stop_waiter = stop_waiter or (lambda event, delay: event.wait(delay))
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._accepting = False
        self._state_lock = threading.Lock()
        self._metrics_lock = threading.Lock()
        self._metrics = {
            "queued": 0,
            "sent": 0,
            "retried": 0,
            "failed": 0,
            "dropped": 0,
        }
        self._last_error: str | None = None

    def start(self) -> None:
        with self._state_lock:
            if self._worker and self._worker.is_alive():
                return
            self._stop.clear()
            self._accepting = True
            self._worker = threading.Thread(
                target=self._run,
                name="edge-telegram-notifier",
                daemon=True,
            )
            self._worker.start()

    def stop(self) -> bool:
        with self._state_lock:
            self._accepting = False
            self._stop.set()
            worker = self._worker
        if worker:
            worker.join(timeout=self._shutdown_timeout_seconds)
        worker_alive = bool(worker and worker.is_alive())
        if worker_alive:
            with self._metrics_lock:
                self._last_error = "shutdown_timeout"
            LOGGER.warning("Telegram notification worker exceeded shutdown timeout")
        return not worker_alive

    def enqueue(self, notification: AlertNotification) -> bool:
        with self._state_lock:
            if not self._accepting:
                self._increment("dropped")
                return False
            try:
                self._queue.put_nowait(notification)
            except queue.Full:
                self._increment("dropped")
                LOGGER.warning("Telegram notification queue is full; message dropped")
                return False
        self._increment("queued")
        return True

    def metrics(self) -> dict[str, object]:
        with self._metrics_lock:
            result: dict[str, object] = dict(self._metrics)
            result["last_error"] = self._last_error
        result["queue_depth"] = self._queue.qsize()
        result["worker_alive"] = bool(self._worker and self._worker.is_alive())
        return result

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    notification = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    if self._stop.is_set():
                        self._increment("dropped")
                    else:
                        self._deliver(notification)
                except Exception:  # Keep one unexpected client bug from killing the worker.
                    self._mark_failed("unexpected_worker_error")
                finally:
                    self._queue.task_done()
        finally:
            self._discard_pending()

    def _discard_pending(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return
            self._increment("dropped")
            self._queue.task_done()

    def _deliver(self, notification: AlertNotification) -> None:
        text = build_alert_message(notification)
        for attempt in range(1, self._max_attempts + 1):
            try:
                self._client.send_message(text)
            except DeliveryFailure as failure:
                if failure.retryable and attempt < self._max_attempts:
                    self._increment("retried")
                    delay = failure.retry_after
                    if delay is None:
                        delay = self._retry_base_seconds * (2 ** (attempt - 1))
                    delay = min(delay, self._retry_max_seconds)
                    if self._stop_waiter(self._stop, delay):
                        self._mark_failed("shutdown_interrupted")
                        return
                    continue
                self._mark_failed(failure.reason)
                return
            except (OSError, TimeoutError):
                if attempt < self._max_attempts:
                    self._increment("retried")
                    delay = min(
                        self._retry_base_seconds * (2 ** (attempt - 1)),
                        self._retry_max_seconds,
                    )
                    if self._stop_waiter(self._stop, delay):
                        self._mark_failed("shutdown_interrupted")
                        return
                    continue
                self._mark_failed("network_error")
                return
            except Exception:
                self._mark_failed("unexpected_client_error")
                return
            self._increment("sent")
            with self._metrics_lock:
                self._last_error = None
            return

    def _mark_failed(self, reason: str) -> None:
        self._increment("failed")
        with self._metrics_lock:
            self._last_error = reason
        LOGGER.warning("Telegram notification delivery failed (%s)", reason)

    def _increment(self, key: str) -> None:
        with self._metrics_lock:
            self._metrics[key] += 1
