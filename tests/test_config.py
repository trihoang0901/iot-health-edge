from __future__ import annotations

import pytest

from edge.config import DemoRuleSettings, Settings


@pytest.mark.parametrize(
    ("username", "password"),
    [(None, None), ("edge", None), (None, "secret")],
)
def test_mqtt_enabled_requires_complete_credentials(username, password):
    with pytest.raises(ValueError, match="MQTT_USERNAME and MQTT_PASSWORD"):
        Settings(
            mqtt_enabled=True,
            mqtt_username=username,
            mqtt_password=password,
        )


@pytest.mark.parametrize("queue_size", [0, 10_001])
def test_queue_size_must_be_bounded(queue_size):
    with pytest.raises(ValueError, match="EDGE_QUEUE_SIZE"):
        Settings(mqtt_enabled=False, queue_size=queue_size)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"max_payload_bytes": 511}, "EDGE_MAX_PAYLOAD_BYTES"),
        ({"max_payload_bytes": 16_385}, "EDGE_MAX_PAYLOAD_BYTES"),
        ({"telemetry_retention_rows": 99}, "EDGE_TELEMETRY_RETENTION_ROWS"),
        (
            {"telemetry_retention_rows": 1_000_001},
            "EDGE_TELEMETRY_RETENTION_ROWS",
        ),
    ],
)
def test_resource_limits_reject_out_of_range_values(overrides, message):
    with pytest.raises(ValueError, match=message):
        Settings(mqtt_enabled=False, **overrides)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("max_payload_bytes", 512),
        ("max_payload_bytes", 16_384),
        ("telemetry_retention_rows", 100),
        ("telemetry_retention_rows", 1_000_000),
    ],
)
def test_resource_limit_boundaries_are_accepted(field_name, value):
    settings = Settings(mqtt_enabled=False, **{field_name: value})

    assert getattr(settings, field_name) == value


@pytest.mark.parametrize(
    "environment_name", ["MQTT_ENABLED", "MQTT_TLS", "TELEGRAM_ENABLED"]
)
def test_invalid_boolean_environment_values_fail_closed(monkeypatch, environment_name):
    monkeypatch.setenv("MQTT_ENABLED", "false")
    monkeypatch.setenv(environment_name, "sometimes")

    with pytest.raises(ValueError, match=environment_name):
        Settings()


@pytest.mark.parametrize(
    ("bot_token", "chat_id"),
    [(None, None), ("bot-token", None), (None, "123456")],
)
def test_enabled_telegram_requires_complete_credentials(bot_token, chat_id):
    with pytest.raises(
        ValueError, match="TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
    ):
        Settings(
            mqtt_enabled=False,
            telegram_enabled=True,
            telegram_bot_token=bot_token,
            telegram_chat_id=chat_id,
        )


def test_disabled_telegram_does_not_require_credentials():
    settings = Settings(
        mqtt_enabled=False,
        telegram_enabled=False,
        telegram_bot_token=None,
        telegram_chat_id=None,
    )

    assert settings.telegram_enabled is False


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"telegram_request_timeout_seconds": 0}, "TELEGRAM_REQUEST_TIMEOUT_SECONDS"),
        ({"telegram_request_timeout_seconds": 61}, "TELEGRAM_REQUEST_TIMEOUT_SECONDS"),
        ({"telegram_max_attempts": 0}, "TELEGRAM_MAX_ATTEMPTS"),
        ({"telegram_max_attempts": 11}, "TELEGRAM_MAX_ATTEMPTS"),
        ({"telegram_retry_base_seconds": 0}, "TELEGRAM_RETRY_BASE_SECONDS"),
        (
            {
                "telegram_retry_base_seconds": 10,
                "telegram_retry_max_seconds": 5,
            },
            "TELEGRAM_RETRY_MAX_SECONDS",
        ),
        ({"telegram_retry_max_seconds": 3601}, "TELEGRAM_RETRY_MAX_SECONDS"),
        ({"telegram_queue_size": 0}, "TELEGRAM_QUEUE_SIZE"),
        ({"telegram_queue_size": 10_001}, "TELEGRAM_QUEUE_SIZE"),
        ({"telegram_shutdown_timeout_seconds": 0}, "TELEGRAM_SHUTDOWN_TIMEOUT_SECONDS"),
        (
            {"telegram_shutdown_timeout_seconds": 31},
            "TELEGRAM_SHUTDOWN_TIMEOUT_SECONDS",
        ),
        (
            {
                "telegram_request_timeout_seconds": 5,
                "telegram_shutdown_timeout_seconds": 5,
            },
            "TELEGRAM_REQUEST_TIMEOUT_SECONDS",
        ),
    ],
)
def test_telegram_resource_limits_are_validated(overrides, message):
    with pytest.raises(ValueError, match=message):
        Settings(mqtt_enabled=False, **overrides)


def test_settings_repr_redacts_transport_credentials():
    settings = Settings(
        mqtt_enabled=False,
        mqtt_password="mqtt-secret",
        telegram_enabled=True,
        telegram_bot_token="telegram-secret",
        telegram_chat_id="private-chat-id",
    )

    rendered = repr(settings)

    assert "mqtt-secret" not in rendered
    assert "telegram-secret" not in rendered
    assert "private-chat-id" not in rendered


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"max_sample_gap_seconds": 0.0}, "DEMO_MAX_SAMPLE_GAP_SECONDS"),
        ({"min_ppg_quality": 1.1}, "DEMO_MIN_PPG_QUALITY"),
        ({"hold_seconds": -1.0}, "hold/recovery durations"),
    ],
)
def test_demo_rule_guardrails_are_validated(overrides, message):
    with pytest.raises(ValueError, match=message):
        DemoRuleSettings(**overrides)


def test_surface_temperature_rule_settings_are_retired():
    settings = DemoRuleSettings()

    assert not hasattr(settings, "surface_temp_threshold")
    assert not hasattr(settings, "temp_hysteresis")
    with pytest.raises(TypeError):
        DemoRuleSettings(surface_temp_threshold=38.0)
