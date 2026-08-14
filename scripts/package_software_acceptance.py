from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Mapping
import zipfile

from simulator.experiment import source_provenance

try:
    from verification_source_fingerprint import (
        build_fingerprint,
        ensure_safe_path,
        is_link_or_reparse,
        stable_content_identity,
    )
except ModuleNotFoundError:  # Allows importing this script as scripts.* in tests.
    from scripts.verification_source_fingerprint import (
        build_fingerprint,
        ensure_safe_path,
        is_link_or_reparse,
        stable_content_identity,
    )


ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE_ROOT = "plans/reports/260814-073149-software-e2e-acceptance"
DEFAULT_OUTPUT = ROOT / "evidence/final/nt532-software-e2e-acceptance.zip"
FIXED_ZIP_TIME = (2026, 8, 14, 0, 0, 0)
VIEWPORTS = ("mobile-320", "mobile-360", "tablet-768", "desktop-1440")
UI_SOURCE_FILES = (
    "edge/static/app.js",
    "edge/static/index.html",
    "edge/static/styles.css",
    "scripts/dashboard-browser-smoke.js",
)
SERVED_ASSET_FILES = (
    "edge/static/favicon.svg",
    "edge/static/styles.css",
    "edge/static/app.js",
)
DRY_RUNS = {
    "acceptance-dry-lan-20260814": "lan-baseline",
    "acceptance-dry-remote-20260814": "remote-app-emulated",
}
ACCEPTANCE_FILES = (
    f"{ACCEPTANCE_ROOT}/report.md",
    f"{ACCEPTANCE_ROOT}/scenario-acceptance.json",
    f"{ACCEPTANCE_ROOT}/scenario-observations.json",
    f"{ACCEPTANCE_ROOT}/ui/browser-smoke.json",
    *(f"{ACCEPTANCE_ROOT}/ui/dashboard-{viewport}.png" for viewport in VIEWPORTS),
    *(
        f"{ACCEPTANCE_ROOT}/dry-runs/{run_id}/{name}"
        for run_id in DRY_RUNS
        for name in ("manifest.json", "samples.jsonl", "summary.json")
    ),
)
TEXT_SUFFIXES = (".md", ".json", ".jsonl")
SENSITIVE_FIELD_RE = re.compile(
    rb'(?i)(?:"?(?:password|passwd|token|authorization|secret|username|raw_exception|'
    rb'api[_-]?key|access[_-]?key|client[_-]?secret|private[_-]?key|'
    rb'bot[_-]?token|chat[_-]?id)"?\s*[:=])'
)
KNOWN_SECRET_RE = re.compile(
    rb"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|"
    rb"gh[oprsu]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|"
    rb"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b)"
)
ABSOLUTE_PATH_RE = re.compile(
    rb"(?:(?<![A-Za-z])[A-Za-z]:[\\/](?![\\/])|"
    rb"(?<![.A-Za-z0-9])\\\\|/Users/|/home/)"
)
SELF_HASH_LINE_RE = re.compile(
    r"(?im)^(?=.*(?:bundle|gói))(?=.*\b[0-9a-f]{64}\b).*$"
)


