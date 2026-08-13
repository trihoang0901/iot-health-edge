from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from .config import DemoRuleSettings
from .db import Database
from .schemas import TelemetryMessage


@dataclass(frozen=True, slots=True)
class DemoRule:
    rule_id: str
    field: str
    direction: str
    threshold: float
    hold_seconds: float
    hysteresis: float
    severity: str
    message: str
    unit: str

    def public_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["non_clinical"] = True
        return result


class RuleEngine:
    def __init__(self, database: Database, settings: DemoRuleSettings) -> None:
        self.database = database
        self.settings = settings
        self.rules = (
            DemoRule(
                rule_id="demo_low_spo2",
                field="spo2_pct",
                direction="below",
                threshold=settings.low_spo2_threshold,
                hold_seconds=settings.hold_seconds,
                hysteresis=settings.spo2_hysteresis,
                severity="warning",
                message="SpO₂ tham khảo vượt ngưỡng demo thấp",
                unit="%",
            ),
            DemoRule(
                rule_id="demo_high_hr",
                field="heart_rate_bpm",
                direction="above",
                threshold=settings.high_hr_threshold,
                hold_seconds=settings.hold_seconds,
                hysteresis=settings.hr_hysteresis,
                severity="warning",
                message="Nhịp tim tham khảo vượt ngưỡng demo cao",
                unit="bpm",
            ),
        )
        self._pending_since: dict[tuple[str, str], datetime] = {}
        self._last_rule_sample: dict[tuple[str, str], datetime] = {}
        self._fall_recovery_since: dict[str, datetime] = {}
        self._fall_recovery_last_sample: dict[str, datetime] = {}

    def public_rules(self) -> list[dict[str, object]]:
        rules = [
            {
                **rule.public_dict(),
                "max_sample_gap_seconds": self.settings.max_sample_gap_seconds,
            }
            for rule in self.rules
        ]
        rules.append(
            {
                "rule_id": "fall_suspected_demo",
                "field": "event.type",
                "direction": "equals",
                "threshold": "fall_suspected_demo",
                "hold_seconds": 0,
                "hysteresis": None,
                "severity": "critical",
                "message": "Phát hiện sự kiện ngã thử nghiệm",
                "unit": None,
                "recovery_seconds": self.settings.fall_recovery_seconds,
                "max_sample_gap_seconds": self.settings.max_sample_gap_seconds,
                "recovery_condition": "motion.fall_state == 'idle'",
                "non_clinical": True,
            }
        )
        return rules

    def evaluate(
        self, telemetry: TelemetryMessage, received: datetime
    ) -> list[dict[str, object]]:
        changed: list[dict[str, object]] = []
        for rule in self.rules:
            value, is_valid = self._value_and_validity(telemetry, rule)
            key = (telemetry.device_id, rule.rule_id)
            active = self.database.get_active_alert(telemetry.device_id, rule.rule_id)

            if not is_valid or value is None:
                self._pending_since.pop(key, None)
                self._last_rule_sample.pop(key, None)
                continue

            previous_sample = self._last_rule_sample.get(key)
            sample_gap_broken = previous_sample is None or (
                (received - previous_sample).total_seconds() < 0
                or (received - previous_sample).total_seconds()
                > self.settings.max_sample_gap_seconds
            )
            self._last_rule_sample[key] = received

            violating = value < rule.threshold if rule.direction == "below" else value > rule.threshold
            recovered = (
                value >= rule.threshold + rule.hysteresis
                if rule.direction == "below"
                else value <= rule.threshold - rule.hysteresis
            )

            if active:
                self._pending_since.pop(key, None)
                if violating:
                    changed.append(
                        self.database.open_or_touch_alert(
                            device_id=telemetry.device_id,
                            rule_id=rule.rule_id,
                            severity=rule.severity,
                            message=rule.message,
                            happened=received,
                            value=value,
                        )
                    )
                elif recovered and self.database.resolve_alert(
                    telemetry.device_id, rule.rule_id, received
                ):
                    resolved = self.database.list_alerts(
                        state="resolved", device_id=telemetry.device_id, limit=1
                    )
                    if resolved:
                        changed.append(resolved[0])
                continue

            if not violating:
                self._pending_since.pop(key, None)
                continue

            if sample_gap_broken:
                self._pending_since[key] = received
            pending_since = self._pending_since.setdefault(key, received)
            if (received - pending_since).total_seconds() >= rule.hold_seconds:
                changed.append(
                    self.database.open_or_touch_alert(
                        device_id=telemetry.device_id,
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        message=rule.message,
                        happened=received,
                        value=value,
                    )
                )
                self._pending_since.pop(key, None)

        changed.extend(self._evaluate_fall_state(telemetry, received))
        return changed

    def _value_and_validity(
        self, telemetry: TelemetryMessage, rule: DemoRule
    ) -> tuple[float | None, bool]:
        if rule.field == "spo2_pct":
            valid = (
                telemetry.quality.spo2_valid
                and telemetry.quality.finger_present
                and telemetry.quality.motion_valid
                and not telemetry.quality.motion_artifact
                and telemetry.quality.ppg is not None
                and telemetry.quality.ppg >= self.settings.min_ppg_quality
            )
            return telemetry.vitals.spo2_pct, valid
        if rule.field == "heart_rate_bpm":
            valid = (
                telemetry.quality.heart_rate_valid
                and telemetry.quality.finger_present
                and telemetry.quality.motion_valid
                and not telemetry.quality.motion_artifact
                and telemetry.quality.ppg is not None
                and telemetry.quality.ppg >= self.settings.min_ppg_quality
            )
            return telemetry.vitals.heart_rate_bpm, valid
        raise ValueError(f"unsupported demo rule field: {rule.field}")

    def _evaluate_fall_state(
        self, telemetry: TelemetryMessage, received: datetime
    ) -> list[dict[str, object]]:
        device_id = telemetry.device_id
        active = self.database.get_active_alert(device_id, "fall_suspected_demo")
        if not telemetry.quality.motion_valid:
            self._fall_recovery_since.pop(device_id, None)
            self._fall_recovery_last_sample.pop(device_id, None)
            return []
        if not active or telemetry.motion.fall_state != "idle":
            self._fall_recovery_since.pop(device_id, None)
            self._fall_recovery_last_sample.pop(device_id, None)
            return []
        previous_sample = self._fall_recovery_last_sample.get(device_id)
        if previous_sample is None or (
            (received - previous_sample).total_seconds() < 0
            or (received - previous_sample).total_seconds()
            > self.settings.max_sample_gap_seconds
        ):
            self._fall_recovery_since[device_id] = received
        self._fall_recovery_last_sample[device_id] = received
        recovery_since = self._fall_recovery_since.setdefault(device_id, received)
        if (received - recovery_since).total_seconds() < self.settings.fall_recovery_seconds:
            return []
        self._fall_recovery_since.pop(device_id, None)
        self._fall_recovery_last_sample.pop(device_id, None)
        if self.database.resolve_alert(device_id, "fall_suspected_demo", received):
            resolved = self.database.list_alerts(state="resolved", device_id=device_id, limit=1)
            return resolved[:1]
        return []
