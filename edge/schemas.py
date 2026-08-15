from __future__ import annotations

import json
import re
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)


DeviceId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$"),
]
BootId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_-]{4,64}$"),
]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


def require_json_number(value: object) -> object:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("value must be a JSON number")
    return value


StrictFiniteNumber = Annotated[
    float,
    BeforeValidator(require_json_number),
    Field(allow_inf_nan=False),
]
PpgState: TypeAlias = Literal[
    "valid",
    "no_finger",
    "warming_up",
    "motion",
    "clipping",
    "low_perfusion",
    "unstable",
    "sample_loss",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_by_alias=True,
        validate_by_name=False,
        serialize_by_alias=True,
    )


class Vitals(StrictModel):
    heart_rate_bpm: Annotated[FiniteFloat, Field(gt=0, le=300)] | None
    spo2_pct: Annotated[FiniteFloat, Field(ge=0, le=100)] | None
    skin_temp_c: Annotated[FiniteFloat, Field(ge=-55, le=125)] | None


class Motion(StrictModel):
    accel_g: Annotated[FiniteFloat, Field(ge=0, le=32)] | None
    gyro_dps: Annotated[FiniteFloat, Field(ge=0, le=4000)] | None
    fall_state: Literal[
        "idle",
        "low_g",
        "impact",
        "verify_stillness",
        "alarm",
        "acked",
        "refractory",
        "unknown",
    ]


class Quality(StrictModel):
    ppg: Annotated[FiniteFloat, Field(ge=0, le=1)] | None
    finger_present: bool
    motion_artifact: bool
    heart_rate_valid: bool
    spo2_valid: bool
    skin_temp_valid: bool
    motion_valid: bool


class SystemMetrics(StrictModel):
    rssi_dbm: Annotated[int, Field(ge=-127, le=0)] | None
    free_heap: Annotated[int, Field(ge=0)] | None
    fw: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    faults: list[Annotated[str, StringConstraints(min_length=1, max_length=80)]]


class Telemetry(StrictModel):
    schema_version: Literal["health.telemetry.v1"] = Field(alias="schema")
    device_id: DeviceId
    boot_id: BootId
    seq: Annotated[int, Field(ge=0, le=4_294_967_295)]
    uptime_ms: Annotated[int, Field(ge=0, le=4_294_967_295)]
    vitals: Vitals
    motion: Motion
    quality: Quality
    system: SystemMetrics

    @model_validator(mode="after")
    def values_follow_validity_flags(self) -> "Telemetry":
        pairs = (
            ("heart_rate", self.quality.heart_rate_valid, self.vitals.heart_rate_bpm),
            ("spo2", self.quality.spo2_valid, self.vitals.spo2_pct),
            ("skin_temp", self.quality.skin_temp_valid, self.vitals.skin_temp_c),
        )
        for name, valid, value in pairs:
            if valid and value is None:
                raise ValueError(f"{name} is valid but its value is null")
            if not valid and value is not None:
                raise ValueError(f"{name} is invalid; its value must be null")

        motion_values = (self.motion.accel_g, self.motion.gyro_dps)
        if self.quality.motion_valid and any(value is None for value in motion_values):
            raise ValueError("motion is valid but a motion value is null")
        if not self.quality.motion_valid and any(value is not None for value in motion_values):
            raise ValueError("motion is invalid; motion values must be null")
        if not self.quality.motion_valid and self.motion.fall_state != "unknown":
            raise ValueError("invalid motion must use fall_state='unknown'")

        if not self.quality.finger_present:
            if self.quality.heart_rate_valid or self.quality.spo2_valid:
                raise ValueError("PPG vitals cannot be valid without a finger")
        if (
            self.quality.heart_rate_valid or self.quality.spo2_valid
        ) and self.quality.ppg is None:
            raise ValueError("valid PPG vitals require a non-null ppg quality score")
        if (
            self.quality.heart_rate_valid or self.quality.spo2_valid
        ) and not self.quality.motion_valid:
            raise ValueError("valid PPG vitals require valid motion quality data")
        if self.quality.motion_artifact and (
            self.quality.heart_rate_valid or self.quality.spo2_valid
        ):
            raise ValueError("PPG vitals cannot be valid during motion artifact")
        return self


class VitalsV2(StrictModel):
    heart_rate_bpm: Annotated[FiniteFloat, Field(gt=0, le=300)] | None
    spo2_pct: Annotated[FiniteFloat, Field(ge=0, le=100)] | None


class Environment(StrictModel):
    ambient_temp_c: Annotated[FiniteFloat, Field(ge=0, le=50)] | None
    humidity_pct: Annotated[FiniteFloat, Field(ge=0, le=100)] | None


