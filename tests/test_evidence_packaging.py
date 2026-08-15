from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import zipfile

import pytest

from scripts import package_final_evidence as research_package
from scripts import package_software_acceptance as acceptance_package


def _provenance(
    digest: str = "a" * 64,
    *,
    head: str = "1" * 40,
    state: str = "commit_clean",
) -> dict[str, object]:
    return {
        "scope": "runner_source_fingerprint",
        "head_commit": head,
        "source_state": state,
        "source_sha256": digest,
        "source_files": ["edge/app.py"],
    }


def _verification_fingerprint(
    digest: str = "b" * 64,
    *,
    head: str = "1" * 40,
    state: str = "commit_clean",
) -> dict[str, object]:
    return {
        "scope": "verification_inputs_v1",
        "head_commit": head,
        "source_state": state,
        "source_sha256": digest,
        "source_files": [".gitattributes", "README.md"],
    }


def test_research_verification_compares_content_not_git_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "evidence/analysis/verification-latest.json"
    path.parent.mkdir(parents=True)
    recorded_runner = _provenance(head="1" * 40, state="worktree_uncommitted")
    recorded_verification = _verification_fingerprint(
        head="1" * 40, state="worktree_uncommitted"
    )
    path.write_text(
        json.dumps(
            {
                "artifact_version": "1.3",
                "overall_status": "passed",
                "command": ".\\scripts\\VERIFY-MVP.ps1 -IncludeDockerLive -IncludeFirmware",
                "launcher_or_upload_used": False,
                "checks": [{"status": "passed"} for _ in range(6)],
                "runner_source_provenance": recorded_runner,
                "verification_input_provenance": recorded_verification,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(research_package, "ROOT", tmp_path)
    monkeypatch.setattr(
        research_package,
        "source_provenance",
        lambda: _provenance(head="2" * 40, state="commit_clean"),
    )
    monkeypatch.setattr(
        research_package,
        "build_fingerprint",
        lambda: _verification_fingerprint(head="2" * 40, state="commit_clean"),
    )

    research_package.validate_verification()

    monkeypatch.setattr(
        research_package,
        "source_provenance",
        lambda: _provenance(digest="c" * 64, head="2" * 40),
    )
    with pytest.raises(ValueError, match="runner content fingerprint is stale"):
        research_package.validate_verification()

    monkeypatch.setattr(
        research_package,
        "source_provenance",
        lambda: _provenance(head="2" * 40, state="commit_clean"),
    )
    for field, bad_value in (
        ("source_sha256", "d" * 64),
        ("source_files", ["different-input.py"]),
    ):
        tampered = dict(recorded_verification)
        tampered[field] = bad_value
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["verification_input_provenance"] = tampered
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(
            ValueError, match="verification input content fingerprint is stale"
        ):
            research_package.validate_verification()


def test_research_rq2_aggregate_must_match_current_source(monkeypatch) -> None:
    aggregate = {
        "controls": {
            "source_provenance": {
                "head_commit": "1" * 40,
                "source_state": "worktree_uncommitted",
                "source_sha256": "a" * 64,
                "source_files": ["edge/app.py"],
            }
        }
    }
    monkeypatch.setattr(
        research_package,
        "source_provenance",
        lambda: _provenance(head="2" * 40, state="commit_clean"),
    )
    research_package.validate_rq2_current_source(aggregate)

    aggregate["controls"]["source_provenance"]["source_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="RQ2 aggregate source fingerprint is stale"):
        research_package.validate_rq2_current_source(aggregate)

    aggregate["controls"]["source_provenance"]["source_sha256"] = "a" * 64
    aggregate["controls"]["source_provenance"]["source_files"] = ["other.py"]
    with pytest.raises(ValueError, match="RQ2 aggregate source fingerprint is stale"):
        research_package.validate_rq2_current_source(aggregate)


def test_acceptance_allowlist_is_exactly_fourteen_and_separate_from_research() -> None:
    files = acceptance_package.ACCEPTANCE_FILES
    root = acceptance_package.ACCEPTANCE_ROOT
    assert files == (
        f"{root}/report.md",
        f"{root}/scenario-acceptance.json",
        f"{root}/scenario-observations.json",
        f"{root}/ui/browser-smoke.json",
        f"{root}/ui/dashboard-mobile-320.png",
        f"{root}/ui/dashboard-mobile-360.png",
        f"{root}/ui/dashboard-tablet-768.png",
        f"{root}/ui/dashboard-desktop-1440.png",
        f"{root}/dry-runs/acceptance-dry-lan-20260814/manifest.json",
        f"{root}/dry-runs/acceptance-dry-lan-20260814/samples.jsonl",
        f"{root}/dry-runs/acceptance-dry-lan-20260814/summary.json",
        f"{root}/dry-runs/acceptance-dry-remote-20260814/manifest.json",
        f"{root}/dry-runs/acceptance-dry-remote-20260814/samples.jsonl",
        f"{root}/dry-runs/acceptance-dry-remote-20260814/summary.json",
    )
    assert len(files) == len(set(files)) == 14
    assert "docs/demo-nt532.md" not in files
    assert not any("deliverables/" in relative for relative in files)
    assert sum(relative.endswith(".png") for relative in files) == 4
    assert sum(relative.endswith("samples.jsonl") for relative in files) == 2


def test_acceptance_artifact_set_rejects_extra_file(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(acceptance_package, "ROOT", tmp_path)
    for relative in acceptance_package.ACCEPTANCE_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"placeholder")

    acceptance_package.validate_exact_artifact_set()

    extra = tmp_path / acceptance_package.ACCEPTANCE_ROOT / "unexpected.txt"
    extra.write_text("unexpected", encoding="utf-8")
    with pytest.raises(ValueError, match="extra=.*unexpected.txt"):
        acceptance_package.validate_exact_artifact_set()

    extra.unlink()
    missing = tmp_path / acceptance_package.ACCEPTANCE_FILES[0]
    missing.unlink()
    with pytest.raises(ValueError, match="missing=.*report.md"):
        acceptance_package.validate_exact_artifact_set()


def test_acceptance_redaction_scans_markdown_json_and_jsonl() -> None:
    entries = {
        "report.md": b"safe markdown",
        "scenario.json": b'{"status":"passed"}',
        "samples.jsonl": b'{"seq":1}\n',
        "image.png": b"not scanned",
    }
    result = acceptance_package.validate_redaction(entries)
    assert result == {
        "status": "passed",
        "text_files_scanned": 3,
        "sensitive_value_hits": 0,
        "absolute_path_hits": 0,
    }

    with pytest.raises(ValueError, match="sensitive value shape"):
        acceptance_package.validate_redaction(
            {"report.md": b"password=do-not-package"}
        )
    with pytest.raises(ValueError, match="sensitive value shape"):
        acceptance_package.validate_redaction(
            {"scenario.json": b'{"api_key":"do-not-package"}'}
        )
    with pytest.raises(ValueError, match="absolute workstation path"):
        acceptance_package.validate_redaction(
            {"scenario.json": b'{"path":"C:\\\\private\\\\edge.db"}'}
        )
    with pytest.raises(ValueError, match="absolute workstation path"):
        acceptance_package.validate_redaction(
            {"scenario.json": b'{"path":"D:/private/edge.db"}'}
        )
    with pytest.raises(ValueError, match="absolute workstation path"):
        acceptance_package.validate_redaction(
            {"scenario.json": b'{"path":"\\\\\\\\server\\\\share"}'}
        )
    with pytest.raises(ValueError, match="sensitive JSON key"):
        research_package.validate_redaction(
            {"manifest.json": b'{"api_key":"do-not-package"}'}
        )
    with pytest.raises(ValueError, match="absolute workstation path"):
        research_package.validate_redaction(
            {"manifest.json": b'{"path":"D:/private/edge.db"}'}
        )


def test_strict_json_and_jsonl_reject_duplicate_keys(tmp_path: Path, monkeypatch) -> None:
    duplicate = b'{"status":"failed","status":"passed"}'
    with pytest.raises(ValueError, match="duplicate JSON key"):
        acceptance_package.strict_json_bytes("scenario.json", duplicate)
    with pytest.raises(ValueError, match="duplicate JSON key"):
        acceptance_package.strict_jsonl("samples.jsonl", duplicate + b"\n")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        research_package.strict_json_bytes("manifest.json", duplicate)

    path = tmp_path / "manifest.json"
    path.write_bytes(duplicate)
    monkeypatch.setattr(research_package, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="duplicate JSON key"):
        research_package.strict_json(path)


def test_acceptance_verification_reference_uses_stable_identity(
    tmp_path: Path, monkeypatch
) -> None:
    relative = "evidence/analysis/verification-latest.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    payload = {
        "artifact_version": "1.3",
        "overall_status": "passed",
        "command": ".\\scripts\\VERIFY-MVP.ps1 -IncludeDockerLive -IncludeFirmware",
        "launcher_or_upload_used": False,
        "checks": [{"status": "passed"} for _ in range(6)],
        "runner_source_provenance": _provenance(
            head="1" * 40, state="worktree_uncommitted"
        ),
        "verification_input_provenance": _verification_fingerprint(
            head="1" * 40, state="worktree_uncommitted"
        ),
    }
    data = (json.dumps(payload) + "\n").encode("utf-8")
    path.write_bytes(data)
    monkeypatch.setattr(acceptance_package, "ROOT", tmp_path)
    monkeypatch.setattr(
        acceptance_package,
        "source_provenance",
        lambda: _provenance(head="2" * 40, state="commit_clean"),
    )
    monkeypatch.setattr(
        acceptance_package,
        "build_fingerprint",
        lambda: _verification_fingerprint(head="2" * 40, state="commit_clean"),
    )
    reference = {
        "path": relative,
        "sha256": sha256(data).hexdigest(),
        "artifact_version": "1.3",
        "overall_status": "passed",
    }

    acceptance_package.validate_verification_reference({"verification": reference})

    reference["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="verification reference is stale"):
        acceptance_package.validate_verification_reference({"verification": reference})


def test_acceptance_report_rejects_bundle_self_reference() -> None:
    required_report = "\n".join(
        (
            "status: MVP_SOFTWARE_ACCEPTED_WITH_DECLARED_LIMITATIONS",
            "scope: software-only, no hardware upload",
            "# Kết luận",
            "**MVP phần mềm để demo/chấm môn:** GO.",
            "**Tuyên bố sản phẩm y tế, node vật lý đã xác minh hoặc 5G đã đo:** NO-GO.",
        )
    )
    key = f"{acceptance_package.ACCEPTANCE_ROOT}/report.md"
    acceptance_package.validate_report(
        {key: required_report.encode("utf-8")},
        acceptance_package.DEFAULT_OUTPUT.name,
    )
    with pytest.raises(ValueError, match="must not embed"):
        acceptance_package.validate_report(
            {
                key: (
                    required_report
                    + "\n"
                    + acceptance_package.DEFAULT_OUTPUT.name
                ).encode("utf-8")
            },
            acceptance_package.DEFAULT_OUTPUT.name,
        )
    with pytest.raises(ValueError, match="must not embed"):
        acceptance_package.validate_report(
            {
                key: (
                    required_report + "\nSHA-256 của gói: " + "a" * 64
                ).encode("utf-8")
            },
            acceptance_package.DEFAULT_OUTPUT.name,
        )


def test_acceptance_cardinality_rejects_duplicate_run_and_viewport(monkeypatch) -> None:
    observations_path = f"{acceptance_package.ACCEPTANCE_ROOT}/scenario-observations.json"
    observations = {
        "artifact_version": "1.0",
        "capture_kind": "sanitized_api_observation_snapshot",
        "health": {
            "status": "ok",
            "non_clinical": True,
            "mqtt": {"connected": True, "subscribed": True, "has_error": False},
            "ingestion": {
                "processing_errors": 0,
                "worker_alive": True,
                "has_error": False,
            },
        },
        "telemetry_runs": [
            {"scenario": name, "row_count": 20, "seq_first": 1, "seq_last": 20}
            for name in ("normal", "motion_artifact", "low_spo2", "normal")
        ],
        "alert": {
            "rule_id": "demo_low_spo2",
            "state": "acknowledged",
            "occurrence_count": 10,
        },
    }
    with pytest.raises(ValueError, match="run set mismatch"):
        acceptance_package.validate_observations(
            {observations_path: json.dumps(observations).encode("utf-8")}
        )

    browser_path = f"{acceptance_package.ACCEPTANCE_ROOT}/ui/browser-smoke.json"
    browser = {
        "artifact_version": "1.1",
        "status": "passed",
        "served_asset_version": "1" * 12,
        "source_provenance": {
            "scope": "dashboard_static_and_smoke_script",
            "source_files": list(acceptance_package.UI_SOURCE_FILES),
            "source_sha256": "2" * 64,
        },
        "checks": [
            {"name": name}
            for name in (*acceptance_package.VIEWPORTS, acceptance_package.VIEWPORTS[0])
        ],
    }

    def fake_digest(files, *, separator=True):
        return "1" * 64 if files == acceptance_package.SERVED_ASSET_FILES else "2" * 64

    monkeypatch.setattr(acceptance_package, "scoped_digest", fake_digest)
    with pytest.raises(ValueError, match="viewport set mismatch"):
        acceptance_package.validate_browser(
            {browser_path: json.dumps(browser).encode("utf-8")}
        )


def test_safe_path_rejects_reparse_ancestor(tmp_path: Path, monkeypatch) -> None:
    parent = tmp_path / "runs"
    parent.mkdir()
    child = parent / "manifest.json"
    child.write_text("{}", encoding="utf-8")
    from scripts import verification_source_fingerprint as fingerprint

    original = fingerprint.is_link_or_reparse
    monkeypatch.setattr(
        fingerprint,
        "is_link_or_reparse",
        lambda path: path == parent or original(path),
    )
    with pytest.raises(ValueError, match="symlink or reparse input forbidden"):
        fingerprint.ensure_safe_path(child, tmp_path)


def test_acceptance_writer_adds_inventory_and_sidecar_deterministically(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        acceptance_package,
        "source_provenance",
        lambda: _provenance(head="2" * 40),
    )
    entries = {f"acceptance/file-{index:02d}.json": b"{}" for index in range(14)}
    redaction = {
        "status": "passed",
        "text_files_scanned": 14,
        "sensitive_value_hits": 0,
        "absolute_path_hits": 0,
    }
    output = tmp_path / "nt532-software-e2e-acceptance.zip"
    legacy_temporary = output.with_suffix(".tmp")
    legacy_temporary.write_bytes(b"must-not-be-followed-or-overwritten")

    first = acceptance_package.write_bundle(output, entries, redaction)
    first_bytes = output.read_bytes()
    second = acceptance_package.write_bundle(output, entries, redaction)

    assert output.read_bytes() == first_bytes
    assert legacy_temporary.read_bytes() == b"must-not-be-followed-or-overwritten"
    assert second["sha256"] == first["sha256"] == sha256(first_bytes).hexdigest()
    assert output.with_suffix(".zip.sha256").read_text(encoding="ascii") == (
        f"{first['sha256']}  {output.name}\n"
    )
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {*entries, "inventory.json"}
        inventory = json.loads(archive.read("inventory.json"))
    assert inventory["allowlisted_file_count"] == 14
    assert len(inventory["files"]) == 14


def test_acceptance_writer_rejects_sidecar_reparse_before_archive(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        acceptance_package,
        "source_provenance",
        lambda: _provenance(head="2" * 40),
    )
    monkeypatch.setattr(
        acceptance_package,
        "is_link_or_reparse",
        lambda path: path.name.endswith(".sha256"),
    )
    output = tmp_path / "nt532-software-e2e-acceptance.zip"
    with pytest.raises(ValueError, match="bundle output forbidden"):
        acceptance_package.write_bundle(
            output,
            {"acceptance/report.md": b"safe"},
            {"status": "passed", "text_files_scanned": 1},
        )
    assert not output.exists()
