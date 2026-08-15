from __future__ import annotations

import sqlite3
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
    recovery_seconds: float
    hysteresis: float
    severity: str
    message: str
    unit: str

    def public_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["non_clinical"] = True
        return result


@dataclass(frozen=True, slots=True)
class RuleStateSnapshot:
    pending_since: dict[tuple[str, str, str], datetime]
    last_rule_sample: dict[tuple[str, str, str], datetime]
    recovery_since: dict[tuple[str, str, str], datetime]
    recovery_last_sample: dict[tuple[str, str, str], datetime]
    fall_recovery_since: dict[tuple[str, str], datetime]
    fall_recovery_last_sample: dict[tuple[str, str], datetime]


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
                recovery_seconds=settings.recovery_seconds,
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
                recovery_seconds=settings.recovery_seconds,
                hysteresis=settings.hr_hysteresis,
                severity="warning",
                message="Nhịp tim tham khảo vượt ngưỡng demo cao",
                unit="bpm",
            ),
        )
        self._pending_since: dict[tuple[str, str, str], datetime] = {}
        self._last_rule_sample: dict[tuple[str, str, str], datetime] = {}
        self._recovery_since: dict[tuple[str, str, str], datetime] = {}
        self._recovery_last_sample: dict[tuple[str, str, str], datetime] = {}
        self._fall_recovery_since: dict[tuple[str, str], datetime] = {}
        self._fall_recovery_last_sample: dict[tuple[str, str], datetime] = {}

    def snapshot_state(self) -> RuleStateSnapshot:
        return RuleStateSnapshot(
            pending_since=dict(self._pending_since),
            last_rule_sample=dict(self._last_rule_sample),
            recovery_since=dict(self._recovery_since),
            recovery_last_sample=dict(self._recovery_last_sample),
            fall_recovery_since=dict(self._fall_recovery_since),
            fall_recovery_last_sample=dict(self._fall_recovery_last_sample),
        )

    def restore_state(self, snapshot: RuleStateSnapshot) -> None:
        self._pending_since = dict(snapshot.pending_since)
        self._last_rule_sample = dict(snapshot.last_rule_sample)
        self._recovery_since = dict(snapshot.recovery_since)
        self._recovery_last_sample = dict(snapshot.recovery_last_sample)
        self._fall_recovery_since = dict(snapshot.fall_recovery_since)
        self._fall_recovery_last_sample = dict(snapshot.fall_recovery_last_sample)

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
        self,
        telemetry: TelemetryMessage,
        received: datetime,
        connection: sqlite3.Connection | None = None,
    ) -> list[dict[str, object]]:
        changed: list[dict[str, object]] = []
        for rule in self.rules:
            value, is_valid = self._value_and_validity(telemetry, rule)
            key = (telemetry.device_id, telemetry.boot_id, rule.rule_id)
            active = self.database.get_active_alert(
                telemetry.device_id, rule.rule_id, connection=connection
            )

            if not is_valid or value is None:
                self._pending_since.pop(key, None)
                self._last_rule_sample.pop(key, None)
                self._clear_vital_recovery(key)
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
                    self._clear_vital_recovery(key)
                    changed.append(
                        self.database.open_or_touch_alert(
                            device_id=telemetry.device_id,
                            rule_id=rule.rule_id,
                            severity=rule.severity,
                            message=rule.message,
                            happened=received,
                            value=value,
                            connection=connection,
                        )
                    )
                elif recovered:
                    previous_recovery = self._recovery_last_sample.get(key)
                    recovery_gap_broken = previous_recovery is None or (
                        (received - previous_recovery).total_seconds() < 0
                        or (received - previous_recovery).total_seconds()
                        > self.settings.max_sample_gap_seconds
                    )
                    if recovery_gap_broken:
                        self._recovery_since[key] = received
                    self._recovery_last_sample[key] = received
                    recovery_since = self._recovery_since.setdefault(key, received)
                    if (
                        (received - recovery_since).total_seconds()
                        >= rule.recovery_seconds
                        and self.database.resolve_alert(
                            telemetry.device_id,
                            rule.rule_id,
                            received,
                            connection=connection,
                        )
                    ):
                        self._clear_vital_recovery(key)
                        resolved = self.database.list_alerts(
                            state="resolved",
                            device_id=telemetry.device_id,
                            limit=1,
                            connection=connection,
                        )
                        if resolved:
                            changed.append(resolved[0])
                else:
                    self._clear_vital_recovery(key)
                continue

            self._clear_vital_recovery(key)
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
                        connection=connection,
                    )
                )
                self._pending_since.pop(key, None)

        changed.extend(self._evaluate_fall_state(telemetry, received, connection))
        return changed

    def _value_and_validity(
        self, telemetry: TelemetryMessage, rule: DemoRule
    ) -> tuple[float | None, bool]:
        ppg_state_valid = getattr(telemetry.quality, "ppg_state", "valid") == "valid"
        if rule.field == "spo2_pct":
            valid = (
                telemetry.quality.spo2_valid
                and ppg_state_valid
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
                and ppg_state_valid
                and telemetry.quality.finger_present
                and telemetry.quality.motion_valid
                and not telemetry.quality.motion_artifact
                and telemetry.quality.ppg is not None
                and telemetry.quality.ppg >= self.settings.min_ppg_quality
            )
            return telemetry.vitals.heart_rate_bpm, valid
        raise ValueError(f"unsupported demo rule field: {rule.field}")

    def _clear_vital_recovery(self, key: tuple[str, str, str]) -> None:
        self._recovery_since.pop(key, None)
        self._recovery_last_sample.pop(key, None)

    def _evaluate_fall_state(
        self,
        telemetry: TelemetryMessage,
        received: datetime,
        connection: sqlite3.Connection | None = None,
    ) -> list[dict[str, object]]:
        device_id = telemetry.device_id
        session_key = (device_id, telemetry.boot_id)
        active = self.database.get_active_alert(
            device_id, "fall_suspected_demo", connection=connection
        )
        if not telemetry.quality.motion_valid:
            self._fall_recovery_since.pop(session_key, None)
            self._fall_recovery_last_sample.pop(session_key, None)
            return []
        if not active or telemetry.motion.fall_state != "idle":
            self._fall_recovery_since.pop(session_key, None)
            self._fall_recovery_last_sample.pop(session_key, None)
            return []
        previous_sample = self._fall_recovery_last_sample.get(session_key)
        if previous_sample is None or (
            (received - previous_sample).total_seconds() < 0
            or (received - previous_sample).total_seconds()
            > self.settings.max_sample_gap_seconds
        ):
            self._fall_recovery_since[session_key] = received
        self._fall_recovery_last_sample[session_key] = received
        recovery_since = self._fall_recovery_since.setdefault(session_key, received)
        if (received - recovery_since).total_seconds() < self.settings.fall_recovery_seconds:
            return []
        self._fall_recovery_since.pop(session_key, None)
        self._fall_recovery_last_sample.pop(session_key, None)
        if self.database.resolve_alert(
            device_id,
            "fall_suspected_demo",
            received,
            connection=connection,
        ):
            resolved = self.database.list_alerts(
                state="resolved",
                device_id=device_id,
                limit=1,
                connection=connection,
            )
            return resolved[:1]
        return []
