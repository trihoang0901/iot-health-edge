from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from simulator.aggregate import AggregateError, aggregate_runs, build_aggregate, main
from simulator.experiment import (
    ARTIFACT_VERSION,
    SOURCE_FILES,
    SOURCE_FINGERPRINT_SCOPE,
    config_digest,
    config_material,
    summarize_samples,
)
from simulator.network_profiles import build_schedule, get_profile


PREFIX = "nt532-rq2-v5-"
COMMIT = "a" * 40
SOURCE_HASH = "b" * 64


def _write_run(
    root: Path,
    *,
    run_id: str,
    profile: str,
    seed: int | bool,
    status: str = "completed",
    manifest_run_id: str | None = None,
    polling_resolution_ms: int = 100,
    count: int = 30,
    interval_seconds: float = 0.05,
    observe_timeout_seconds: float = 5.0,
    source_hash: str = SOURCE_HASH,
) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    canonical = get_profile(profile) if profile in {"lan-baseline", "remote-app-emulated"} else get_profile("lan-baseline")
    numeric_seed = int(seed)
    artifact_run_id = manifest_run_id or run_id
    device_id = "health-node-01"
    boot_id = sha256(run_id.encode("utf-8")).hexdigest()[:32]
    schedule = build_schedule(canonical, count=count, seed=numeric_seed)
    samples = []
    for index, scheduled in enumerate(schedule):
        publish_latency = round(20.0 + (index % 7), 3)
        schedule_slip = round(float(index % 3), 3)
        dropped = scheduled.intentionally_dropped
        samples.append(
            {
                "artifact_version": ARTIFACT_VERSION,
                "run_id": artifact_run_id,
                "device_id": device_id,
                "boot_id": boot_id,
                "stream": "telemetry",
                "seq": index + 1,
                "scheduled_index": index,
                "scheduled": True,
                "scheduled_delay_ms": scheduled.delay_ms,
                "scheduled_offset_ms": round(index * interval_seconds * 1000, 3),
                "schedule_slip_ms": schedule_slip,
                "slot_to_publish_ms": (
                    None
                    if dropped
                    else round(scheduled.delay_ms + schedule_slip + 2.0, 3)
                ),
                "intentionally_dropped": dropped,
                "drop_reason": scheduled.drop_reason,
                "publish_attempted": not dropped,
                "attempt_count": 0 if dropped else 1,
                "published": not dropped,
                "ingested": not dropped,
                "api_observed": not dropped,
                "publish_to_api_upper_bound_ms": None if dropped else publish_latency,
                "schedule_to_api_upper_bound_ms": (
                    None
                    if dropped
                    else round(
                        publish_latency + scheduled.delay_ms + schedule_slip + 2.0,
                        3,
                    )
                ),
                "polling_error_bound_ms": polling_resolution_ms,
                "error_code": None,
            }
        )

    manifest = {
        "artifact_version": ARTIFACT_VERSION,
        "run_id": artifact_run_id,
        "status": status,
        "created_at": "2026-08-14T00:00:00.000Z",
        "completed_at": "2026-08-14T00:01:00.000Z" if status == "completed" else None,
        "profile": canonical.public_dict() if profile in {"lan-baseline", "remote-app-emulated"} else {**canonical.public_dict(), "name": profile},
        "scenario": "normal",
        "seed": seed,
        "count": count,
        "interval_seconds": interval_seconds,
        "protocol": {"name": "MQTT", "version": "3.1.1", "transport": "TCP"},
        "topic_namespace": "iot-health/v1/devices/{device_id}/{stream}",
        "device_id": device_id,
        "boot_id": boot_id,
        "schema": "health.telemetry.v3",
        "commit": COMMIT,
        "source_provenance": {
            "scope": SOURCE_FINGERPRINT_SCOPE,
            "head_commit": COMMIT,
            "source_state": "worktree_uncommitted",
            "source_sha256": source_hash,
            "source_files": list(SOURCE_FILES),
        },
        "config_hash": config_digest(
            config_material(
                profile=canonical,
                scenario="normal",
                count=count,
                seed=numeric_seed,
                interval_seconds=interval_seconds,
                device_id=device_id,
                polling_resolution_ms=polling_resolution_ms,
                observe_timeout_seconds=observe_timeout_seconds,
            )
        ),
        "clock_domain": "host_monotonic_same_process",
        "polling_resolution_ms": polling_resolution_ms,
        "observe_timeout_seconds": observe_timeout_seconds,
        "injection_point": "before_mqtt_publish",
        "claims": {
            "profile_kind": "app_impairment",
            "network_claim": "none",
            "measured_5g": False,
            "primary_latency_kind": "schedule_to_api_polling_upper_bound",
            "diagnostic_latency_kind": "publish_to_api_polling_upper_bound",
        },
    }
    summary = summarize_samples(
        artifact_run_id,
        samples,
        status=status,
        polling_resolution_ms=polling_resolution_ms,
    )
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (run_dir / "samples.jsonl").write_text(
        "".join(json.dumps(sample, separators=(",", ":")) + "\n" for sample in samples),
        encoding="utf-8",
    )
    return run_dir


