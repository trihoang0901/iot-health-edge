from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

import simulator.experiment as experiment
from simulator.experiment import (
    ARTIFACT_VERSION,
    PollObservation,
    SOURCE_FILES,
    SOURCE_FINGERPRINT_SCOPE,
    main,
    percentile,
    source_provenance,
    summarize_samples,
)


def _provenance() -> dict:
    return {
        "scope": SOURCE_FINGERPRINT_SCOPE,
        "head_commit": "a" * 40,
        "source_state": "worktree_uncommitted",
        "source_sha256": "b" * 64,
        "source_files": list(SOURCE_FILES),
    }


class _FakePublisher:
    def __init__(self, _runtime, _stream) -> None:
        self.is_connected = False

    def connect(self) -> None:
        self.is_connected = True

    def publish(self, _message) -> None:
        return None

    def close(self) -> None:
        self.is_connected = False


class _JsonResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _configure_measured(monkeypatch, observation: PollObservation) -> None:
    monkeypatch.setenv("SIMULATOR_MQTT_USERNAME", "simulator")
    monkeypatch.setenv("SIMULATOR_MQTT_PASSWORD", "test-only")
    monkeypatch.setattr(experiment, "source_provenance", _provenance)
    monkeypatch.setattr(experiment, "_require_api_ready", lambda _base: None)
    monkeypatch.setattr(experiment, "MqttPublisher", _FakePublisher)
    monkeypatch.setattr(experiment, "_poll_observed", lambda *_args, **_kwargs: observation)


def test_percentile_interpolates_and_empty_is_none():
    assert percentile([], 0.5) is None
    assert percentile([10.0], 0.95) == 10.0
    assert percentile([0.0, 10.0], 0.5) == 5.0


def test_summary_uses_scheduled_and_attempted_denominators_separately():
    samples = []
    for seq in range(1, 21):
        observed = seq != 20
        samples.append(
            {
                "device_id": "node-1",
                "boot_id": "boot-1",
                "stream": "telemetry",
                "seq": seq,
                "intentionally_dropped": False,
                "publish_attempted": True,
                "attempt_count": 2 if seq == 1 else 1,
                "published": True,
                "ingested": observed,
                "api_observed": observed,
                "publish_to_api_upper_bound_ms": float(seq * 10) if observed else None,
                "schedule_to_api_upper_bound_ms": float(seq * 10 + 5) if observed else None,
                "schedule_slip_ms": 1.0,
                "error_code": "api_observation_timeout" if not observed else None,
            }
        )

    summary = summarize_samples(
        "run-1", samples, status="completed", polling_resolution_ms=100
    )

    assert summary["unique_logical_publish_attempted"] == 20
    assert summary["attempt_count"] == 21
    assert summary["api_observed"] == 19
    assert summary["attempted_delivery_ratio"] == 0.95
    assert summary["delivery_ratio"] == 0.95
    assert summary["scheduled_observation_ratio"] == 0.95
    assert summary["percentiles_available"] is False
    assert summary["schedule_to_api_upper_bound_p95_ms"] is None


def test_source_fingerprint_is_stable_allowlisted_and_changes_with_source(tmp_path):
    for relative in SOURCE_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")

    first = source_provenance(tmp_path)
    second = source_provenance(tmp_path)
    assert first == second
    assert first["scope"] == "runner_source_fingerprint"
    assert first["source_files"] == list(SOURCE_FILES)
    assert first["source_state"] == "unknown"

    (tmp_path / SOURCE_FILES[0]).write_text("changed", encoding="utf-8")
    assert source_provenance(tmp_path)["source_sha256"] != first["source_sha256"]


