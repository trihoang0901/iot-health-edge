from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ROOT / "plans/reports/260814-073149-software-e2e-acceptance"


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_software_acceptance_is_bound_to_commands_source_and_observations() -> None:
    scenario = json.loads((ACCEPTANCE / "scenario-acceptance.json").read_text("utf-8"))
    observations = json.loads((ACCEPTANCE / "scenario-observations.json").read_text("utf-8"))

    assert scenario["status"] == "passed"
    assert scenario["scope"] == "software_e2e_no_hardware_upload"
    assert scenario["source_provenance"]["scope"] == "runner_source_fingerprint"
    assert len(scenario["source_provenance"]["source_sha256"]) == 64
    assert [item["seed"] for item in scenario["commands"]] == [101, 102, 103]
    assert all("--device-id health-node-01" in item["command"] for item in scenario["commands"])
    assert scenario["observation_snapshot"]["sha256"] == _digest(
        ACCEPTANCE / "scenario-observations.json"
    )
    assert observations["capture_kind"] == "sanitized_api_observation_snapshot"
    assert [item["row_count"] for item in observations["telemetry_runs"]] == [20, 20, 20]
    assert [item["seq_last"] for item in observations["telemetry_runs"]] == [20, 20, 20]
    assert observations["alert"]["state"] == "acknowledged"


def test_software_acceptance_uses_safe_verification_and_current_browser_references() -> None:
    scenario = json.loads((ACCEPTANCE / "scenario-acceptance.json").read_text("utf-8"))
    browser_path = ROOT / scenario["browser_smoke"]["path"]
    browser = json.loads(browser_path.read_text("utf-8"))

    # VERIFY writes a running sentinel before pytest, so comparing the live
    # verification artifact here would create a self-invalidating test. The
    # acceptance packager performs the exact post-run hash/schema check.
    assert scenario["verification"]["path"] == "evidence/analysis/verification-latest.json"
    assert len(scenario["verification"]["sha256"]) == 64
    assert scenario["browser_smoke"]["sha256"] == _digest(browser_path)
    assert browser["status"] == "passed"


def test_report_commands_respect_broker_acl_binding() -> None:
    report = (ROOT / "deliverables/BAO-CAO-NT532-MQTT-MVP.md").read_text("utf-8")
    demo = (ROOT / "docs/demo-nt532.md").read_text("utf-8")

    for stale_device in ("nt532-normal-01", "nt532-motion-01", "nt532-spo2-01"):
        assert stale_device not in report
        assert stale_device not in demo
    assert report.count("python -m simulator --device-id health-node-01") >= 3
    assert demo.count("python -m simulator --device-id health-node-01") >= 3


def test_word_render_persists_updated_field_caches() -> None:
    script = (ROOT / "scripts/render_docx_word.ps1").read_text("utf-8")

    assert "$document = $word.Documents.Open($inputPath, $false, $false)" in script
    assert "$document.Repaginate()" in script
    assert "$document.Fields.Update()" in script
    assert "$document.Save()" in script
