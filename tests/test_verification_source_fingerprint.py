from __future__ import annotations

from pathlib import Path

import pytest

from scripts import verification_source_fingerprint as fingerprint


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _create_verification_tree(root: Path) -> None:
    for relative in fingerprint.ROOT_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    for relative in fingerprint.ROOT_DIRS:
        (root / relative).mkdir(parents=True, exist_ok=True)


def test_verification_files_include_contract_inputs_and_skip_desktop_ini(
    tmp_path: Path, monkeypatch
) -> None:
    _create_verification_tree(tmp_path)
    (tmp_path / "edge/app.py").write_text("app", encoding="utf-8")
    (tmp_path / "edge/desktop.ini").write_text("noise", encoding="utf-8")
    (tmp_path / "tests/Desktop.INI").write_text("noise", encoding="utf-8")
    (tmp_path / "firmware/health-node/secrets.h").write_text(
        "secret", encoding="utf-8"
    )
    monkeypatch.setattr(fingerprint, "ROOT", tmp_path)

    files = fingerprint.verification_files()

    assert ".gitattributes" in files
    assert "INSTALL-IOT-HEALTH-EDGE.bat" in files
    assert "IOT-HEALTH-EDGE.ps1" in files
    assert "START-IOT-HEALTH-EDGE.bat" in files
    assert "START-SOFTWARE.bat" in files
    assert "START-HARDWARE.bat" in files
    assert "STOP-IOT-HEALTH-EDGE.bat" in files
    assert "STATUS-IOT-HEALTH-EDGE.bat" in files
    assert "LOGS-IOT-HEALTH-EDGE.bat" in files
    assert "edge/app.py" in files
    assert not any(Path(relative).name.casefold() == "desktop.ini" for relative in files)
    assert "firmware/health-node/secrets.h" not in files


def test_build_fingerprint_uses_scoped_status_and_stable_identity(
    tmp_path: Path, monkeypatch
) -> None:
    _create_verification_tree(tmp_path)
    calls: list[list[str]] = []

    def fake_git_value(args: list[str]) -> str:
        calls.append(args)
        return " M README.md" if args[0] == "status" else "a" * 40

    monkeypatch.setattr(fingerprint, "ROOT", tmp_path)
    monkeypatch.setattr(fingerprint, "git_value", fake_git_value)

    payload = fingerprint.build_fingerprint()

    status_call = next(call for call in calls if call[0] == "status")
    assert status_call[:3] == ["status", "--porcelain", "--"]
    assert status_call[3:] == payload["source_files"]
    assert payload["source_state"] == "worktree_uncommitted"
    assert fingerprint.stable_content_identity(payload) == {
        "scope": "verification_inputs_v1",
        "source_sha256": payload["source_sha256"],
        "source_files": payload["source_files"],
    }
    changed_git_metadata = {**payload, "head_commit": "b" * 40, "source_state": "commit_clean"}
    assert fingerprint.stable_content_identity(changed_git_metadata) == (
        fingerprint.stable_content_identity(payload)
    )


def test_fixed_root_file_reparse_is_rejected(tmp_path: Path, monkeypatch) -> None:
    _create_verification_tree(tmp_path)
    launcher = tmp_path / "START-IOT-HEALTH-EDGE.bat"
    original = fingerprint.is_link_or_reparse

    monkeypatch.setattr(fingerprint, "ROOT", tmp_path)
    monkeypatch.setattr(
        fingerprint,
        "is_link_or_reparse",
        lambda path: path == launcher or original(path),
    )

    with pytest.raises(ValueError, match="symlink or reparse input forbidden"):
        fingerprint.verification_files()


def test_verify_report_normalizes_json_to_lf_before_writing() -> None:
    script = (PROJECT_ROOT / "scripts/VERIFY-MVP.ps1").read_text(encoding="utf-8")

    assert script.count('.Replace("`r`n", "`n").Replace("`r", "`n")') == 2