def test_source_provenance_scopes_git_status_to_runner_files(tmp_path, monkeypatch):
    for relative in SOURCE_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    calls: list[list[str]] = []

    class Result:
        stdout = ""

    def fake_run(command, **_kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr(experiment.subprocess, "run", fake_run)
    monkeypatch.setattr(experiment, "_git_commit", lambda _root: "a" * 40)

    payload = source_provenance(tmp_path)

    assert calls == [
        [
            "git",
            "-C",
            str(tmp_path),
            "status",
            "--porcelain",
            "--",
            *SOURCE_FILES,
        ]
    ]
    assert payload["source_state"] == "commit_clean"


def test_dry_run_writes_v3_planned_redacted_artifact_trio(tmp_path, capsys):
    output = tmp_path / "runs"

    result = main(
        [
            "--profile",
            "remote-app-emulated",
            "--scenario",
            "normal",
            "--count",
            "20",
            "--seed",
            "532",
            "--interval",
            "0.01",
            "--run-id",
            "run-dry-532",
            "--output-dir",
            str(output),
            "--dry-run",
        ]
    )

    assert result == 0
    run_dir = output / "run-dry-532"
    assert {item.name for item in run_dir.iterdir()} == {
        "manifest.json",
        "samples.jsonl",
        "summary.json",
    }
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    samples = [
        json.loads(line)
        for line in (run_dir / "samples.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    content = "\n".join(item.read_text(encoding="utf-8") for item in run_dir.iterdir())
    assert manifest["artifact_version"] == ARTIFACT_VERSION == "5.0"
    assert manifest["status"] == "planned"
    assert manifest["source_provenance"]["scope"] == SOURCE_FINGERPRINT_SCOPE
    assert manifest["profile"]["network_claim"] == "none"
    assert manifest["claims"]["measured_5g"] is False
    assert manifest["claims"]["primary_latency_kind"] == (
        "schedule_to_api_polling_upper_bound"
    )
    assert manifest["claims"]["diagnostic_latency_kind"] == (
        "publish_to_api_polling_upper_bound"
    )
    assert "latency_kind" not in manifest["claims"]
    assert summary["status"] == "planned"
    assert summary["scheduled"] == 20
    assert summary["scheduled_observation_ratio"] is None
    assert samples[-1]["scheduled_offset_ms"] == 190.0
    assert all(sample["schedule_slip_ms"] == 0.0 for sample in samples)
    assert all(sample["slot_to_publish_ms"] is None for sample in samples)
    assert "password" not in content.lower()
    assert "token" not in content.lower()
    assert "network_claim" in capsys.readouterr().out


def test_health_gate_requires_ok(monkeypatch):
    monkeypatch.setattr(
        experiment,
        "urlopen",
        lambda *_args, **_kwargs: _JsonResponse({"status": "degraded"}),
    )
    with pytest.raises(RuntimeError, match="edge_api_not_ready"):
        experiment._require_api_ready("http://edge")


def test_poll_503_is_infrastructure_failure(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise HTTPError("http://edge", 503, "unavailable", {}, None)

    monkeypatch.setattr(experiment, "urlopen", unavailable)
    result = experiment._poll_observed(
        "http://edge",
        device_id="health-node-01",
        boot_id="a" * 32,
        seq=1,
        timeout_seconds=0.1,
        polling_resolution_ms=20,
    )
    assert result == PollObservation(
        observed=False,
        error_code="api_infrastructure_unavailable",
        infrastructure_error=True,
    )


def test_disconnect_after_empty_poll_is_infrastructure_failure(monkeypatch):
    calls = 0

    def empty_then_disconnect(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _JsonResponse({"data": []})
        raise URLError("disconnected")

    monkeypatch.setattr(experiment, "urlopen", empty_then_disconnect)
    result = experiment._poll_observed(
        "http://edge",
        device_id="health-node-01",
        boot_id="a" * 32,
        seq=1,
        timeout_seconds=0.05,
        polling_resolution_ms=20,
    )
    assert calls >= 2
    assert result == PollObservation(
        observed=False,
        error_code="api_infrastructure_unavailable",
        infrastructure_error=True,
    )


def test_infrastructure_loss_finalizes_partial_and_exits_one(tmp_path, monkeypatch):
    _configure_measured(
        monkeypatch,
        PollObservation(False, "api_infrastructure_unavailable", True),
    )
    output = tmp_path / "runs"
    result = main(
        [
            "--count",
            "20",
            "--interval",
            "0.001",
            "--run-id",
            "run-partial",
            "--output-dir",
            str(output),
        ]
    )
    assert result == 1
    manifest = json.loads(
        (output / "run-partial" / "manifest.json").read_text(encoding="utf-8")
    )
    summary = json.loads(
        (output / "run-partial" / "summary.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == summary["status"] == "partial"
    assert summary["scheduled"] == 1
    assert summary["error_codes"] == ["api_infrastructure_unavailable"]


def test_measured_reexecution_uses_fresh_boot_identity(tmp_path, monkeypatch):
    _configure_measured(monkeypatch, PollObservation(True, None))
    boot_ids = []
    for name in ("one", "two"):
        output = tmp_path / name
        result = main(
            [
                "--count",
                "20",
                "--interval",
                "0.001",
                "--run-id",
                "same-human-run-id",
                "--output-dir",
                str(output),
            ]
        )
        assert result == 0
        manifest = json.loads(
            (output / "same-human-run-id" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert manifest["status"] == "completed"
        samples = [
            json.loads(line)
            for line in (
                output / "same-human-run-id" / "samples.jsonl"
            ).read_text(encoding="utf-8").splitlines()
        ]
        assert all(sample["slot_to_publish_ms"] is not None for sample in samples)
        assert all(
            abs(
                sample["schedule_to_api_upper_bound_ms"]
                - sample["publish_to_api_upper_bound_ms"]
                - sample["slot_to_publish_ms"]
            ) <= 0.01
            for sample in samples
        )
        boot_ids.append(manifest["boot_id"])
    assert len(set(boot_ids)) == 2


def test_finalize_order_is_samples_then_summary_then_manifest(tmp_path, monkeypatch):
    events: list[str] = []
    original_json = experiment._write_json
    original_samples = experiment._write_samples

    def record_json(path: Path, payload: dict) -> None:
        events.append(path.name)
        original_json(path, payload)

    def record_samples(path: Path, payload: list[dict]) -> None:
        events.append(path.name)
        original_samples(path, payload)

    monkeypatch.setattr(experiment, "_write_json", record_json)
    monkeypatch.setattr(experiment, "_write_samples", record_samples)
    assert main(
        [
            "--count",
            "20",
            "--run-id",
            "finalize-order",
            "--output-dir",
            str(tmp_path),
            "--dry-run",
        ]
    ) == 0
    assert events == [
        "manifest.json",
        "samples.jsonl",
        "summary.json",
        "manifest.json",
    ]