class QualityV2(StrictModel):
    ppg: Annotated[FiniteFloat, Field(ge=0, le=1)] | None
    finger_present: bool
    motion_artifact: bool
    heart_rate_valid: bool
    spo2_valid: bool
    motion_valid: bool
    ambient_temp_valid: bool
    humidity_valid: bool


class TelemetryV2(StrictModel):
    schema_version: Literal["health.telemetry.v2"] = Field(alias="schema")
    device_id: DeviceId
    boot_id: BootId
    seq: Annotated[int, Field(ge=0, le=4_294_967_295)]
    uptime_ms: Annotated[int, Field(ge=0, le=4_294_967_295)]
    vitals: VitalsV2
    environment: Environment
    motion: Motion
    quality: QualityV2
    system: SystemMetrics

    @model_validator(mode="after")
    def values_follow_validity_flags(self) -> "TelemetryV2":
        pairs = (
            ("heart_rate", self.quality.heart_rate_valid, self.vitals.heart_rate_bpm),
            ("spo2", self.quality.spo2_valid, self.vitals.spo2_pct),
            (
                "ambient_temp",
                self.quality.ambient_temp_valid,
                self.environment.ambient_temp_c,
            ),
            ("humidity", self.quality.humidity_valid, self.environment.humidity_pct),
        )
        for name, valid, value in pairs:
            if valid and value is None:
                raise ValueError(f"{name} is valid but its value is null")
            if not valid and value is not None:
                raise ValueError(f"{name} is invalid; its value must be null")

        motion_values = (self.motion.accel_g, self.motion.gyro_dps)
        if self.quality.motion_valid and any(value is None for value in motion_values):
            raise ValueError("motion is valid but a motion value is null")
        if not self.quality.motion_valid and any(value is not None for value in motion_values):
            raise ValueError("motion is invalid; motion values must be null")
        if not self.quality.motion_valid and self.motion.fall_state != "unknown":
            raise ValueError("invalid motion must use fall_state='unknown'")

        if not self.quality.finger_present:
            if self.quality.heart_rate_valid or self.quality.spo2_valid:
                raise ValueError("PPG vitals cannot be valid without a finger")
        if (
            self.quality.heart_rate_valid or self.quality.spo2_valid
        ) and self.quality.ppg is None:
            raise ValueError("valid PPG vitals require a non-null ppg quality score")
        if (
            self.quality.heart_rate_valid or self.quality.spo2_valid
        ) and not self.quality.motion_valid:
            raise ValueError("valid PPG vitals require valid motion quality data")
        if self.quality.motion_artifact and (
            self.quality.heart_rate_valid or self.quality.spo2_valid
        ):
            raise ValueError("PPG vitals cannot be valid during motion artifact")
        return self


class VitalsV3(StrictModel):
    heart_rate_bpm: Annotated[StrictFiniteNumber, Field(gt=0, le=300)] | None
    spo2_pct: Annotated[StrictFiniteNumber, Field(ge=0, le=100)] | None


class Wearable(StrictModel):
    wrist_surface_temp_c: Annotated[StrictFiniteNumber, Field(ge=0, le=50)] | None


class MotionV3(StrictModel):
    accel_g: Annotated[StrictFiniteNumber, Field(ge=0, le=32)] | None
    gyro_dps: Annotated[StrictFiniteNumber, Field(ge=0, le=4000)] | None
    fall_state: Literal[
        "idle",
        "low_g",
        "impact",
        "verify_stillness",
        "alarm",
        "acked",
        "refractory",
        "unknown",
    ]


class QualityV3(StrictModel):
    ppg: Annotated[StrictFiniteNumber, Field(ge=0, le=1)] | None
    finger_present: StrictBool
    motion_artifact: StrictBool
    heart_rate_valid: StrictBool
    spo2_valid: StrictBool
    motion_valid: StrictBool
    wrist_surface_temp_valid: StrictBool


class SystemMetricsV3(StrictModel):
    rssi_dbm: Annotated[StrictInt, Field(ge=-127, le=0)] | None
    free_heap: Annotated[StrictInt, Field(ge=0)] | None
    fw: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    faults: list[Annotated[str, StringConstraints(min_length=1, max_length=80)]]


