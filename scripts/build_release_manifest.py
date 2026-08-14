from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "evidence/final/nt532-release-manifest.json"
ARTIFACTS = (
    ("report_docx", "deliverables/BAO-CAO-NT532-MQTT-MVP.docx", None),
    ("report_source", "deliverables/BAO-CAO-NT532-MQTT-MVP.md", None),
    (
        "research_evidence_zip",
        "evidence/final/nt532-mqtt-mvp-evidence-v5.zip",
        "evidence/final/nt532-mqtt-mvp-evidence-v5.zip.sha256",
    ),
    (
        "software_acceptance_zip",
        "evidence/final/nt532-software-e2e-acceptance.zip",
        "evidence/final/nt532-software-e2e-acceptance.zip.sha256",
    ),
)


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def validate_sidecar(path: Path, artifact: Path, expected: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"missing SHA-256 sidecar: {path.relative_to(ROOT)}")
    parts = path.read_text(encoding="ascii").strip().split()
    if len(parts) != 2 or parts[0].lower() != expected or parts[1] != artifact.name:
        raise ValueError(f"invalid SHA-256 sidecar: {path.relative_to(ROOT)}")


def build_manifest() -> dict[str, object]:
    artifacts: list[dict[str, object]] = []
    for kind, relative, sidecar_relative in ARTIFACTS:
        path = ROOT / relative
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(f"missing or unsafe release artifact: {relative}")
        artifact_digest = digest(path)
        if sidecar_relative is not None:
            validate_sidecar(ROOT / sidecar_relative, path, artifact_digest)
        artifacts.append(
            {
                "kind": kind,
                "path": relative,
                "size": path.stat().st_size,
                "sha256": artifact_digest,
            }
        )
    return {
        "artifact_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        "status": "ready_for_submission_with_declared_limitations",
        "scope": "nt532_software_mvp",
        "artifacts": artifacts,
        "limitations": [
            "physical_node_runtime_not_verified_in_final_software_batch",
            "manual_screen_reader_and_400_percent_zoom_not_verified",
            "app_impairment_is_not_network_or_5g_measurement",
            "non_clinical_prototype",
            "official_rubric_and_page_limit_not_provided",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a non-self-referential manifest for final NT532 artifacts."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.parent != (ROOT / "evidence/final").resolve():
        parser.error("--output must stay directly under evidence/final")
    payload = build_manifest()
    data = (
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    ).encode("utf-8")
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({"output": str(output), "sha256": sha256(data).hexdigest()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
