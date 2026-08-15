from __future__ import annotations

import json
import threading
import time

import pytest

import edge.experiments as experiments_module
import simulator.experiment as experiment
from edge.experiments import ExperimentNotFoundError, ExperimentRegistry
from simulator.experiment import PollObservation, SOURCE_FILES, SOURCE_FINGERPRINT_SCOPE


class _FakePublisher:
    def __init__(self, _runtime, _stream) -> None:
        self.is_connected = False

    def connect(self) -> None:
        self.is_connected = True

    def publish(self, _message) -> None:
        return None

    def close(self) -> None:
        self.is_connected = False


def write_run(root, monkeypatch, run_id="run-001"):
    monkeypatch.setenv("SIMULATOR_MQTT_USERNAME", "simulator")
    monkeypatch.setenv("SIMULATOR_MQTT_PASSWORD", "test-only")
    monkeypatch.setattr(
        experiment,
        "source_provenance",
        lambda: {
            "scope": SOURCE_FINGERPRINT_SCOPE,
            "head_commit": "a" * 40,
            "source_state": "worktree_uncommitted",
            "source_sha256": "b" * 64,
            "source_files": list(SOURCE_FILES),
        },
    )
    monkeypatch.setattr(experiment, "_require_api_ready", lambda _base: None)
    monkeypatch.setattr(experiment, "MqttPublisher", _FakePublisher)
    monkeypatch.setattr(
        experiment,
        "_poll_observed",
        lambda *_args, **_kwargs: PollObservation(True, None),
    )
    assert experiment.main(
        [
            "--count",
            "20",
            "--interval",
            "0.001",
            "--run-id",
            run_id,
            "--output-dir",
            str(root),
        ]
    ) == 0
    return root / run_id


def _mutate_json(path, mutator) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutator(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_registry_returns_allowlisted_redacted_reconciled_v5_metadata(
    tmp_path, monkeypatch
):
    write_run(tmp_path, monkeypatch)
    registry = ExperimentRegistry(tmp_path)

    run = registry.get_run("run-001")

    assert run["manifest"]["artifact_version"] == "5.0"
    assert run["manifest"]["profile"]["network_claim"] == "none"
    assert run["manifest"]["source_provenance"] == {
        "scope": "runner_source_fingerprint",
        "source_state": "worktree_uncommitted",
        "source_sha256": "b" * 64,
    }
    assert run["summary"]["scheduled_observation_ratio"] == 1.0
    assert run["manifest"]["claims"] == {
        "profile_kind": "app_impairment",
        "network_claim": "none",
        "measured_5g": False,
        "primary_latency_kind": "schedule_to_api_polling_upper_bound",
        "diagnostic_latency_kind": "publish_to_api_polling_upper_bound",
    }
    assert "head_commit" not in run["manifest"]["source_provenance"]
    assert "source_files" not in run["manifest"]["source_provenance"]


@pytest.mark.parametrize("run_id", ["../escape", "..", "bad/run", ""])
def test_registry_rejects_path_traversal(tmp_path, run_id):
    registry = ExperimentRegistry(tmp_path)

    with pytest.raises(ExperimentNotFoundError):
        registry.get_run(run_id)


@pytest.mark.parametrize(
    ("manifest_status", "summary_status", "version"),
    [
        ("running", "running", "5.0"),
        ("completed", "partial", "5.0"),
        ("completed", "completed", "4.0"),
        ("future", "future", "5.0"),
    ],
)
def test_registry_hides_transitional_mismatched_legacy_or_unknown_status(
    tmp_path, monkeypatch, manifest_status, summary_status, version
):
    run = write_run(tmp_path, monkeypatch)
    _mutate_json(
        run / "manifest.json",
        lambda payload: payload.update(
            {"status": manifest_status, "artifact_version": version}
        ),
    )
    _mutate_json(
        run / "summary.json",
        lambda payload: payload.update(
            {"status": summary_status, "artifact_version": version}
        ),
    )
    with pytest.raises(ExperimentNotFoundError):
        ExperimentRegistry(tmp_path).get_run("run-001")
    assert ExperimentRegistry(tmp_path).list_runs() == []


def test_registry_hides_well_typed_tampered_summary(tmp_path, monkeypatch):
    run = write_run(tmp_path, monkeypatch)
    _mutate_json(
        run / "summary.json",
        lambda payload: payload.update({"scheduled_observation_ratio": 0.5}),
    )

    registry = ExperimentRegistry(tmp_path)
    with pytest.raises(ExperimentNotFoundError):
        registry.get_run("run-001")
    assert registry.list_runs() == []


def test_registry_hides_well_typed_tampered_raw_sample(tmp_path, monkeypatch):
    run = write_run(tmp_path, monkeypatch)
    path = run / "samples.jsonl"
    samples = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    samples[0]["schedule_slip_ms"] += 10_000.0
    path.write_text(
        "".join(json.dumps(sample, separators=(",", ":")) + "\n" for sample in samples),
        encoding="utf-8",
    )

    registry = ExperimentRegistry(tmp_path)
    with pytest.raises(ExperimentNotFoundError):
        registry.get_run("run-001")
    assert registry.list_runs() == []


def test_registry_skips_malformed_runs(tmp_path, monkeypatch):
    write_run(tmp_path, monkeypatch, "valid-run")
    broken = tmp_path / "broken-run"
    broken.mkdir()
    (broken / "manifest.json").write_text("not-json", encoding="utf-8")

    runs = ExperimentRegistry(tmp_path).list_runs()

    assert [item["manifest"]["run_id"] for item in runs] == ["valid-run"]


def test_registry_caches_only_success_and_invalidates_changed_or_missing_artifact(
    tmp_path, monkeypatch
):
    run = write_run(tmp_path, monkeypatch)
    original_validate = experiments_module.validate_completed_run
    calls = 0

    def counted_validate(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(experiments_module, "validate_completed_run", counted_validate)
    registry = ExperimentRegistry(tmp_path)
    assert registry.get_run("run-001")["manifest"]["artifact_version"] == "5.0"
    assert registry.get_run("run-001")["manifest"]["artifact_version"] == "5.0"
    assert registry.list_runs()[0]["manifest"]["run_id"] == "run-001"
    assert calls == 1

    _mutate_json(
        run / "summary.json",
        lambda payload: payload.update({"scheduled_observation_ratio": 0.5}),
    )
    with pytest.raises(ExperimentNotFoundError):
        registry.get_run("run-001")
    assert calls == 2
    assert registry.list_runs() == []

    (run / "samples.jsonl").unlink()
    with pytest.raises(ExperimentNotFoundError):
        registry.get_run("run-001")


def test_registry_cold_list_validates_runs_concurrently(tmp_path, monkeypatch):
    for index in range(8):
        write_run(tmp_path, monkeypatch, f"run-{index:03d}")

    original_validate = experiments_module.validate_completed_run
    state_lock = threading.Lock()
    active = 0
    peak_active = 0

    def slow_validate(*args, **kwargs):
        nonlocal active, peak_active
        with state_lock:
            active += 1
            peak_active = max(peak_active, active)
        try:
            time.sleep(0.02)
            return original_validate(*args, **kwargs)
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(experiments_module, "validate_completed_run", slow_validate)
    runs = ExperimentRegistry(tmp_path).list_runs(limit=8)
    assert len(runs) == 8
    assert peak_active > 1