class TelemetryV3(StrictModel):
    schema_version: Literal["health.telemetry.v3"] = Field(alias="schema")
    device_id: DeviceId
    boot_id: BootId
    seq: Annotated[StrictInt, Field(ge=0, le=4_294_967_295)]
    uptime_ms: Annotated[StrictInt, Field(ge=0, le=4_294_967_295)]
    vitals: VitalsV3
    wearable: Wearable
    motion: MotionV3
    quality: QualityV3
    system: SystemMetricsV3

    @model_validator(mode="after")
    def values_follow_validity_flags(self) -> "TelemetryV3":
        pairs = (
            ("heart_rate", self.quality.heart_rate_valid, self.vitals.heart_rate_bpm),
            ("spo2", self.quality.spo2_valid, self.vitals.spo2_pct),
            (
                "wrist_surface_temp",
                self.quality.wrist_surface_temp_valid,
                self.wearable.wrist_surface_temp_c,
            ),
        )
        for name, valid, value in pairs:
            if valid and value is None:
                raise ValueError(f"{name} is valid but its value is null")
            if not valid and value is not None:
                raise ValueError(f"{name} is invalid; its value must be null")

        motion_values = (self.motion.accel_g, self.motion.gyro_dps)
        if self.quality.motion_valid and any(value is None for value in motion_values):
            raise ValueError("motion is valid but a motion value is null")
        if not self.quality.motion_valid and any(value is not None for value in motion_values):
            raise ValueError("motion is invalid; motion values must be null")
        if not self.quality.motion_valid and self.motion.fall_state != "unknown":
            raise ValueError("invalid motion must use fall_state='unknown'")

        if not self.quality.finger_present:
            if self.quality.heart_rate_valid or self.quality.spo2_valid:
                raise ValueError("PPG vitals cannot be valid without a finger")
        if (
            self.quality.heart_rate_valid or self.quality.spo2_valid
        ) and self.quality.ppg is None:
            raise ValueError("valid PPG vitals require a non-null ppg quality score")
        if (
            self.quality.heart_rate_valid or self.quality.spo2_valid
        ) and not self.quality.motion_valid:
            raise ValueError("valid PPG vitals require valid motion quality data")
        if self.quality.motion_artifact and (
            self.quality.heart_rate_valid or self.quality.spo2_valid
        ):
            raise ValueError("PPG vitals cannot be valid during motion artifact")

        ds18b20_fault = "ds18b20_unavailable" in self.system.faults
        if self.quality.wrist_surface_temp_valid and ds18b20_fault:
            raise ValueError("valid wrist temperature cannot report ds18b20_unavailable")
        if not self.quality.wrist_surface_temp_valid and not ds18b20_fault:
            raise ValueError("invalid wrist temperature must report ds18b20_unavailable")
        return self


class VitalsV4(StrictModel):
    heart_rate_raw_bpm: Annotated[StrictFiniteNumber, Field(gt=0, le=300)] | None
    heart_rate_bpm: Annotated[StrictFiniteNumber, Field(gt=0, le=300)] | None
    spo2_raw_pct: Annotated[StrictFiniteNumber, Field(ge=0, le=100)] | None
    spo2_pct: Annotated[StrictFiniteNumber, Field(ge=0, le=100)] | None


class QualityV4(StrictModel):
    ppg: Annotated[StrictFiniteNumber, Field(ge=0, le=1)] | None
    ppg_state: PpgState
    finger_present: StrictBool
    motion_artifact: StrictBool
    heart_rate_valid: StrictBool
    spo2_valid: StrictBool
    motion_valid: StrictBool
    wrist_surface_temp_valid: StrictBool