def digest_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def require_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def strict_json_bytes(relative: str, data: bytes) -> object:
    def reject(value: str) -> None:
        raise ValueError(f"non-finite JSON constant in {relative}: {value}")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key in {relative}: {key}")
            result[key] = value
        return result

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"non-UTF-8 text artifact: {relative}") from exc
    try:
        return json.loads(
            text,
            parse_constant=reject,
            object_pairs_hook=reject_duplicates,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON artifact: {relative}") from exc


def strict_json_file(relative: str) -> object:
    path = ROOT / relative
    ensure_safe_path(path, ROOT)
    if not path.is_file():
        raise FileNotFoundError(f"missing or unsafe referenced artifact: {relative}")
    return strict_json_bytes(relative, path.read_bytes())


def strict_jsonl(relative: str, data: bytes) -> list[dict[str, object]]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(f"non-UTF-8 text artifact: {relative}") from exc
    if not lines or any(not line.strip() for line in lines):
        raise ValueError(f"JSONL must contain non-empty lines only: {relative}")
    rows: list[dict[str, object]] = []
    for index, line in enumerate(lines, start=1):
        value = strict_json_bytes(f"{relative}:{index}", line.encode("utf-8"))
        rows.append(require_mapping(value, f"{relative}:{index}"))
    return rows


def scoped_digest(files: tuple[str, ...], *, separator: bool = True) -> str:
    digest = sha256()
    for relative in files:
        path = ROOT / relative
        ensure_safe_path(path, ROOT)
        if separator:
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
        digest.update(path.read_bytes())
        if separator:
            digest.update(b"\0")
    return digest.hexdigest()


def require_current_content(
    recorded: Mapping[str, object],
    current: Mapping[str, object],
    label: str,
) -> None:
    if stable_content_identity(recorded) != stable_content_identity(current):
        raise ValueError(f"{label} content fingerprint is stale")


def validate_exact_artifact_set() -> None:
    base = ROOT / ACCEPTANCE_ROOT
    ensure_safe_path(base, ROOT)
    if not base.is_dir():
        raise FileNotFoundError("missing or unsafe acceptance artifact directory")
    actual: set[str] = set()
    for path in base.rglob("*"):
        ensure_safe_path(path, ROOT)
        if path.is_file():
            actual.add(path.relative_to(ROOT).as_posix())
    expected = set(ACCEPTANCE_FILES)
    if actual != expected:
        raise ValueError(
            "acceptance artifact set mismatch: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def collect_raw_entries() -> dict[str, bytes]:
    validate_exact_artifact_set()
    entries: dict[str, bytes] = {}
    for relative in ACCEPTANCE_FILES:
        path = ROOT / relative
        ensure_safe_path(path, ROOT)
        if not path.is_file():
            raise FileNotFoundError(f"missing or unsafe acceptance artifact: {relative}")
        entries[relative] = path.read_bytes()
    return entries


def validate_report(entries: Mapping[str, bytes], output_name: str) -> None:
    relative = f"{ACCEPTANCE_ROOT}/report.md"
    try:
        report = entries[relative].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("acceptance report must be UTF-8") from exc
    required = (
        "status: MVP_SOFTWARE_ACCEPTED_WITH_DECLARED_LIMITATIONS",
        "scope: software-only, no hardware upload",
        "# Kết luận",
        "**MVP phần mềm để demo/chấm môn:** GO.",
        "**Tuyên bố sản phẩm y tế, node vật lý đã xác minh hoặc 5G đã đo:** NO-GO.",
    )
    if any(fragment not in report for fragment in required):
        raise ValueError("acceptance report contract mismatch")
    forbidden_names = {
        output_name.casefold(),
        f"{output_name}.sha256".casefold(),
        DEFAULT_OUTPUT.name.casefold(),
        f"{DEFAULT_OUTPUT.name}.sha256".casefold(),
    }
    lowered = report.casefold()
    if any(name in lowered for name in forbidden_names) or SELF_HASH_LINE_RE.search(report):
        raise ValueError("acceptance report must not embed its bundle checksum")


def validate_verification_reference(scenario: Mapping[str, object]) -> None:
    reference = require_mapping(scenario.get("verification"), "verification reference")
    relative = "evidence/analysis/verification-latest.json"
    if reference.get("path") != relative:
        raise ValueError("acceptance verification path mismatch")
    path = ROOT / relative
    ensure_safe_path(path, ROOT)
    if not path.is_file():
        raise FileNotFoundError("missing or unsafe acceptance verification reference")
    data = path.read_bytes()
    verification = require_mapping(
        strict_json_bytes(relative, data), "verification report"
    )
    if (
        reference.get("sha256") != digest_bytes(data)
        or reference.get("artifact_version") != "1.3"
        or reference.get("overall_status") != "passed"
        or verification.get("artifact_version") != "1.3"
        or verification.get("overall_status") != "passed"
        or verification.get("command")
        != ".\\scripts\\VERIFY-MVP.ps1 -IncludeDockerLive -IncludeFirmware"
        or verification.get("launcher_or_upload_used") is not False
    ):
        raise ValueError("acceptance verification reference is stale")
    checks = verification.get("checks")
    if not isinstance(checks, list) or len(checks) != 6 or any(
        not isinstance(check, dict) or check.get("status") != "passed"
        for check in checks
    ):
        raise ValueError("acceptance verification check set mismatch")
    require_current_content(
        require_mapping(
            verification.get("runner_source_provenance"),
            "verification runner provenance",
        ),
        source_provenance(),
        "acceptance verification runner",
    )
    require_current_content(
        require_mapping(
            verification.get("verification_input_provenance"),
            "verification input provenance",
        ),
        build_fingerprint(),
        "acceptance verification input",
    )


def validate_scenario(entries: Mapping[str, bytes]) -> None:
    scenario_path = f"{ACCEPTANCE_ROOT}/scenario-acceptance.json"
    observation_path = f"{ACCEPTANCE_ROOT}/scenario-observations.json"
    browser_path = f"{ACCEPTANCE_ROOT}/ui/browser-smoke.json"
    scenario = require_mapping(
        strict_json_bytes(scenario_path, entries[scenario_path]),
        "scenario acceptance",
    )
    if (
        scenario.get("artifact_version") != "1.0"
        or scenario.get("status") != "passed"
        or scenario.get("scope") != "software_e2e_no_hardware_upload"
        or scenario.get("device_id") != "health-node-01"
    ):
        raise ValueError("scenario acceptance contract mismatch")
    require_current_content(
        require_mapping(scenario.get("source_provenance"), "scenario provenance"),
        source_provenance(),
        "scenario acceptance",
    )
    validate_verification_reference(scenario)

    observation_ref = require_mapping(
        scenario.get("observation_snapshot"), "observation reference"
    )
    browser_ref = require_mapping(scenario.get("browser_smoke"), "browser reference")
    if (
        observation_ref.get("path") != observation_path
        or observation_ref.get("sha256") != digest_bytes(entries[observation_path])
        or browser_ref.get("path") != browser_path
        or browser_ref.get("sha256") != digest_bytes(entries[browser_path])
        or browser_ref.get("status") != "passed"
    ):
        raise ValueError("scenario acceptance internal reference mismatch")

    commands = scenario.get("commands")
    expected_commands = (
        (
            "normal",
            101,
            "python -m simulator --device-id health-node-01 --scenario normal --count 20 --seed 101",
        ),
        (
            "motion_artifact",
            102,
            "python -m simulator --device-id health-node-01 --scenario motion_artifact --count 20 --seed 102",
        ),
        (
            "low_spo2",
            103,
            "python -m simulator --device-id health-node-01 --scenario low_spo2 --count 20 --seed 103",
        ),
    )
    if not isinstance(commands, list) or len(commands) != len(expected_commands) or any(
        not isinstance(command, dict)
        or command.get("scenario") != expected[0]
        or command.get("seed") != expected[1]
        or command.get("command") != expected[2]
        for command, expected in zip(commands, expected_commands)
    ):
        raise ValueError("scenario command set mismatch")
    normal = require_mapping(scenario.get("normal"), "normal scenario")
    motion = require_mapping(scenario.get("motion_artifact"), "motion scenario")
    low_spo2 = require_mapping(scenario.get("low_spo2"), "low SpO2 scenario")
    if (
        normal.get("seq") != 20
        or normal.get("heart_rate_valid") is not True
        or normal.get("spo2_valid") is not True
        or normal.get("new_alerts") != 0
        or motion.get("seq") != 20
        or motion.get("motion_artifact") is not True
        or motion.get("heart_rate") is not None
        or motion.get("spo2") is not None
        or motion.get("new_alerts") != 0
        or low_spo2.get("seq") != 20
        or low_spo2.get("spo2_valid") is not True
        or low_spo2.get("new_alert_count") != 1
        or low_spo2.get("ack_repeated") is not True
        or low_spo2.get("ack_state") != "acknowledged"
    ):
        raise ValueError("scenario acceptance result mismatch")

    observations = require_mapping(
        strict_json_bytes(observation_path, entries[observation_path]),
        "scenario observations",
    )
    telemetry_runs = observations.get("telemetry_runs")
    if not isinstance(telemetry_runs, list):
        raise ValueError("scenario observation run set mismatch")
    observed_by_scenario = {
        run.get("scenario"): run for run in telemetry_runs if isinstance(run, dict)
    }
    if any(
        observed_by_scenario.get(name, {}).get("boot_id")
        != recorded.get("boot_id")
        for name, recorded in (
            ("normal", normal),
            ("motion_artifact", motion),
            ("low_spo2", low_spo2),
        )
    ):
        raise ValueError("scenario observation boot identity mismatch")
    observed_alert = require_mapping(observations.get("alert"), "observation alert")
    if observed_alert.get("id") != low_spo2.get("alert_id"):
        raise ValueError("scenario observation alert identity mismatch")


def validate_observations(entries: Mapping[str, bytes]) -> None:
    relative = f"{ACCEPTANCE_ROOT}/scenario-observations.json"
    payload = require_mapping(
        strict_json_bytes(relative, entries[relative]), "scenario observations"
    )
    health = require_mapping(payload.get("health"), "observation health")
    mqtt = require_mapping(health.get("mqtt"), "observation MQTT health")
    ingestion = require_mapping(health.get("ingestion"), "observation ingestion")
    if (
        payload.get("artifact_version") != "1.0"
        or payload.get("capture_kind") != "sanitized_api_observation_snapshot"
        or health.get("status") != "ok"
        or health.get("non_clinical") is not True
        or mqtt.get("connected") is not True
        or mqtt.get("subscribed") is not True
        or mqtt.get("has_error") is not False
        or ingestion.get("processing_errors") != 0
        or ingestion.get("worker_alive") is not True
        or ingestion.get("has_error") is not False
    ):
        raise ValueError("scenario observation health mismatch")
    telemetry_runs = payload.get("telemetry_runs")
    if not isinstance(telemetry_runs, list) or len(telemetry_runs) != 3 or {
        run.get("scenario") for run in telemetry_runs if isinstance(run, dict)
    } != {"normal", "motion_artifact", "low_spo2"}:
        raise ValueError("scenario observation run set mismatch")
    if any(
        not isinstance(run, dict)
        or run.get("row_count") != 20
        or run.get("seq_first") != 1
        or run.get("seq_last") != 20
        for run in telemetry_runs
    ):
        raise ValueError("scenario observation sequence mismatch")
    alert = require_mapping(payload.get("alert"), "observation alert")
    if (
        alert.get("rule_id") != "demo_low_spo2"
        or alert.get("state") != "acknowledged"
        or alert.get("occurrence_count") != 10
    ):
        raise ValueError("scenario observation alert mismatch")


def validate_browser(entries: Mapping[str, bytes]) -> None:
    relative = f"{ACCEPTANCE_ROOT}/ui/browser-smoke.json"
    payload = require_mapping(
        strict_json_bytes(relative, entries[relative]), "acceptance browser smoke"
    )
    expected_served = scoped_digest(SERVED_ASSET_FILES, separator=False)[:12]
    if (
        payload.get("artifact_version") != "1.1"
        or payload.get("status") != "passed"
        or payload.get("served_asset_version") != expected_served
    ):
        raise ValueError("acceptance browser smoke contract mismatch")
    provenance = require_mapping(payload.get("source_provenance"), "browser provenance")
    if (
        provenance.get("scope") != "dashboard_static_and_smoke_script"
        or provenance.get("source_files") != list(UI_SOURCE_FILES)
        or provenance.get("source_sha256") != scoped_digest(UI_SOURCE_FILES)
    ):
        raise ValueError("acceptance browser source fingerprint is stale")
    checks = payload.get("checks")
    if not isinstance(checks, list) or len(checks) != len(VIEWPORTS) or {
        check.get("name") for check in checks if isinstance(check, dict)
    } != set(VIEWPORTS):
        raise ValueError("acceptance browser viewport set mismatch")
    screenshot_names: set[str] = set()
    for check in checks:
        if (
            not isinstance(check, dict)
            or check.get("served_asset_version") != expected_served
            or check.get("horizontalOverflowPx") != 0
            or check.get("duplicateIds") != []
            or check.get("unlabeledControls") != []
        ):
            raise ValueError("acceptance browser check mismatch")
        screenshot = check.get("screenshot")
        if not isinstance(screenshot, str) or Path(screenshot).name != screenshot:
            raise ValueError("acceptance browser screenshot path must be a basename")
        screenshot_names.add(screenshot)
        screenshot_relative = f"{ACCEPTANCE_ROOT}/ui/{screenshot}"
        if (
            screenshot_relative not in entries
            or check.get("screenshot_sha256")
            != digest_bytes(entries[screenshot_relative])
        ):
            raise ValueError("acceptance browser screenshot hash mismatch")
    if screenshot_names != {f"dashboard-{viewport}.png" for viewport in VIEWPORTS}:
        raise ValueError("acceptance browser screenshot set mismatch")


def validate_dry_runs(entries: Mapping[str, bytes]) -> None:
    current = source_provenance()
    for run_id, profile_name in DRY_RUNS.items():
        base = f"{ACCEPTANCE_ROOT}/dry-runs/{run_id}"
        manifest = require_mapping(
            strict_json_bytes(f"{base}/manifest.json", entries[f"{base}/manifest.json"]),
            f"{run_id} manifest",
        )
        summary = require_mapping(
            strict_json_bytes(f"{base}/summary.json", entries[f"{base}/summary.json"]),
            f"{run_id} summary",
        )
        samples = strict_jsonl(f"{base}/samples.jsonl", entries[f"{base}/samples.jsonl"])
        profile = require_mapping(manifest.get("profile"), f"{run_id} profile")
        claims = require_mapping(manifest.get("claims"), f"{run_id} claims")
        count = manifest.get("count")
        if (
            manifest.get("artifact_version") != "5.0"
            or manifest.get("run_id") != run_id
            or manifest.get("status") != "planned"
            or profile.get("name") != profile_name
            or profile.get("profile_kind") != "app_impairment"
            or profile.get("network_claim") != "none"
            or claims.get("network_claim") != "none"
            or claims.get("measured_5g") is not False
            or not isinstance(count, int)
            or count != 30
        ):
            raise ValueError(f"{run_id} manifest contract mismatch")
        require_current_content(
            require_mapping(manifest.get("source_provenance"), f"{run_id} provenance"),
            current,
            f"{run_id} runner",
        )
        if len(samples) != count:
            raise ValueError(f"{run_id} sample count mismatch")
        for index, sample in enumerate(samples):
            if (
                sample.get("artifact_version") != "5.0"
                or sample.get("run_id") != run_id
                or sample.get("scheduled_index") != index
                or sample.get("seq") != index + 1
                or sample.get("scheduled") is not True
                or sample.get("publish_attempted") is not False
                or sample.get("attempt_count") != 0
                or sample.get("published") is not False
                or sample.get("ingested") is not False
                or sample.get("api_observed") is not False
            ):
                raise ValueError(f"{run_id} planned sample reconciliation failed")
        dropped = sum(sample.get("intentionally_dropped") is True for sample in samples)
        if (
            summary.get("artifact_version") != "5.0"
            or summary.get("run_id") != run_id
            or summary.get("status") != "planned"
            or summary.get("scheduled") != count
            or summary.get("intentionally_dropped") != dropped
            or summary.get("attempt_count") != 0
            or summary.get("published") != 0
            or summary.get("ingested") != 0
            or summary.get("api_observed") != 0
            or summary.get("network_claim") != "none"
        ):
            raise ValueError(f"{run_id} summary reconciliation failed")


def validate_redaction(entries: Mapping[str, bytes]) -> dict[str, object]:
    scanned = 0
    for relative, data in entries.items():
        if not relative.casefold().endswith(TEXT_SUFFIXES):
            continue
        scanned += 1
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"non-UTF-8 text artifact: {relative}") from exc
        if SENSITIVE_FIELD_RE.search(data) or KNOWN_SECRET_RE.search(data):
            raise ValueError(f"sensitive value shape in acceptance evidence: {relative}")
        if ABSOLUTE_PATH_RE.search(data):
            raise ValueError(f"absolute workstation path in acceptance evidence: {relative}")
    return {
        "status": "passed",
        "text_files_scanned": scanned,
        "sensitive_value_hits": 0,
        "absolute_path_hits": 0,
    }


def collect_entries(output_name: str) -> tuple[dict[str, bytes], dict[str, object]]:
    entries = collect_raw_entries()
    validate_report(entries, output_name)
    validate_scenario(entries)
    validate_observations(entries)
    validate_browser(entries)
    validate_dry_runs(entries)
    redaction = validate_redaction(entries)
    return entries, redaction


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def atomic_write_bytes(path: Path, data: bytes) -> None:
    if is_link_or_reparse(path):
        raise ValueError(f"symlink or reparse output forbidden: {path.name}")
    if path.exists() and not path.is_file():
        raise ValueError(f"output must be a regular file: {path.name}")
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w+b",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_archive(
    output: Path,
    entries: Mapping[str, bytes],
    inventory_bytes: bytes,
) -> None:
    if is_link_or_reparse(output):
        raise ValueError(f"symlink or reparse output forbidden: {output.name}")
    if output.exists() and not output.is_file():
        raise ValueError(f"output must be a regular file: {output.name}")
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w+b",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            with zipfile.ZipFile(handle, "w") as archive:
                for relative, data in sorted(entries.items()):
                    archive.writestr(zip_info(relative), data)
                archive.writestr(zip_info("inventory.json"), inventory_bytes)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_bundle(
    output: Path,
    entries: Mapping[str, bytes],
    redaction: Mapping[str, object],
) -> dict[str, object]:
    inventory = {
        "bundle_version": "1.0",
        "artifact_set": "nt532_software_e2e_acceptance",
        "allowlisted_file_count": len(entries),
        "redaction": dict(redaction),
        "source_identity": stable_content_identity(source_provenance()),
        "files": [
            {
                "path": relative,
                "size": len(data),
                "sha256": digest_bytes(data),
            }
            for relative, data in sorted(entries.items())
        ],
    }
    inventory_bytes = (
        json.dumps(inventory, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    ).encode("utf-8")
    checksum = output.with_suffix(output.suffix + ".sha256")
    if (
        is_link_or_reparse(output.parent)
        or is_link_or_reparse(output)
        or is_link_or_reparse(checksum)
    ):
        raise ValueError("symlink or reparse bundle output forbidden")
    write_archive(output, entries, inventory_bytes)
    archive_hash = digest_bytes(output.read_bytes())
    atomic_write_bytes(
        checksum,
        f"{archive_hash}  {output.name}\n".encode("ascii"),
    )
    return {
        "output": output.name,
        "sha256": archive_hash,
        "allowlisted_file_count": len(entries),
        "text_files_scanned": redaction.get("text_files_scanned"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create the fail-closed NT532 software E2E acceptance bundle."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    final_directory = Path(os.path.abspath(ROOT / "evidence" / "final"))
    ensure_safe_path(final_directory, ROOT)
    if not final_directory.is_dir():
        parser.error("evidence/final must be a real directory")
    output = Path(os.path.abspath(args.output))
    if output.parent != final_directory:
        parser.error("--output must stay directly under evidence/final")
    if output.suffix.casefold() != ".zip":
        parser.error("--output must use the .zip suffix")
    entries, redaction = collect_entries(output.name)
    result = write_bundle(output, entries, redaction)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
