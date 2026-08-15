from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import re
from statistics import median
import sys
from typing import Any

from .experiment import (
    ARTIFACT_VERSION,
    MIN_PERCENTILE_SAMPLES,
    SOURCE_FILES,
    SOURCE_FINGERPRINT_SCOPE,
    _atomic_write,
    config_digest,
    config_material,
    summarize_samples,
)
from .mqtt_simulator import DEVICE_ID_RE
from .network_profiles import build_schedule, get_profile


ANALYSIS_ID = "rq2-matched-profile-aggregate-v5"
PROFILES = ("lan-baseline", "remote-app-emulated")
RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SCENARIO_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_ARTIFACT_BYTES = 256 * 1024
MAX_SAMPLES_ARTIFACT_BYTES = 32 * 1024 * 1024
DEFAULT_MIN_SEEDS = 30
BOOTSTRAP_SEED = 532
BOOTSTRAP_RESAMPLES = 5_000
BOOTSTRAP_CONFIDENCE = 0.95
EXPECTED_CLOCK_DOMAIN = "host_monotonic_same_process"
EXPECTED_INJECTION_POINT = "before_mqtt_publish"
EXPECTED_PROFILE_KIND = "app_impairment"
EXPECTED_NETWORK_CLAIM = "none"
EXPECTED_PRIMARY_LATENCY_KIND = "schedule_to_api_polling_upper_bound"
EXPECTED_DIAGNOSTIC_LATENCY_KIND = "publish_to_api_polling_upper_bound"
SOURCE_STATE_VALUES = {"commit_clean", "worktree_uncommitted"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
BOOT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SAMPLE_FIELDS = {
    "artifact_version",
    "run_id",
    "device_id",
    "boot_id",
    "stream",
    "seq",
    "scheduled_index",
    "scheduled",
    "scheduled_delay_ms",
    "scheduled_offset_ms",
    "schedule_slip_ms",
    "slot_to_publish_ms",
    "intentionally_dropped",
    "drop_reason",
    "publish_attempted",
    "attempt_count",
    "published",
    "ingested",
    "api_observed",
    "publish_to_api_upper_bound_ms",
    "schedule_to_api_upper_bound_ms",
    "polling_error_bound_ms",
    "error_code",
}
MANIFEST_FIELDS = {
    "artifact_version",
    "run_id",
    "status",
    "created_at",
    "completed_at",
    "profile",
    "scenario",
    "seed",
    "count",
    "interval_seconds",
    "protocol",
    "topic_namespace",
    "device_id",
    "boot_id",
    "schema",
    "commit",
    "source_provenance",
    "config_hash",
    "clock_domain",
    "polling_resolution_ms",
    "observe_timeout_seconds",
    "injection_point",
    "claims",
}


class AggregateError(ValueError):
    """Fail-closed validation error with a non-sensitive public code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _reject_constant(_value: str) -> None:
    raise ValueError("non_finite_json_number")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _strict_json_loads(content: str) -> Any:
    return json.loads(
        content,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    profile: str
    profile_version: str
    seed: int
    attempted_delivery_ratio: float
    scheduled_observation_ratio: float
    intentional_drop_ratio: float
    publish_p50_ms: float
    publish_p95_ms: float
    schedule_p50_ms: float
    schedule_p95_ms: float
    schedule_slip_p50_ms: float
    schedule_slip_p95_ms: float
    scenario: str
    count: int
    interval_seconds: float
    commit: str
    polling_resolution_ms: int
    protocol_name: str
    protocol_version: str
    protocol_transport: str
    clock_domain: str
    injection_point: str
    profile_kind: str
    network_claim: str
    measured_5g: bool
    primary_latency_kind: str
    diagnostic_latency_kind: str
    source_state: str
    source_sha256: str
    source_files: tuple[str, ...]
    device_id: str
    observe_timeout_seconds: float


@dataclass(frozen=True, slots=True)
class ValidatedCompletedRun:
    """A single, strict read of the artifacts used for both API and analysis."""

    record: RunRecord
    manifest: dict[str, Any]
    summary: dict[str, Any]


def _read_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise AggregateError("missing_artifact")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise AggregateError("missing_artifact") from exc
    if size <= 0 or size > MAX_ARTIFACT_BYTES:
        raise AggregateError("invalid_artifact_size")
    try:
        payload = _strict_json_loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise AggregateError("invalid_json") from exc
    if not isinstance(payload, dict):
        raise AggregateError("artifact_not_object")
    return payload


def _read_samples_artifact(path: Path, *, expected_count: int) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise AggregateError("missing_artifact")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise AggregateError("missing_artifact") from exc
    if size <= 0 or size > MAX_SAMPLES_ARTIFACT_BYTES:
        raise AggregateError("invalid_artifact_size")
    samples: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if line_number > expected_count:
                    raise AggregateError("sample_count_mismatch")
                if not line.strip() or len(line.encode("utf-8")) > MAX_ARTIFACT_BYTES:
                    raise AggregateError("invalid_sample_line")
                payload = _strict_json_loads(line)
                if not isinstance(payload, dict):
                    raise AggregateError("sample_not_object")
                if set(payload) != SAMPLE_FIELDS:
                    raise AggregateError("invalid_sample_shape")
                samples.append({key: payload[key] for key in SAMPLE_FIELDS if key in payload})
    except AggregateError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise AggregateError("invalid_samples_jsonl") from exc
    if len(samples) != expected_count:
        raise AggregateError("sample_count_mismatch")
    return samples


def _mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise AggregateError("invalid_nested_object")
    return value


def _boolean(parent: dict[str, Any], key: str) -> bool:
    value = parent.get(key)
    if not isinstance(value, bool):
        raise AggregateError("invalid_boolean")
    return value


def _string(parent: dict[str, Any], key: str, pattern: re.Pattern[str] | None = None) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value:
        raise AggregateError("invalid_string")
    if pattern is not None and not pattern.fullmatch(value):
        raise AggregateError("invalid_string")
    return value


def _finite_number(
    parent: dict[str, Any],
    key: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = parent.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AggregateError("invalid_numeric_metric")
    result = float(value)
    if not math.isfinite(result):
        raise AggregateError("non_finite_metric")
    if minimum is not None and result < minimum:
        raise AggregateError("numeric_metric_out_of_range")
    if maximum is not None and result > maximum:
        raise AggregateError("numeric_metric_out_of_range")
    return result


def _integer(
    parent: dict[str, Any],
    key: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = parent.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise AggregateError("invalid_integer")
    if not minimum <= value <= maximum:
        raise AggregateError("integer_out_of_range")
    return value


def _exact_string(parent: dict[str, Any], key: str, expected: str) -> str:
    value = parent.get(key)
    if value != expected:
        raise AggregateError("measurement_boundary_mismatch")
    return expected


def _validate_samples(
    samples: list[dict[str, Any]],
    *,
    run_id: str,
    device_id: str,
    boot_id: str,
    polling_resolution_ms: int,
    interval_seconds: float,
    schedule: tuple[Any, ...],
) -> None:
    for index, (sample, scheduled) in enumerate(zip(samples, schedule, strict=True)):
        expected_identity = {
            "artifact_version": ARTIFACT_VERSION,
            "run_id": run_id,
            "device_id": device_id,
            "boot_id": boot_id,
            "stream": "telemetry",
            "seq": index + 1,
            "scheduled_index": index,
            "scheduled": True,
            "scheduled_delay_ms": scheduled.delay_ms,
            "scheduled_offset_ms": round(index * interval_seconds * 1000, 3),
            "intentionally_dropped": scheduled.intentionally_dropped,
            "drop_reason": scheduled.drop_reason,
            "polling_error_bound_ms": polling_resolution_ms,
        }
        if any(sample.get(key) != value for key, value in expected_identity.items()):
            raise AggregateError("sample_schedule_or_identity_mismatch")
        scheduled_offset = sample.get("scheduled_offset_ms")
        schedule_slip = sample.get("schedule_slip_ms")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
            for value in (scheduled_offset, schedule_slip)
        ):
            raise AggregateError("invalid_schedule_timing")
        for key in (
            "scheduled",
            "intentionally_dropped",
            "publish_attempted",
            "published",
            "ingested",
            "api_observed",
        ):
            if not isinstance(sample.get(key), bool):
                raise AggregateError("invalid_sample_flag")
        attempt_count = sample.get("attempt_count")
        if isinstance(attempt_count, bool) or not isinstance(attempt_count, int):
            raise AggregateError("invalid_sample_attempt_count")

        if scheduled.intentionally_dropped:
            if (
                sample["publish_attempted"]
                or attempt_count != 0
                or sample["published"]
                or sample["ingested"]
                or sample["api_observed"]
                or sample["publish_to_api_upper_bound_ms"] is not None
                or sample["schedule_to_api_upper_bound_ms"] is not None
                or sample["slot_to_publish_ms"] is not None
                or sample["error_code"] is not None
            ):
                raise AggregateError("invalid_intentional_drop_flags")
            continue

        if not sample["publish_attempted"] or attempt_count < 1:
            raise AggregateError("invalid_publish_attempt_flags")
        slot_to_publish = sample["slot_to_publish_ms"]
        if (
            isinstance(slot_to_publish, bool)
            or not isinstance(slot_to_publish, (int, float))
            or not math.isfinite(float(slot_to_publish))
            or float(slot_to_publish) < 0
        ):
            raise AggregateError("invalid_slot_to_publish_timing")
        if not sample["published"]:
            raise AggregateError("completed_run_has_publish_failure")
        if sample["ingested"] is not sample["api_observed"]:
            raise AggregateError("invalid_observation_flags")
        publish_latency = sample["publish_to_api_upper_bound_ms"]
        schedule_latency = sample["schedule_to_api_upper_bound_ms"]
        if sample["api_observed"]:
            if sample["error_code"] is not None:
                raise AggregateError("observed_sample_has_error")
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
                for value in (publish_latency, schedule_latency)
            ):
                raise AggregateError("invalid_sample_latency")
            if abs(
                float(schedule_latency)
                - (float(publish_latency) + float(slot_to_publish))
            ) > 1.0:
                raise AggregateError("schedule_latency_timeline_mismatch")
        elif (
            publish_latency is not None
            or schedule_latency is not None
            or sample["error_code"] != "api_observation_timeout"
        ):
            raise AggregateError("invalid_unobserved_sample")


def validate_completed_run(
    run_dir: Path, run_prefix: str = ""
) -> ValidatedCompletedRun:
    manifest = _read_json_object(run_dir / "manifest.json")
    summary = _read_json_object(run_dir / "summary.json")
    if set(manifest) != MANIFEST_FIELDS:
        raise AggregateError("invalid_manifest_shape")

    if manifest.get("artifact_version") != ARTIFACT_VERSION:
        raise AggregateError("unsupported_manifest_version")
    if summary.get("artifact_version") != ARTIFACT_VERSION:
        raise AggregateError("unsupported_summary_version")

    run_id = manifest.get("run_id")
    if (
        not isinstance(run_id, str)
        or not RUN_ID_RE.fullmatch(run_id)
        or not run_id.startswith(run_prefix)
        or run_id != run_dir.name
        or summary.get("run_id") != run_id
    ):
        raise AggregateError("invalid_run_id")

    if manifest.get("status") != "completed" or summary.get("status") != "completed":
        raise AggregateError("run_not_completed")
    if not isinstance(manifest.get("created_at"), str) or not manifest["created_at"].strip():
        raise AggregateError("missing_creation_marker")
    completed_at = manifest.get("completed_at")
    if not isinstance(completed_at, str) or not completed_at.strip():
        raise AggregateError("missing_completion_marker")

    profile = _mapping(manifest, "profile")
    profile_name = profile.get("name")
    if profile_name not in PROFILES:
        raise AggregateError("unsupported_profile")
    canonical_profile = get_profile(profile_name)
    canonical_profile_dict = canonical_profile.public_dict()
    if any(profile.get(key) != value for key, value in canonical_profile_dict.items()):
        raise AggregateError("profile_definition_mismatch")
    profile_version = canonical_profile.version

    seed = _integer(manifest, "seed", minimum=0, maximum=2**32 - 1)
    scenario = manifest.get("scenario")
    if not isinstance(scenario, str) or not SCENARIO_RE.fullmatch(scenario):
        raise AggregateError("invalid_scenario")
    count = _integer(manifest, "count", minimum=20, maximum=10_000)
    interval_seconds = _finite_number(
        manifest, "interval_seconds", minimum=0.001, maximum=60.0
    )
    commit = manifest.get("commit")
    if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        raise AggregateError("invalid_commit")
    source_provenance = _mapping(manifest, "source_provenance")
    if set(source_provenance) != {
        "scope",
        "head_commit",
        "source_state",
        "source_sha256",
        "source_files",
    }:
        raise AggregateError("invalid_source_fingerprint_shape")
    _exact_string(source_provenance, "scope", SOURCE_FINGERPRINT_SCOPE)
    source_head_commit = _string(source_provenance, "head_commit", COMMIT_RE)
    source_state = source_provenance.get("source_state")
    if source_state not in SOURCE_STATE_VALUES:
        raise AggregateError("invalid_source_state")
    source_sha256 = _string(source_provenance, "source_sha256", SHA256_RE)
    source_files_value = source_provenance.get("source_files")
    if source_files_value != list(SOURCE_FILES):
        raise AggregateError("source_file_set_mismatch")
    source_files = tuple(source_files_value)
    if commit != source_head_commit:
        raise AggregateError("source_commit_mismatch")

    device_id = _string(manifest, "device_id", DEVICE_ID_RE)
    boot_id = _string(manifest, "boot_id", BOOT_ID_RE)
    _exact_string(manifest, "schema", "health.telemetry.v3")
    _exact_string(
        manifest,
        "topic_namespace",
        "iot-health/v1/devices/{device_id}/{stream}",
    )

    protocol = _mapping(manifest, "protocol")
    if set(protocol) != {"name", "version", "transport"}:
        raise AggregateError("invalid_protocol_shape")
    protocol_name = _exact_string(protocol, "name", "MQTT")
    protocol_version = _exact_string(protocol, "version", "3.1.1")
    protocol_transport = _exact_string(protocol, "transport", "TCP")
    polling_resolution_ms = _integer(
        manifest, "polling_resolution_ms", minimum=20, maximum=5_000
    )
    observe_timeout_seconds = _finite_number(
        manifest, "observe_timeout_seconds", minimum=0.001, maximum=60.0
    )
    clock_domain = _exact_string(manifest, "clock_domain", EXPECTED_CLOCK_DOMAIN)
    injection_point = _exact_string(
        manifest, "injection_point", EXPECTED_INJECTION_POINT
    )

    profile_kind = _exact_string(profile, "profile_kind", EXPECTED_PROFILE_KIND)
    _exact_string(profile, "network_claim", EXPECTED_NETWORK_CLAIM)
    _exact_string(profile, "injection_point", EXPECTED_INJECTION_POINT)

    claims = _mapping(manifest, "claims")
    if set(claims) != {
        "profile_kind",
        "network_claim",
        "measured_5g",
        "primary_latency_kind",
        "diagnostic_latency_kind",
    }:
        raise AggregateError("invalid_claim_shape")
    _exact_string(claims, "profile_kind", EXPECTED_PROFILE_KIND)
    network_claim = _exact_string(
        claims, "network_claim", EXPECTED_NETWORK_CLAIM
    )
    if claims.get("measured_5g") is not False:
        raise AggregateError("measurement_boundary_mismatch")
    measured_5g = False
    primary_latency_kind = _exact_string(
        claims, "primary_latency_kind", EXPECTED_PRIMARY_LATENCY_KIND
    )
    diagnostic_latency_kind = _exact_string(
        claims, "diagnostic_latency_kind", EXPECTED_DIAGNOSTIC_LATENCY_KIND
    )

    expected_hash = config_digest(
        config_material(
            profile=canonical_profile,
            scenario=scenario,
            count=count,
            seed=seed,
            interval_seconds=interval_seconds,
            device_id=device_id,
            polling_resolution_ms=polling_resolution_ms,
            observe_timeout_seconds=observe_timeout_seconds,
        )
    )
    if manifest.get("config_hash") != expected_hash:
        raise AggregateError("config_hash_mismatch")

    schedule = build_schedule(canonical_profile, count=count, seed=seed)
    samples = _read_samples_artifact(run_dir / "samples.jsonl", expected_count=count)
    _validate_samples(
        samples,
        run_id=run_id,
        device_id=device_id,
        boot_id=boot_id,
        polling_resolution_ms=polling_resolution_ms,
        interval_seconds=interval_seconds,
        schedule=schedule,
    )
    recomputed = summarize_samples(
        run_id,
        samples,
        status="completed",
        polling_resolution_ms=polling_resolution_ms,
    )
    if summary != recomputed:
        raise AggregateError("summary_reconciliation_failed")

    if recomputed["percentiles_available"] is not True:
        raise AggregateError("run_percentiles_unavailable")
    if (
        recomputed["latency_sample_count"] < MIN_PERCENTILE_SAMPLES
        or recomputed["schedule_to_api_latency_sample_count"]
        < MIN_PERCENTILE_SAMPLES
    ):
        raise AggregateError("run_percentiles_unavailable")

    attempted_delivery_ratio = float(recomputed["attempted_delivery_ratio"])
    scheduled_observation_ratio = float(recomputed["scheduled_observation_ratio"])
    intentional_drop_ratio = float(recomputed["intentional_drop_ratio"])
    publish_p50_ms = float(recomputed["publish_to_api_upper_bound_p50_ms"])
    publish_p95_ms = float(recomputed["publish_to_api_upper_bound_p95_ms"])
    schedule_p50_ms = float(recomputed["schedule_to_api_upper_bound_p50_ms"])
    schedule_p95_ms = float(recomputed["schedule_to_api_upper_bound_p95_ms"])
    schedule_slip_p50_ms = float(recomputed["schedule_slip_p50_ms"])
    schedule_slip_p95_ms = float(recomputed["schedule_slip_p95_ms"])

    record = RunRecord(
        run_id=run_id,
        profile=profile_name,
        profile_version=profile_version,
        seed=seed,
        attempted_delivery_ratio=attempted_delivery_ratio,
        scheduled_observation_ratio=scheduled_observation_ratio,
        intentional_drop_ratio=intentional_drop_ratio,
        publish_p50_ms=publish_p50_ms,
        publish_p95_ms=publish_p95_ms,
        schedule_p50_ms=schedule_p50_ms,
        schedule_p95_ms=schedule_p95_ms,
        schedule_slip_p50_ms=schedule_slip_p50_ms,
        schedule_slip_p95_ms=schedule_slip_p95_ms,
        scenario=scenario,
        count=count,
        interval_seconds=interval_seconds,
        commit=commit,
        polling_resolution_ms=polling_resolution_ms,
        protocol_name=protocol_name,
        protocol_version=protocol_version,
        protocol_transport=protocol_transport,
        clock_domain=clock_domain,
        injection_point=injection_point,
        profile_kind=profile_kind,
        network_claim=network_claim,
        measured_5g=measured_5g,
        primary_latency_kind=primary_latency_kind,
        diagnostic_latency_kind=diagnostic_latency_kind,
        source_state=source_state,
        source_sha256=source_sha256,
        source_files=source_files,
        device_id=device_id,
        observe_timeout_seconds=observe_timeout_seconds,
    )
    return ValidatedCompletedRun(record=record, manifest=manifest, summary=summary)


def _validate_run(run_dir: Path, run_prefix: str) -> RunRecord:
    return validate_completed_run(run_dir, run_prefix).record


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _rounded(value: float, metric: str) -> float:
    decimals = 6 if metric.endswith("ratio") else 3
    return round(float(value), decimals)


def _bootstrap_median_ci(
    values: list[float],
    *,
    metric: str,
    profile: str,
) -> dict[str, float]:
    if BOOTSTRAP_RESAMPLES < 2_000:
        raise AggregateError("insufficient_bootstrap_resamples")
    seed_material = f"{BOOTSTRAP_SEED}:{profile}:{metric}".encode("utf-8")
    derived_seed = int.from_bytes(sha256(seed_material).digest()[:8], "big")
    rng = random.Random(derived_seed)
    sample_size = len(values)
    estimates = [
        float(median(values[rng.randrange(sample_size)] for _ in range(sample_size)))
        for _ in range(BOOTSTRAP_RESAMPLES)
    ]
    alpha = (1.0 - BOOTSTRAP_CONFIDENCE) / 2.0
    return {
        "lower": _rounded(_quantile(estimates, alpha), metric),
        "upper": _rounded(_quantile(estimates, 1.0 - alpha), metric),
    }


def _single_value(records: list[RunRecord], field: str) -> Any:
    values = {getattr(record, field) for record in records}
    if len(values) != 1:
        raise AggregateError("experimental_control_mismatch")
    return next(iter(values))


def _metric_payload(records: list[RunRecord], field: str, metric: str) -> dict[str, Any]:
    values = [float(getattr(record, field)) for record in records]
    return {
        "median": _rounded(float(median(values)), metric),
        "bootstrap_95_ci": _bootstrap_median_ci(
            values, metric=metric, profile=records[0].profile
        ),
    }


def _paired_metric_payload(
    by_pair: dict[tuple[str, int], RunRecord],
    matched_seeds: list[int],
    field: str,
    metric: str,
) -> dict[str, Any]:
    deltas = [
        float(getattr(by_pair[(PROFILES[1], seed)], field))
        - float(getattr(by_pair[(PROFILES[0], seed)], field))
        for seed in matched_seeds
    ]
    return {
        "median_delta": _rounded(float(median(deltas)), metric),
        "bootstrap_95_ci": _bootstrap_median_ci(
            deltas,
            metric=metric,
            profile="paired-seed-delta",
        ),
    }


def build_aggregate(
    input_dir: Path,
    *,
    run_prefix: str = "nt532-rq2-v5-",
    min_seeds: int = DEFAULT_MIN_SEEDS,
) -> dict[str, Any]:
    if not isinstance(run_prefix, str) or not RUN_ID_RE.fullmatch(run_prefix):
        raise AggregateError("invalid_run_prefix")
    if isinstance(min_seeds, bool) or not isinstance(min_seeds, int) or min_seeds < 1:
        raise AggregateError("invalid_min_seeds")
    if not input_dir.is_dir():
        raise AggregateError("input_dir_unavailable")

    candidates = sorted(
        (child for child in input_dir.iterdir() if child.name.startswith(run_prefix)),
        key=lambda child: child.name,
    )
    if not candidates:
        raise AggregateError("no_matching_runs")
    if any(child.is_symlink() for child in candidates):
        raise AggregateError("symlink_run_forbidden")
    if any(not child.is_dir() for child in candidates):
        raise AggregateError("invalid_run_entry")
    run_dirs = candidates

    records = [_validate_run(run_dir, run_prefix) for run_dir in run_dirs]
    by_pair: dict[tuple[str, int], RunRecord] = {}
    for record in records:
        pair = (record.profile, record.seed)
        if pair in by_pair:
            raise AggregateError("duplicate_profile_seed")
        by_pair[pair] = record

    seeds_by_profile = {
        profile: {record.seed for record in records if record.profile == profile}
        for profile in PROFILES
    }
    if any(not seeds for seeds in seeds_by_profile.values()):
        raise AggregateError("missing_profile")
    if seeds_by_profile[PROFILES[0]] != seeds_by_profile[PROFILES[1]]:
        raise AggregateError("mismatched_seed_sets")
    matched_seeds = sorted(seeds_by_profile[PROFILES[0]])
    if len(matched_seeds) < min_seeds:
        raise AggregateError("insufficient_independent_seeds")

    # Experimental controls must be identical across every run; profile is the
    # only intended treatment difference.
    controls = {
        "scenario": _single_value(records, "scenario"),
        "messages_per_run": _single_value(records, "count"),
        "interval_seconds": _single_value(records, "interval_seconds"),
        "commit": _single_value(records, "commit"),
        "protocol": {
            "name": _single_value(records, "protocol_name"),
            "version": _single_value(records, "protocol_version"),
            "transport": _single_value(records, "protocol_transport"),
        },
        "source_provenance": {
            "head_commit": _single_value(records, "commit"),
            "source_state": _single_value(records, "source_state"),
            "source_sha256": _single_value(records, "source_sha256"),
            "source_files": list(_single_value(records, "source_files")),
        },
        "device_id": _single_value(records, "device_id"),
        "observe_timeout_seconds": _single_value(records, "observe_timeout_seconds"),
    }
    boundaries = {
        "clock_domain": _single_value(records, "clock_domain"),
        "polling_resolution_ms": _single_value(records, "polling_resolution_ms"),
        "primary_latency_kind": _single_value(records, "primary_latency_kind"),
        "diagnostic_latency_kind": _single_value(
            records, "diagnostic_latency_kind"
        ),
        "injection_point": _single_value(records, "injection_point"),
        "profile_kind": _single_value(records, "profile_kind"),
        "network_claim": _single_value(records, "network_claim"),
        "measured_5g": _single_value(records, "measured_5g"),
    }

    profile_payload: dict[str, Any] = {}
    for profile in PROFILES:
        profile_records = sorted(
            (record for record in records if record.profile == profile),
            key=lambda record: record.seed,
        )
        profile_payload[profile] = {
            "profile_version": _single_value(profile_records, "profile_version"),
            "run_count": len(profile_records),
            "metrics": {
                "scheduled_observation_ratio": _metric_payload(
                    profile_records,
                    "scheduled_observation_ratio",
                    "scheduled_observation_ratio",
                ),
                "intentional_drop_ratio": _metric_payload(
                    profile_records, "intentional_drop_ratio", "intentional_drop_ratio"
                ),
                "attempted_delivery_ratio": _metric_payload(
                    profile_records,
                    "attempted_delivery_ratio",
                    "attempted_delivery_ratio",
                ),
                "publish_to_api_upper_bound_p50_ms": _metric_payload(
                    profile_records,
                    "publish_p50_ms",
                    "publish_to_api_upper_bound_p50_ms",
                ),
                "publish_to_api_upper_bound_p95_ms": _metric_payload(
                    profile_records,
                    "publish_p95_ms",
                    "publish_to_api_upper_bound_p95_ms",
                ),
                "schedule_to_api_upper_bound_p50_ms": _metric_payload(
                    profile_records,
                    "schedule_p50_ms",
                    "schedule_to_api_upper_bound_p50_ms",
                ),
                "schedule_to_api_upper_bound_p95_ms": _metric_payload(
                    profile_records,
                    "schedule_p95_ms",
                    "schedule_to_api_upper_bound_p95_ms",
                ),
                "schedule_slip_p50_ms": _metric_payload(
                    profile_records, "schedule_slip_p50_ms", "schedule_slip_p50_ms"
                ),
                "schedule_slip_p95_ms": _metric_payload(
                    profile_records, "schedule_slip_p95_ms", "schedule_slip_p95_ms"
                ),
            },
        }

    paired_deltas = {
        "direction": f"{PROFILES[1]}_minus_{PROFILES[0]}",
        "unit": "matched_seed_pair",
        "metrics": {
            "scheduled_observation_ratio": _paired_metric_payload(
                by_pair,
                matched_seeds,
                "scheduled_observation_ratio",
                "scheduled_observation_ratio",
            ),
            "attempted_delivery_ratio": _paired_metric_payload(
                by_pair,
                matched_seeds,
                "attempted_delivery_ratio",
                "attempted_delivery_ratio",
            ),
            "schedule_to_api_upper_bound_p50_ms": _paired_metric_payload(
                by_pair,
                matched_seeds,
                "schedule_p50_ms",
                "schedule_to_api_upper_bound_p50_ms",
            ),
            "schedule_to_api_upper_bound_p95_ms": _paired_metric_payload(
                by_pair,
                matched_seeds,
                "schedule_p95_ms",
                "schedule_to_api_upper_bound_p95_ms",
            ),
        },
    }

    return {
        "artifact_version": ARTIFACT_VERSION,
        "analysis_id": ANALYSIS_ID,
        "run_prefix": run_prefix,
        "matched_seed_count": len(matched_seeds),
        "matched_seeds": matched_seeds,
        "bootstrap": {
            "method": "percentile",
            "statistic": "median",
            "confidence_level": BOOTSTRAP_CONFIDENCE,
            "unit": "run",
            "seed": BOOTSTRAP_SEED,
            "resamples": BOOTSTRAP_RESAMPLES,
        },
        "controls": controls,
        "measurement_boundaries": boundaries,
        "profiles": profile_payload,
        "paired_deltas": paired_deltas,
        "source_runs": [
            {
                "run_id": record.run_id,
                "profile": record.profile,
                "seed": record.seed,
            }
            for record in sorted(records, key=lambda item: (item.seed, item.profile))
        ],
    }


def write_aggregate(output: Path, payload: dict[str, Any]) -> None:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    _atomic_write(output, content.encode("utf-8"))


def aggregate_runs(
    input_dir: Path,
    output: Path,
    *,
    run_prefix: str = "nt532-rq2-v5-",
    min_seeds: int = DEFAULT_MIN_SEEDS,
) -> dict[str, Any]:
    payload = build_aggregate(
        input_dir,
        run_prefix=run_prefix,
        min_seeds=min_seeds,
    )
    write_aggregate(output, payload)
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate matched RQ2 MQTT experiment runs. Fails closed on "
            "incomplete, duplicate, or unmatched evidence."
        )
    )
    parser.add_argument("--input-dir", type=Path, default=Path("evidence/runs"))
    parser.add_argument(
        "--output", type=Path, default=Path("evidence/analysis/rq2-experiments.json")
    )
    parser.add_argument("--run-prefix", default="nt532-rq2-v5-")
    parser.add_argument("--min-seeds", type=int, default=DEFAULT_MIN_SEEDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        payload = aggregate_runs(
            args.input_dir,
            args.output,
            run_prefix=args.run_prefix,
            min_seeds=args.min_seeds,
        )
    except AggregateError as exc:
        print(f"Aggregate failed: {exc.code}", file=sys.stderr)
        return 1
    except OSError:
        print("Aggregate failed: output_io_error", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "analysis_id": ANALYSIS_ID,
                "matched_seed_count": payload["matched_seed_count"],
                "output": str(args.output),
            },
            ensure_ascii=False,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