class TelemetryV4(StrictModel):
    schema_version: Literal["health.telemetry.v4"] = Field(alias="schema")
    device_id: DeviceId
    boot_id: BootId
    seq: Annotated[StrictInt, Field(ge=0, le=4_294_967_295)]
    uptime_ms: Annotated[StrictInt, Field(ge=0, le=4_294_967_295)]
    vitals: VitalsV4
    wearable: Wearable
    motion: MotionV3
    quality: QualityV4
    system: SystemMetricsV3

    @model_validator(mode="after")
    def values_follow_validity_and_ppg_state(self) -> "TelemetryV4":
        confirmed_pairs = (
            ("heart_rate", self.quality.heart_rate_valid, self.vitals.heart_rate_bpm),
            ("spo2", self.quality.spo2_valid, self.vitals.spo2_pct),
            (
                "wrist_surface_temp",
                self.quality.wrist_surface_temp_valid,
                self.wearable.wrist_surface_temp_c,
            ),
        )
        for name, valid, value in confirmed_pairs:
            if valid and value is None:
                raise ValueError(f"{name} is valid but its value is null")
            if not valid and value is not None:
                raise ValueError(f"{name} is invalid; its value must be null")

        motion_values = (self.motion.accel_g, self.motion.gyro_dps)
        if self.quality.motion_valid and any(value is None for value in motion_values):
            raise ValueError("motion is valid but a motion value is null")
        if not self.quality.motion_valid and any(value is not None for value in motion_values):
            raise ValueError("motion is invalid; motion values must be null")
        if not self.quality.motion_valid and self.motion.fall_state != "unknown":
            raise ValueError("invalid motion must use fall_state='unknown'")

        confirmed_ppg = self.quality.heart_rate_valid or self.quality.spo2_valid
        if confirmed_ppg and self.quality.ppg_state != "valid":
            raise ValueError("confirmed PPG vitals require ppg_state='valid'")
        if confirmed_ppg and not self.quality.finger_present:
            raise ValueError("PPG vitals cannot be valid without a finger")
        if confirmed_ppg and self.quality.ppg is None:
            raise ValueError("valid PPG vitals require a non-null ppg quality score")
        if confirmed_ppg and not self.quality.motion_valid:
            raise ValueError("valid PPG vitals require valid motion quality data")
        if confirmed_ppg and self.quality.motion_artifact:
            raise ValueError("PPG vitals cannot be valid during motion artifact")

        if self.quality.ppg_state == "valid":
            if not self.quality.finger_present:
                raise ValueError("ppg_state='valid' requires a detected finger")
            if self.quality.ppg is None:
                raise ValueError("ppg_state='valid' requires a quality score")
            if not self.quality.motion_valid or self.quality.motion_artifact:
                raise ValueError("ppg_state='valid' requires clean motion data")
        if self.quality.ppg_state == "no_finger" and self.quality.finger_present:
            raise ValueError("ppg_state='no_finger' requires finger_present=false")
        if (
            not self.quality.finger_present
            and self.quality.ppg_state not in {"no_finger", "sample_loss"}
        ):
            raise ValueError(
                "finger_present=false requires ppg_state no_finger or sample_loss"
            )

        if self.quality.ppg_state in {"no_finger", "sample_loss"} and (
            self.vitals.heart_rate_raw_bpm is not None
            or self.vitals.spo2_raw_pct is not None
        ):
            raise ValueError(
                "raw PPG values must be null for no_finger or sample_loss"
            )

        ds18b20_fault = "ds18b20_unavailable" in self.system.faults
        if self.quality.wrist_surface_temp_valid and ds18b20_fault:
            raise ValueError("valid wrist temperature cannot report ds18b20_unavailable")
        if not self.quality.wrist_surface_temp_valid and not ds18b20_fault:
            raise ValueError("invalid wrist temperature must report ds18b20_unavailable")
        return self


TelemetryMessage: TypeAlias = Telemetry | TelemetryV2 | TelemetryV3 | TelemetryV4


def parse_telemetry(raw_json: str | bytes | bytearray) -> TelemetryMessage:
    """Parse a strict v1-v4 telemetry document by its schema discriminator."""
    payload = json.loads(raw_json)
    if not isinstance(payload, dict):
        raise ValueError("telemetry payload must be a JSON object")
    schema = payload.get("schema")
    if schema == "health.telemetry.v1":
        return Telemetry.model_validate(payload)
    if schema == "health.telemetry.v2":
        return TelemetryV2.model_validate(payload)
    if schema == "health.telemetry.v3":
        return TelemetryV3.model_validate(payload)
    if schema == "health.telemetry.v4":
        return TelemetryV4.model_validate(payload)
    raise ValueError("unsupported telemetry schema")


class FallEvent(StrictModel):
    schema_version: Literal["health.event.v1"] = Field(alias="schema")
    device_id: DeviceId
    boot_id: BootId
    event_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    seq: Annotated[int, Field(ge=0, le=4_294_967_295)]
    uptime_ms: Annotated[int, Field(ge=0, le=4_294_967_295)]
    type: Literal["fall_suspected_demo"]


class DeviceStatus(StrictModel):
    schema_version: Literal["health.status.v1"] = Field(alias="schema")
    device_id: DeviceId
    boot_id: BootId
    seq: Annotated[int, Field(ge=0, le=4_294_967_295)]
    uptime_ms: Annotated[int, Field(ge=0, le=4_294_967_295)]
    online: bool
    reason: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    command_session_id: UUID | None = None
    correlation_id: UUID | None = None
    system: SystemMetrics


class OpenProvisioningRequest(StrictModel):
    expected_command_session_id: UUID | None = None


class DeviceCommand(StrictModel):
    schema_version: Literal["health.command.v1"] = Field(alias="schema")
    device_id: DeviceId
    target_boot_id: BootId
    command_id: UUID
    command_session_id: UUID
    action: Literal["open_provisioning"]
    expires_uptime_ms: Annotated[StrictInt, Field(ge=0, le=4_294_967_295)]


class AckRequest(StrictModel):
    actor: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=240)] = ""


TOPIC_RE = re.compile(
    r"^iot-health/v1/devices/(?P<device_id>[a-z0-9][a-z0-9-]{0,31})/"
    r"(?P<kind>telemetry|event|status)$"
)


def parse_topic(topic: str) -> tuple[str, Literal["telemetry", "event", "status"]]:
    match = TOPIC_RE.fullmatch(topic)
    if not match:
        raise ValueError("unsupported MQTT topic")
    return match.group("device_id"), match.group("kind")  # type: ignore[return-value]
