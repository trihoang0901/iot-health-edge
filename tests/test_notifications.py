from __future__ import annotations

import json
import logging
import queue
import threading
import time
from http.client import HTTPException as HttpClientError, IncompleteRead

import pytest

from edge.notifications import (
    AlertNotification,
    DeliveryFailure,
    TelegramApiClient,
    TelegramNotifier,
    build_alert_message,
)


SAMPLE_NOTIFICATION = AlertNotification(
    device_id="health-node-01",
    rule_id="demo_low_spo2",
    severity="warning",
    message="SpO₂ tham khảo vượt ngưỡng demo thấp",
    happened_at="2026-08-12T08:00:00.000Z",
    value=91.5,
)


class ScriptedClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.messages: list[str] = []

    def send_message(self, text: str) -> None:
        self.messages.append(text)
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, BaseException):
            raise outcome


def make_notifier(client, **overrides):
    defaults = {
        "queue_size": 10,
        "max_attempts": 3,
        "retry_base_seconds": 1.0,
        "retry_max_seconds": 30.0,
        "shutdown_timeout_seconds": 1.0,
    }
    defaults.update(overrides)
    return TelegramNotifier(client=client, **defaults)


def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_plain_text_message_is_vietnamese_minimal_and_non_clinical():
    notification = AlertNotification(
        device_id="node<>&_*[]",
        rule_id="surface_temp_demo",
        severity="warning",
        message="Dữ liệu <>&_*[]\nkhông chèn định dạng",
        happened_at="2026-08-12T08:00:00.000Z",
        value=38.25,
    )

    text = build_alert_message(notification)

    assert "node<>&_*[]" in text
    assert "Dữ liệu <>&_*[] không chèn định dạng" in text
    assert "38.25 °C" in text
    assert "Prototype phi lâm sàng" in text
    assert "không phải kênh cấp cứu" in text
    assert len(text) <= 4096


def test_api_client_posts_plain_utf8_json_without_parse_mode():
    captured = {}

    def http_post(url, data, timeout):
        captured.update(url=url, data=data, timeout=timeout)
        return 200, b'{"ok":true,"result":{"message_id":1}}'

    client = TelegramApiClient(
        bot_token="123456:TEST_TOKEN",
        chat_id="-100123456",
        timeout_seconds=4.5,
        http_post=http_post,
    )
    client.send_message("Cảnh báo tiếng Việt <>&_*[]")

    payload = json.loads(captured["data"].decode("utf-8"))
    assert captured["url"].endswith("/bot123456:TEST_TOKEN/sendMessage")
    assert captured["timeout"] == 4.5
    assert payload == {
        "chat_id": "-100123456",
        "text": "Cảnh báo tiếng Việt <>&_*[]",
    }
    assert "parse_mode" not in payload


@pytest.mark.parametrize(
    ("status", "body", "reason", "retryable", "retry_after"),
    [
        (
            429,
            b'{"ok":false,"error_code":429,"parameters":{"retry_after":7}}',
            "rate_limited",
            True,
            7.0,
        ),
        (429, b"not-json", "rate_limited", True, None),
        (
            503,
            b'{"ok":false,"error_code":503}',
            "telegram_server_error",
            True,
            None,
        ),
        (
            403,
            b'{"ok":false,"error_code":403}',
            "telegram_client_error",
            False,
            None,
        ),
        (
            400,
            b'{"ok":false,"error_code":500}',
            "telegram_client_error",
            False,
            None,
        ),
        (200, b'{"ok":false}', "telegram_api_error", False, None),
        (200, b"not-json", "invalid_response", False, None),
    ],
)
def test_api_failures_are_classified_without_using_remote_description(
    status, body, reason, retryable, retry_after
):
    client = TelegramApiClient(
        bot_token="test-token",
        chat_id="test-chat",
        timeout_seconds=5,
        http_post=lambda _url, _data, _timeout: (status, body),
    )

    with pytest.raises(DeliveryFailure) as caught:
        client.send_message("test")

    assert caught.value.reason == reason
    assert caught.value.retryable is retryable
    assert caught.value.retry_after == retry_after


@pytest.mark.parametrize(
    "failure",
    [
        OSError("sensitive upstream detail"),
        TimeoutError("sensitive timeout detail"),
        HttpClientError("sensitive protocol detail"),
        IncompleteRead(b"partial-response", 100),
    ],
)
def test_network_failure_is_retryable_and_exception_text_is_discarded(failure):
    def fail(_url, _data, _timeout):
        raise failure

    client = TelegramApiClient(
        bot_token="test-token",
        chat_id="test-chat",
        timeout_seconds=5,
        http_post=fail,
    )

    with pytest.raises(DeliveryFailure) as caught:
        client.send_message("test")

    assert str(caught.value) == "network_error"
    assert caught.value.retryable is True


def test_rate_limit_uses_retry_after_then_succeeds():
    client = ScriptedClient(
        [
            DeliveryFailure("rate_limited", retryable=True, retry_after=7),
            None,
        ]
    )
    delays = []
    notifier = make_notifier(
        client,
        stop_waiter=lambda _event, delay: delays.append(delay) or False,
    )

    notifier._deliver(SAMPLE_NOTIFICATION)

    assert delays == [7]
    assert notifier.metrics()["retried"] == 1
    assert notifier.metrics()["sent"] == 1
    assert notifier.metrics()["failed"] == 0


