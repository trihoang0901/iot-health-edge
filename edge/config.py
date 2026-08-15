from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None else float(value)


def _env_text(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _database_path() -> Path:
    explicit_path = os.getenv("EDGE_DATABASE_PATH")
    if explicit_path:
        return Path(explicit_path)
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return Path("data/edge.db")
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("DATABASE_URL must use sqlite:/// for this local edge service")
    return Path(database_url.removeprefix(prefix))


@dataclass(frozen=True, slots=True)
class DemoRuleSettings:
    low_spo2_threshold: float = field(
        default_factory=lambda: _env_float("DEMO_LOW_SPO2_THRESHOLD", 92.0)
    )
    high_hr_threshold: float = field(
        default_factory=lambda: _env_float("DEMO_HIGH_HR_THRESHOLD", 120.0)
    )
    hold_seconds: float = field(
        default_factory=lambda: _env_float("DEMO_RULE_HOLD_SECONDS", 10.0)
    )
    spo2_hysteresis: float = field(
        default_factory=lambda: _env_float("DEMO_LOW_SPO2_HYSTERESIS", 2.0)
    )
    hr_hysteresis: float = field(
        default_factory=lambda: _env_float("DEMO_HIGH_HR_HYSTERESIS", 5.0)
    )
    min_ppg_quality: float = field(
        default_factory=lambda: _env_float("DEMO_MIN_PPG_QUALITY", 0.5)
    )
    fall_recovery_seconds: float = field(
        default_factory=lambda: _env_float("DEMO_FALL_RECOVERY_SECONDS", 10.0)
    )
    max_sample_gap_seconds: float = field(
        default_factory=lambda: _env_float("DEMO_MAX_SAMPLE_GAP_SECONDS", 3.0)
    )

    def __post_init__(self) -> None:
        if not 0 <= self.low_spo2_threshold <= 100:
            raise ValueError("DEMO_LOW_SPO2_THRESHOLD must be between 0 and 100")
        if not 0 < self.high_hr_threshold <= 300:
            raise ValueError("DEMO_HIGH_HR_THRESHOLD must be between 0 and 300")
        if self.hold_seconds < 0 or self.fall_recovery_seconds < 0:
            raise ValueError("demo hold/recovery durations cannot be negative")
        if self.max_sample_gap_seconds <= 0:
            raise ValueError("DEMO_MAX_SAMPLE_GAP_SECONDS must be greater than zero")
        if not 0 <= self.min_ppg_quality <= 1:
            raise ValueError("DEMO_MIN_PPG_QUALITY must be between 0 and 1")
        if min(self.spo2_hysteresis, self.hr_hysteresis) < 0:
            raise ValueError("demo hysteresis values cannot be negative")


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path = field(default_factory=_database_path)
    mqtt_enabled: bool = field(default_factory=lambda: _env_bool("MQTT_ENABLED", True))
    mqtt_host: str = field(default_factory=lambda: os.getenv("MQTT_HOST", "127.0.0.1"))
    mqtt_port: int = field(default_factory=lambda: int(os.getenv("MQTT_PORT", "1883")))
    mqtt_username: str | None = field(default_factory=lambda: os.getenv("MQTT_USERNAME"))
    mqtt_password: str | None = field(
        default_factory=lambda: os.getenv("MQTT_PASSWORD"), repr=False
    )
    mqtt_tls: bool = field(default_factory=lambda: _env_bool("MQTT_TLS", False))
    mqtt_ca_cert: Path | None = field(
        default_factory=lambda: Path(value) if (value := os.getenv("MQTT_CA_CERT")) else None
    )
    mqtt_client_id: str = field(
        default_factory=lambda: os.getenv("MQTT_CLIENT_ID", "iot-health-edge")
    )
    mqtt_keepalive: int = field(
        default_factory=lambda: int(os.getenv("MQTT_KEEPALIVE", "30"))
    )
    queue_size: int = field(default_factory=lambda: int(os.getenv("EDGE_QUEUE_SIZE", "1000")))
    max_payload_bytes: int = field(
        default_factory=lambda: int(os.getenv("EDGE_MAX_PAYLOAD_BYTES", "4096"))
    )
    telemetry_retention_rows: int = field(
        default_factory=lambda: int(os.getenv("EDGE_TELEMETRY_RETENTION_ROWS", "50000"))
    )
    experiment_evidence_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("EDGE_EXPERIMENT_EVIDENCE_DIR", "evidence/runs")
        )
    )
    offline_after_seconds: float = field(
        default_factory=lambda: _env_float("DEVICE_OFFLINE_AFTER_SECONDS", 15.0)
    )
    telegram_enabled: bool = field(
        default_factory=lambda: _env_bool("TELEGRAM_ENABLED", False)
    )
    telegram_bot_token: str | None = field(
        default_factory=lambda: _env_text("TELEGRAM_BOT_TOKEN"), repr=False
    )
    telegram_chat_id: str | None = field(
        default_factory=lambda: _env_text("TELEGRAM_CHAT_ID"), repr=False
    )
    telegram_request_timeout_seconds: float = field(
        default_factory=lambda: _env_float("TELEGRAM_REQUEST_TIMEOUT_SECONDS", 5.0)
    )
    telegram_max_attempts: int = field(
        default_factory=lambda: int(os.getenv("TELEGRAM_MAX_ATTEMPTS", "3"))
    )
    telegram_retry_base_seconds: float = field(
        default_factory=lambda: _env_float("TELEGRAM_RETRY_BASE_SECONDS", 1.0)
    )
    telegram_retry_max_seconds: float = field(
        default_factory=lambda: _env_float("TELEGRAM_RETRY_MAX_SECONDS", 30.0)
    )
    telegram_queue_size: int = field(
        default_factory=lambda: int(os.getenv("TELEGRAM_QUEUE_SIZE", "100"))
    )
    telegram_shutdown_timeout_seconds: float = field(
        default_factory=lambda: _env_float("TELEGRAM_SHUTDOWN_TIMEOUT_SECONDS", 6.0)
    )
    allowed_hosts: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            item.strip()
            for item in os.getenv(
                "EDGE_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver"
            ).split(",")
            if item.strip()
        )
    )
    rules: DemoRuleSettings = field(default_factory=DemoRuleSettings)

    def __post_init__(self) -> None:
        if not 1 <= self.mqtt_port <= 65_535:
            raise ValueError("MQTT_PORT must be between 1 and 65535")
        if self.mqtt_keepalive <= 0:
            raise ValueError("MQTT_KEEPALIVE must be greater than zero")
        if not 1 <= self.queue_size <= 10_000:
            raise ValueError("EDGE_QUEUE_SIZE must be between 1 and 10000")
        if not 512 <= self.max_payload_bytes <= 16_384:
            raise ValueError("EDGE_MAX_PAYLOAD_BYTES must be between 512 and 16384")
        if not 100 <= self.telemetry_retention_rows <= 1_000_000:
            raise ValueError(
                "EDGE_TELEMETRY_RETENTION_ROWS must be between 100 and 1000000"
            )
        if not str(self.experiment_evidence_dir).strip():
            raise ValueError("EDGE_EXPERIMENT_EVIDENCE_DIR must not be empty")
        if self.offline_after_seconds <= 0:
            raise ValueError("DEVICE_OFFLINE_AFTER_SECONDS must be greater than zero")
        if not 0 < self.telegram_request_timeout_seconds <= 60:
            raise ValueError(
                "TELEGRAM_REQUEST_TIMEOUT_SECONDS must be greater than 0 and at most 60"
            )
        if not 1 <= self.telegram_max_attempts <= 10:
            raise ValueError("TELEGRAM_MAX_ATTEMPTS must be between 1 and 10")
        if not 0 < self.telegram_retry_base_seconds <= 60:
            raise ValueError(
                "TELEGRAM_RETRY_BASE_SECONDS must be greater than 0 and at most 60"
            )
        if not (
            self.telegram_retry_base_seconds
            <= self.telegram_retry_max_seconds
            <= 3600
        ):
            raise ValueError(
                "TELEGRAM_RETRY_MAX_SECONDS must be between the retry base and 3600"
            )
        if not 1 <= self.telegram_queue_size <= 10_000:
            raise ValueError("TELEGRAM_QUEUE_SIZE must be between 1 and 10000")
        if not 0 < self.telegram_shutdown_timeout_seconds <= 30:
            raise ValueError(
                "TELEGRAM_SHUTDOWN_TIMEOUT_SECONDS must be greater than 0 and at most 30"
            )
        if (
            self.telegram_request_timeout_seconds
            >= self.telegram_shutdown_timeout_seconds
        ):
            raise ValueError(
                "TELEGRAM_REQUEST_TIMEOUT_SECONDS must be less than "
                "TELEGRAM_SHUTDOWN_TIMEOUT_SECONDS"
            )
        if self.mqtt_enabled and (not self.mqtt_username or not self.mqtt_password):
            raise ValueError(
                "MQTT_USERNAME and MQTT_PASSWORD are required when MQTT_ENABLED is true"
            )
        if self.telegram_enabled and (
            not self.telegram_bot_token or not self.telegram_chat_id
        ):
            raise ValueError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required when "
                "TELEGRAM_ENABLED is true"
            )
        if not self.allowed_hosts:
            raise ValueError("EDGE_ALLOWED_HOSTS must contain at least one host")