def _write_pair(root: Path, seed: int, *, source_hash: str = SOURCE_HASH) -> None:
    _write_run(
        root,
        run_id=f"{PREFIX}lan-{seed:03d}",
        profile="lan-baseline",
        seed=seed,
        source_hash=source_hash,
    )
    _write_run(
        root,
        run_id=f"{PREFIX}remote-{seed:03d}",
        profile="remote-app-emulated",
        seed=seed,
        source_hash=source_hash,
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_samples(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_samples(path: Path, samples: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(sample, separators=(",", ":")) + "\n" for sample in samples),
        encoding="utf-8",
    )


def test_aggregate_reconciles_30_matched_seeds_and_reports_paired_treatment_metrics(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    for seed in range(30):
        _write_pair(runs, seed)

    output = tmp_path / "analysis" / "rq2.json"
    payload = aggregate_runs(runs, output, run_prefix=PREFIX)

    assert payload["matched_seed_count"] == 30
    assert payload["profiles"]["lan-baseline"]["metrics"]["scheduled_observation_ratio"]["median"] == 1.0
    assert payload["profiles"]["remote-app-emulated"]["metrics"]["scheduled_observation_ratio"]["median"] < 1.0
    assert payload["profiles"]["remote-app-emulated"]["metrics"]["schedule_to_api_upper_bound_p50_ms"]["median"] > payload["profiles"]["lan-baseline"]["metrics"]["schedule_to_api_upper_bound_p50_ms"]["median"]
    assert payload["paired_deltas"]["unit"] == "matched_seed_pair"
    assert payload["paired_deltas"]["metrics"]["schedule_to_api_upper_bound_p50_ms"]["median_delta"] > 0
    assert payload["controls"]["source_provenance"]["source_sha256"] == SOURCE_HASH
    assert payload["measurement_boundaries"]["primary_latency_kind"] == "schedule_to_api_polling_upper_bound"
    assert payload["measurement_boundaries"]["diagnostic_latency_kind"] == "publish_to_api_polling_upper_bound"
    assert "latency_kind" not in payload["measurement_boundaries"]
    assert json.loads(output.read_text(encoding="utf-8")) == payload


def test_rejects_ambiguous_or_inverted_latency_claims(tmp_path):
    for case in ("legacy", "inverted"):
        runs = tmp_path / case
        runs.mkdir()
        run = _write_run(
            runs,
            run_id=f"{PREFIX}lan-001",
            profile="lan-baseline",
            seed=1,
        )
        manifest = _read_json(run / "manifest.json")
        if case == "legacy":
            manifest["claims"]["latency_kind"] = manifest["claims"].pop(
                "diagnostic_latency_kind"
            )
            error = "invalid_claim_shape"
        else:
            manifest["claims"]["primary_latency_kind"] = (
                "publish_to_api_polling_upper_bound"
            )
            error = "measurement_boundary_mismatch"
        _write_json(run / "manifest.json", manifest)
        with pytest.raises(AggregateError, match=error):
            build_aggregate(runs, run_prefix=PREFIX, min_seeds=1)


def test_rejects_mismatched_seed_sets(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_pair(runs, 1)
    _write_run(runs, run_id=f"{PREFIX}lan-002", profile="lan-baseline", seed=2)
    with pytest.raises(AggregateError, match="mismatched_seed_sets"):
        build_aggregate(runs, run_prefix=PREFIX, min_seeds=1)


def test_rejects_duplicate_completed_profile_seed(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_pair(runs, 1)
    _write_run(runs, run_id=f"{PREFIX}lan-duplicate", profile="lan-baseline", seed=1)
    with pytest.raises(AggregateError, match="duplicate_profile_seed"):
        build_aggregate(runs, run_prefix=PREFIX, min_seeds=1)


def test_default_rejects_fewer_than_30_independent_seeds(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    for seed in range(29):
        _write_pair(runs, seed)
    with pytest.raises(AggregateError, match="insufficient_independent_seeds"):
        build_aggregate(runs, run_prefix=PREFIX)


def test_rejects_incomplete_or_mixed_status_run(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_pair(runs, 1)
    path = runs / f"{PREFIX}remote-001" / "manifest.json"
    manifest = _read_json(path)
    manifest["status"] = "running"
    manifest["completed_at"] = None
    _write_json(path, manifest)
    with pytest.raises(AggregateError, match="run_not_completed"):
        build_aggregate(runs, run_prefix=PREFIX, min_seeds=1)


def test_rejects_missing_samples_artifact(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_pair(runs, 1)
    (runs / f"{PREFIX}lan-001" / "samples.jsonl").unlink()
    with pytest.raises(AggregateError, match="missing_artifact"):
        build_aggregate(runs, run_prefix=PREFIX, min_seeds=1)


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [("run_id", "invalid_run_id"), ("profile", "unsupported_profile"), ("seed", "invalid_integer")],
)
def test_validates_run_id_profile_and_seed(tmp_path, mutation, error_code):
    runs = tmp_path / mutation
    runs.mkdir()
    kwargs = {"run_id": f"{PREFIX}candidate", "profile": "lan-baseline", "seed": 1}
    if mutation == "run_id":
        kwargs["manifest_run_id"] = f"{PREFIX}different"
    elif mutation == "profile":
        kwargs["profile"] = "future-profile"
    else:
        kwargs["seed"] = True
    _write_run(runs, **kwargs)
    with pytest.raises(AggregateError, match=error_code):
        build_aggregate(runs, run_prefix=PREFIX, min_seeds=1)


def test_rejects_mixed_polling_or_source_boundaries(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_run(runs, run_id=f"{PREFIX}lan-001", profile="lan-baseline", seed=1, polling_resolution_ms=100)
    _write_run(runs, run_id=f"{PREFIX}remote-001", profile="remote-app-emulated", seed=1, polling_resolution_ms=50)
    with pytest.raises(AggregateError, match="experimental_control_mismatch"):
        build_aggregate(runs, run_prefix=PREFIX, min_seeds=1)

    other = tmp_path / "source"
    other.mkdir()
    _write_run(other, run_id=f"{PREFIX}lan-001", profile="lan-baseline", seed=1)
    _write_run(other, run_id=f"{PREFIX}remote-001", profile="remote-app-emulated", seed=1, source_hash="c" * 64)
    with pytest.raises(AggregateError, match="experimental_control_mismatch"):
        build_aggregate(other, run_prefix=PREFIX, min_seeds=1)


def test_rejects_tampered_summary(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    run = _write_run(runs, run_id=f"{PREFIX}lan-001", profile="lan-baseline", seed=1)
    summary = _read_json(run / "summary.json")
    summary["scheduled_observation_ratio"] = 0.25
    _write_json(run / "summary.json", summary)
    with pytest.raises(AggregateError, match="summary_reconciliation_failed"):
        build_aggregate(runs, run_prefix=PREFIX, min_seeds=1)


def test_rejects_tampered_raw_sample_even_when_summary_is_recomputed(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    run = _write_run(runs, run_id=f"{PREFIX}lan-001", profile="lan-baseline", seed=1)
    samples = _read_samples(run / "samples.jsonl")
    samples[0]["seq"] = 99
    _write_samples(run / "samples.jsonl", samples)
    summary = summarize_samples(
        f"{PREFIX}lan-001", samples, status="completed", polling_resolution_ms=100
    )
    _write_json(run / "summary.json", summary)
    with pytest.raises(AggregateError, match="sample_schedule_or_identity_mismatch"):
        build_aggregate(runs, run_prefix=PREFIX, min_seeds=1)


def test_rejects_tampered_slot_to_publish_timeline(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    run = _write_run(runs, run_id=f"{PREFIX}lan-001", profile="lan-baseline", seed=1)
    samples = _read_samples(run / "samples.jsonl")
    samples[0]["slot_to_publish_ms"] += 25.0
    _write_samples(run / "samples.jsonl", samples)
    # The summary does not contain this raw timing field; reconciliation must
    # still reject the impossible timeline before accepting KPI percentiles.
    with pytest.raises(AggregateError, match="schedule_latency_timeline_mismatch"):
        build_aggregate(runs, run_prefix=PREFIX, min_seeds=1)


def test_rejects_profile_tamper_even_after_recomputing_config_hash(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    run = _write_run(runs, run_id=f"{PREFIX}lan-001", profile="lan-baseline", seed=1)
    manifest = _read_json(run / "manifest.json")
    manifest["profile"]["base_delay_ms"] = 999
    material = {
        "profile": manifest["profile"],
        "scenario": manifest["scenario"],
        "count": manifest["count"],
        "seed": manifest["seed"],
        "interval_seconds": manifest["interval_seconds"],
        "device_id": manifest["device_id"],
        "schema": manifest["schema"],
        "polling_resolution_ms": manifest["polling_resolution_ms"],
        "observe_timeout_seconds": manifest["observe_timeout_seconds"],
    }
    manifest["config_hash"] = config_digest(material)
    _write_json(run / "manifest.json", manifest)
    with pytest.raises(AggregateError, match="profile_definition_mismatch"):
        build_aggregate(runs, run_prefix=PREFIX, min_seeds=1)


def test_rejects_config_provenance_and_artifact_version_tampering(tmp_path):
    for field, value, error in (
        ("config_hash", "0" * 64, "config_hash_mismatch"),
        ("artifact_version", "1.0", "unsupported_manifest_version"),
    ):
        runs = tmp_path / field
        runs.mkdir()
        run = _write_run(runs, run_id=f"{PREFIX}lan-001", profile="lan-baseline", seed=1)
        manifest = _read_json(run / "manifest.json")
        manifest[field] = value
        _write_json(run / "manifest.json", manifest)
        with pytest.raises(AggregateError, match=error):
            build_aggregate(runs, run_prefix=PREFIX, min_seeds=1)


def test_rejects_unknown_sample_fields_duplicate_keys_and_nonfinite_values(tmp_path):
    for case in ("extra", "duplicate", "nan"):
        runs = tmp_path / case
        runs.mkdir()
        run = _write_run(runs, run_id=f"{PREFIX}lan-001", profile="lan-baseline", seed=1)
        path = run / "samples.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        if case == "extra":
            sample = json.loads(lines[0])
            sample["password"] = "must-not-propagate"
            lines[0] = json.dumps(sample)
            error = "invalid_sample_shape"
        elif case == "duplicate":
            lines[0] = lines[0][:-1] + ',"seq":999}'
            error = "invalid_samples_jsonl"
        else:
            lines[0] = lines[0].replace('"schedule_slip_ms":0.0', '"schedule_slip_ms":NaN')
            error = "invalid_samples_jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(AggregateError, match=error):
            build_aggregate(runs, run_prefix=PREFIX, min_seeds=1)


def test_cli_writes_allowlisted_json(tmp_path, capsys):
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_pair(runs, 1)
    output = tmp_path / "rq2.json"
    result = main(["--input-dir", str(runs), "--output", str(output), "--run-prefix", PREFIX, "--min-seeds", "1"])
    assert result == 0
    assert output.is_file()
    assert json.loads(capsys.readouterr().out)["matched_seed_count"] == 1
