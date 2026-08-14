from __future__ import annotations

from pathlib import Path

import pytest

from scripts import build_release_manifest as release


def test_release_manifest_is_relative_and_non_self_referential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = (
        ("report_docx", "deliverables/report.docx", None),
        ("report_source", "deliverables/report.md", None),
        ("research_evidence_zip", "evidence/final/research.zip", "evidence/final/research.zip.sha256"),
        ("software_acceptance_zip", "evidence/final/acceptance.zip", "evidence/final/acceptance.zip.sha256"),
    )
    for _, relative, sidecar_relative in artifacts:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode("utf-8"))
        if sidecar_relative is not None:
            sidecar = tmp_path / sidecar_relative
            sidecar.write_text(f"{release.digest(path)}  {path.name}\n", encoding="ascii")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    monkeypatch.setattr(release, "ARTIFACTS", artifacts)

    payload = release.build_manifest()

    assert payload["status"] == "ready_for_submission_with_declared_limitations"
    paths = [item["path"] for item in payload["artifacts"]]
    assert paths == [item[1] for item in artifacts]
    assert all(not Path(path).is_absolute() for path in paths)
    assert "evidence/final/nt532-release-manifest.json" not in paths
    assert len(payload["limitations"]) == 5


def test_release_manifest_rejects_a_mismatched_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release, "ROOT", tmp_path)
    artifact = tmp_path / "artifact.zip"
    sidecar = tmp_path / "artifact.zip.sha256"
    artifact.write_bytes(b"artifact")
    sidecar.write_text("0" * 64 + "  artifact.zip\n", encoding="ascii")

    with pytest.raises(ValueError, match="invalid SHA-256 sidecar"):
        release.validate_sidecar(sidecar, artifact, release.digest(artifact))
