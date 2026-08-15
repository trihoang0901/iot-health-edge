from __future__ import annotations

from dataclasses import asdict, dataclass
import random
from typing import Literal


ProfileName = Literal["lan-baseline", "remote-app-emulated"]


@dataclass(frozen=True, slots=True)
class AppImpairmentProfile:
    name: ProfileName
    version: str
    description_vi: str
    base_delay_ms: int
    jitter_ms: int
    intentional_drop_rate: float
    outage_fraction: float
    profile_kind: Literal["app_impairment"] = "app_impairment"
    network_claim: Literal["none"] = "none"
    injection_point: Literal["before_mqtt_publish"] = "before_mqtt_publish"

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ScheduledMessage:
    index: int
    delay_ms: int
    intentionally_dropped: bool
    drop_reason: Literal["scheduled_loss", "scheduled_outage"] | None

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


PROFILES: dict[ProfileName, AppImpairmentProfile] = {
    "lan-baseline": AppImpairmentProfile(
        name="lan-baseline",
        version="1.0",
        description_vi="Baseline ứng dụng: không chủ động trễ hoặc bỏ bản tin.",
        base_delay_ms=0,
        jitter_ms=0,
        intentional_drop_rate=0.0,
        outage_fraction=0.0,
    ),
    "remote-app-emulated": AppImpairmentProfile(
        name="remote-app-emulated",
        version="1.0",
        description_vi=(
            "Nhiễu tầng ứng dụng tái lập trước MQTT publish; không phải packet loss, "
            "network emulator hoặc phép đo 5G."
        ),
        base_delay_ms=85,
        jitter_ms=35,
        intentional_drop_rate=0.08,
        outage_fraction=0.10,
    ),
}


def get_profile(name: str) -> AppImpairmentProfile:
    try:
        return PROFILES[name]  # type: ignore[index]
    except KeyError as exc:
        raise ValueError(f"unsupported app impairment profile: {name}") from exc


def build_schedule(
    profile: AppImpairmentProfile,
    *,
    count: int,
    seed: int,
) -> tuple[ScheduledMessage, ...]:
    if count <= 0:
        raise ValueError("count must be greater than zero")

    rng = random.Random(seed)
    outage_length = int(round(count * profile.outage_fraction))
    if profile.outage_fraction > 0 and count >= 10:
        outage_length = max(1, outage_length)
    outage_start = max(0, (count - outage_length) // 2)
    outage_end = outage_start + outage_length

    schedule: list[ScheduledMessage] = []
    for index in range(count):
        delay = profile.base_delay_ms
        if profile.jitter_ms:
            delay += rng.randint(-profile.jitter_ms, profile.jitter_ms)
        in_outage = outage_length > 0 and outage_start <= index < outage_end
        random_drop = (
            profile.intentional_drop_rate > 0
            and rng.random() < profile.intentional_drop_rate
        )
        reason: Literal["scheduled_loss", "scheduled_outage"] | None = None
        if in_outage:
            reason = "scheduled_outage"
        elif random_drop:
            reason = "scheduled_loss"
        schedule.append(
            ScheduledMessage(
                index=index,
                delay_ms=max(0, delay),
                intentionally_dropped=reason is not None,
                drop_reason=reason,
            )
        )
    return tuple(schedule)


def public_profiles() -> list[dict[str, object]]:
    return [PROFILES[name].public_dict() for name in sorted(PROFILES)]