def test_transient_failure_retries_with_bounded_backoff_then_exhausts():
    failure = DeliveryFailure("telegram_server_error", retryable=True)
    client = ScriptedClient([failure, failure, failure])
    delays = []
    notifier = make_notifier(
        client,
        retry_base_seconds=2,
        retry_max_seconds=3,
        stop_waiter=lambda _event, delay: delays.append(delay) or False,
    )

    notifier._deliver(SAMPLE_NOTIFICATION)

    assert delays == [2, 3]
    assert notifier.metrics()["retried"] == 2
    assert notifier.metrics()["failed"] == 1
    assert notifier.metrics()["last_error"] == "telegram_server_error"


def test_permanent_client_failure_is_not_retried():
    client = ScriptedClient(
        [DeliveryFailure("telegram_client_error", retryable=False)]
    )
    delays = []
    notifier = make_notifier(
        client,
        stop_waiter=lambda _event, delay: delays.append(delay) or False,
    )

    notifier._deliver(SAMPLE_NOTIFICATION)

    assert delays == []
    assert len(client.messages) == 1
    assert notifier.metrics()["retried"] == 0
    assert notifier.metrics()["failed"] == 1


def test_queue_full_is_non_blocking_and_shutdown_drains_available_message():
    started = threading.Event()
    release = threading.Event()

    class BlockingClient:
        def send_message(self, _text):
            started.set()
            assert release.wait(timeout=2)

    notifier = make_notifier(BlockingClient(), queue_size=1)
    notifier.start()
    try:
        assert notifier.enqueue(SAMPLE_NOTIFICATION)
        assert started.wait(timeout=1)
        assert notifier.enqueue(SAMPLE_NOTIFICATION)
        assert notifier.enqueue(SAMPLE_NOTIFICATION) is False
        release.set()
        assert wait_until(lambda: notifier.metrics()["sent"] == 2)
    finally:
        notifier.stop()

    metrics = notifier.metrics()
    assert metrics["queued"] == 2
    assert metrics["dropped"] == 1
    assert metrics["sent"] == 2
    assert metrics["worker_alive"] is False


def test_enqueue_and_stop_cannot_leave_an_accepted_message_stranded():
    entered_put = threading.Event()
    release_put = threading.Event()

    class PausingQueue(queue.Queue):
        def put_nowait(self, item):
            entered_put.set()
            assert release_put.wait(timeout=2)
            return super().put_nowait(item)

    notifier = make_notifier(ScriptedClient([None]))
    notifier._queue = PausingQueue(maxsize=1)
    notifier.start()
    enqueue_result = []
    stop_result = []
    enqueue_thread = threading.Thread(
        target=lambda: enqueue_result.append(notifier.enqueue(SAMPLE_NOTIFICATION))
    )
    stop_thread = threading.Thread(target=lambda: stop_result.append(notifier.stop()))

    enqueue_thread.start()
    assert entered_put.wait(timeout=1)
    stop_thread.start()
    time.sleep(0.05)
    assert stop_thread.is_alive()  # stop waits for the atomic state+queue operation.
    release_put.set()
    enqueue_thread.join(timeout=1)
    stop_thread.join(timeout=1)

    assert enqueue_result == [True]
    assert stop_result == [True]
    assert notifier.metrics()["queue_depth"] == 0
    assert notifier.metrics()["sent"] + notifier.metrics()["dropped"] == 1


def test_stop_reports_a_client_that_violates_the_bounded_call_contract():
    entered = threading.Event()
    release = threading.Event()

    class NonCooperativeClient:
        def send_message(self, _text):
            entered.set()
            release.wait(timeout=2)

    notifier = make_notifier(
        NonCooperativeClient(), shutdown_timeout_seconds=0.05
    )
    notifier.start()
    assert notifier.enqueue(SAMPLE_NOTIFICATION)
    assert entered.wait(timeout=1)

    assert notifier.stop() is False
    assert notifier.metrics()["worker_alive"] is True
    assert notifier.metrics()["last_error"] == "shutdown_timeout"

    release.set()
    assert wait_until(lambda: notifier.metrics()["worker_alive"] is False)


def test_unexpected_client_exception_does_not_kill_worker():
    client = ScriptedClient([RuntimeError("untrusted detail"), None])
    notifier = make_notifier(client)
    notifier.start()
    try:
        assert notifier.enqueue(SAMPLE_NOTIFICATION)
        assert notifier.enqueue(SAMPLE_NOTIFICATION)
        assert wait_until(
            lambda: notifier.metrics()["failed"] == 1
            and notifier.metrics()["sent"] == 1
        )
        assert notifier.metrics()["worker_alive"] is True
    finally:
        notifier.stop()


def test_logs_and_metrics_do_not_expose_token_chat_or_remote_body(caplog):
    token = "123456:SUPER_SECRET_TOKEN"
    chat_id = "-100987654321"
    remote_description = f"token={token}; chat={chat_id}"
    response = json.dumps(
        {"ok": False, "error_code": 403, "description": remote_description}
    ).encode()
    client = TelegramApiClient(
        bot_token=token,
        chat_id=chat_id,
        timeout_seconds=5,
        http_post=lambda _url, _data, _timeout: (403, response),
    )
    notifier = make_notifier(client)

    with caplog.at_level(logging.WARNING):
        notifier._deliver(SAMPLE_NOTIFICATION)

    combined = caplog.text + json.dumps(notifier.metrics())
    assert token not in combined
    assert chat_id not in combined
    assert remote_description not in combined
    assert notifier.metrics()["last_error"] == "telegram_client_error"
