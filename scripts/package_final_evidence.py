from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import zipfile

from simulator.aggregate import build_aggregate
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
RUN_PREFIX = "nt532-rq2-v5-"
ARTIFACT_VERSION = "5.0"
RUN_FILE_NAMES = ("manifest.json", "samples.jsonl", "summary.json")
RUN_NAME_RE = re.compile(r"^nt532-rq2-v5-(lan|remote)-(\d{3})$")
FIXED_ZIP_TIME = (2026, 8, 14, 0, 0, 0)
SUPPORT_FILES = (
    "evidence/analysis/rq2-v5-experiments.json",
    "evidence/analysis/baseline-reliability.json",
    "evidence/analysis/hardened-reliability.json",
    "evidence/analysis/verification-latest.json",
    "evidence/ui/browser-smoke.json",
    "evidence/ui/dashboard-mobile-320.png",
    "evidence/ui/dashboard-mobile-360.png",
    "evidence/ui/dashboard-tablet-768.png",
    "evidence/ui/dashboard-desktop-1440.png",
)
BASELINE_COMMIT = "7030e4b30300dec65646e3091356ca00d9eaa8f5"
BASELINE_RQ1_SHA256 = "760429f9dceed614279cb6c937d111a66fb1cb63ca813ed615c7de1bbd24c280"
RQ1_SOURCE_FILES = (
    "edge/db.py",
    "edge/rules.py",
    "edge/service.py",
    "edge/mqtt_client.py",
)
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
VIEWPORTS = {"mobile-320", "mobile-360", "tablet-768", "desktop-1440"}
SENSITIVE_JSON_KEY_RE = re.compile(
    rb'"(?:password|passwd|token|authorization|secret|username|raw_exception|'
    rb'api[_-]?key|access[_-]?key|client[_-]?secret|private[_-]?key|'
    rb'bot[_-]?token|chat[_-]?id)"\s*:',
    re.IGNORECASE,
)
ABSOLUTE_PATH_RE = re.compile(
    rb"(?:(?<![A-Za-z])[A-Za-z]:[\\/](?![\\/])|"
    rb"(?<![.A-Za-z0-9])\\\\|/Users/|/home/)"
)


def digest_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


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
        raise ValueError(f"non-UTF-8 JSON artifact: {relative}") from exc
    try:
        return json.loads(
            text,
            parse_constant=reject,
            object_pairs_hook=reject_duplicates,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON artifact: {relative}") from exc


def strict_json(path: Path) -> object:
    ensure_safe_path(path, ROOT)
    return strict_json_bytes(path.relative_to(ROOT).as_posix(), path.read_bytes())


def expected_run_names() -> set[str]:
    return {
        f"{RUN_PREFIX}{profile}-{seed:03d}"
        for profile in ("lan", "remote")
        for seed in range(1, 31)
    }


def add_entry(entries: dict[str, bytes], relative: str) -> None:
    path = ROOT / relative
    ensure_safe_path(path, ROOT)
    if not path.is_file():
        raise FileNotFoundError(f"missing or unsafe final evidence file: {relative}")
    entries[relative] = path.read_bytes()


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


def require_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def require_current_content(
    recorded: dict[str, object],
    current: dict[str, object],
    label: str,
) -> None:
    """Compare stable bytes/file scope without coupling evidence to Git HEAD."""

    if stable_content_identity(recorded) != stable_content_identity(current):
        raise ValueError(f"{label} content fingerprint is stale")


def validate_rq1() -> None:
    baseline = require_mapping(
        strict_json(ROOT / "evidence/analysis/baseline-reliability.json"),
        "RQ1 baseline",
    )
    hardened = require_mapping(
        strict_json(ROOT / "evidence/analysis/hardened-reliability.json"),
        "RQ1 hardened",
    )
    for payload, implementation, expected_cases in (
        (
            baseline,
            "baseline",
            {"atomic_alert_passed": 0, "old_lwt_session_passed": 0},
        ),
        (
            hardened,
            "hardened",
            {"atomic_alert_passed": 30, "old_lwt_session_passed": 30},
        ),
    ):
        if (
            payload.get("artifact_version") != "1.0"
            or payload.get("implementation") != implementation
            or payload.get("repetitions") != 30
            or payload.get("cases") != expected_cases
            or payload.get("deterministic_repeatability_only") is not True
            or payload.get("inferential_confidence_interval") is not None
        ):
            raise ValueError(f"RQ1 {implementation} contract mismatch")
        runs = payload.get("runs")
        if not isinstance(runs, list) or len(runs) != 30:
            raise ValueError(f"RQ1 {implementation} raw run count mismatch")
        recomputed = {
            "atomic_alert_passed": sum(
                isinstance(run, dict)
                and isinstance(run.get("atomic_alert"), dict)
                and run["atomic_alert"].get("pass") is True
                for run in runs
            ),
            "old_lwt_session_passed": sum(
                isinstance(run, dict)
                and isinstance(run.get("old_lwt_session"), dict)
                and run["old_lwt_session"].get("pass") is True
                for run in runs
            ),
        }
        if recomputed != expected_cases:
            raise ValueError(f"RQ1 {implementation} raw reconciliation failed")
    baseline_provenance = require_mapping(
        baseline.get("source_provenance"), "RQ1 baseline provenance"
    )
    hardened_provenance = require_mapping(
        hardened.get("source_provenance"), "RQ1 hardened provenance"
    )
    if (
        baseline.get("commit") != BASELINE_COMMIT
        or baseline.get("baseline_commit") != BASELINE_COMMIT
        or baseline_provenance.get("source_state") != "commit_clean"
        or baseline_provenance.get("rq1_source_sha256") != BASELINE_RQ1_SHA256
    ):
        raise ValueError("RQ1 baseline source identity mismatch")
    if (
        hardened.get("baseline_commit") != BASELINE_COMMIT
        or hardened_provenance.get("rq1_source_files") != list(RQ1_SOURCE_FILES)
        or hardened_provenance.get("rq1_source_sha256")
        != scoped_digest(RQ1_SOURCE_FILES)
    ):
        raise ValueError("RQ1 hardened source identity mismatch")
    if any(
        not isinstance(run, dict)
        or not isinstance(run.get("old_lwt_session"), dict)
        or run["old_lwt_session"].get("stale_disposition") != "stale"
        for run in hardened["runs"]  # type: ignore[index]
    ):
        raise ValueError("RQ1 hardened old LWT disposition mismatch")


def validate_verification() -> None:
    payload = require_mapping(
        strict_json(ROOT / "evidence/analysis/verification-latest.json"),
        "verification report",
    )
    if (
        payload.get("artifact_version") != "1.3"
        or payload.get("overall_status") != "passed"
        or payload.get("command")
        != ".\\scripts\\VERIFY-MVP.ps1 -IncludeDockerLive -IncludeFirmware"
        or payload.get("launcher_or_upload_used") is not False
    ):
        raise ValueError("verification report is not the canonical full pass")
    checks = payload.get("checks")
    if not isinstance(checks, list) or len(checks) != 6:
        raise ValueError("verification check set mismatch")
    if any(not isinstance(check, dict) or check.get("status") != "passed" for check in checks):
        raise ValueError("verification contains a non-passing gate")
    require_current_content(
        require_mapping(
            payload.get("runner_source_provenance"),
            "verification runner provenance",
        ),
        source_provenance(),
        "verification runner",
    )
    require_current_content(
        require_mapping(
            payload.get("verification_input_provenance"),
            "verification input provenance",
        ),
        build_fingerprint(),
        "verification input",
    )


def validate_rq2_current_source(aggregate: dict[str, object]) -> None:
    controls = require_mapping(aggregate.get("controls"), "RQ2 controls")
    recorded = require_mapping(
        controls.get("source_provenance"), "RQ2 source provenance"
    )
    current = source_provenance()
    if (
        recorded.get("source_sha256") != current.get("source_sha256")
        or recorded.get("source_files") != current.get("source_files")
    ):
        raise ValueError("RQ2 aggregate source fingerprint is stale")


def validate_browser() -> None:
    payload = require_mapping(
        strict_json(ROOT / "evidence/ui/browser-smoke.json"),
        "browser smoke report",
    )
    expected_served = scoped_digest(SERVED_ASSET_FILES, separator=False)[:12]
    if (
        payload.get("artifact_version") != "1.1"
        or payload.get("status") != "passed"
        or payload.get("served_asset_version") != expected_served
    ):
        raise ValueError("browser smoke is not a current completed pass")
    provenance = require_mapping(payload.get("source_provenance"), "browser provenance")
    if (
        provenance.get("scope") != "dashboard_static_and_smoke_script"
        or provenance.get("source_files") != list(UI_SOURCE_FILES)
        or provenance.get("source_sha256") != scoped_digest(UI_SOURCE_FILES)
    ):
        raise ValueError("browser smoke source fingerprint is stale")
    checks = payload.get("checks")
    if not isinstance(checks, list) or {
        check.get("name") for check in checks if isinstance(check, dict)
    } != VIEWPORTS:
        raise ValueError("browser smoke viewport set mismatch")
    for check in checks:
        if not isinstance(check, dict) or check.get("served_asset_version") != expected_served:
            raise ValueError("browser smoke served asset mismatch")
        name = check.get("screenshot")
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("browser screenshot path must be a basename")
        screenshot = ROOT / "evidence" / "ui" / name
        if not screenshot.is_file() or check.get("screenshot_sha256") != digest_bytes(
            screenshot.read_bytes()
        ):
            raise ValueError("browser screenshot hash mismatch")


def validate_redaction(entries: dict[str, bytes]) -> dict[str, object]:
    scanned = 0
    for relative, data in entries.items():
        if not relative.endswith((".json", ".jsonl")):
            continue
        scanned += 1
        if relative.endswith(".json"):
            strict_json_bytes(relative, data)
        else:
            try:
                lines = data.decode("utf-8").splitlines()
            except UnicodeDecodeError as exc:
                raise ValueError(f"non-UTF-8 JSONL artifact: {relative}") from exc
            if not lines or any(not line.strip() for line in lines):
                raise ValueError(f"invalid JSONL artifact: {relative}")
            for index, line in enumerate(lines, start=1):
                strict_json_bytes(f"{relative}:{index}", line.encode("utf-8"))
        if SENSITIVE_JSON_KEY_RE.search(data):
            raise ValueError(f"sensitive JSON key in final evidence: {relative}")
        if ABSOLUTE_PATH_RE.search(data):
            raise ValueError(f"absolute workstation path in final evidence: {relative}")
    return {
        "status": "passed",
        "text_files_scanned": scanned,
        "sensitive_key_hits": 0,
        "absolute_path_hits": 0,
    }


def collect_entries() -> tuple[dict[str, bytes], list[str]]:
    validate_rq1()
    validate_verification()
    validate_browser()
    run_root = ROOT / "evidence" / "runs"
    ensure_safe_path(run_root, ROOT)
    matching: dict[str, Path] = {}
    for child in run_root.iterdir():
        if not child.name.startswith(RUN_PREFIX):
            continue
        ensure_safe_path(child, ROOT)
        if child.is_dir():
            matching[child.name] = child
    expected = expected_run_names()
    if set(matching) != expected:
        missing = sorted(expected - set(matching))
        extra = sorted(set(matching) - expected)
        raise ValueError(f"final run set mismatch: missing={missing}, extra={extra}")

    aggregate_path = ROOT / "evidence" / "analysis" / "rq2-v5-experiments.json"
    actual_aggregate = strict_json(aggregate_path)
    expected_aggregate = build_aggregate(
        run_root,
        run_prefix=RUN_PREFIX,
        min_seeds=30,
    )
    if actual_aggregate != expected_aggregate:
        raise ValueError("stored RQ2 aggregate does not reconcile with final raw runs")
    if not isinstance(actual_aggregate, dict) or (
        actual_aggregate.get("artifact_version") != ARTIFACT_VERSION
        or actual_aggregate.get("matched_seed_count") != 30
    ):
        raise ValueError("final RQ2 aggregate identity mismatch")
    validate_rq2_current_source(actual_aggregate)

    entries: dict[str, bytes] = {}
    omitted_sidecars: list[str] = []
    for run_name in sorted(matching):
        if not RUN_NAME_RE.fullmatch(run_name):
            raise ValueError(f"invalid final run name: {run_name}")
        run_dir = matching[run_name]
        for name in RUN_FILE_NAMES:
            add_entry(entries, f"evidence/runs/{run_name}/{name}")
        for child in run_dir.iterdir():
            if child.name not in RUN_FILE_NAMES:
                omitted_sidecars.append(
                    f"evidence/runs/{run_name}/{child.name}"
                )

    for relative in SUPPORT_FILES:
        add_entry(entries, relative)
    return entries, sorted(omitted_sidecars)


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


def write_archive(output: Path, entries: dict[str, bytes], inventory_bytes: bytes) -> None:
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create the fail-closed, portable NT532 final evidence bundle."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evidence" / "final" / "nt532-mqtt-mvp-evidence-v5.zip",
    )
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

    entries, omitted_sidecars = collect_entries()
    redaction = validate_redaction(entries)
    inventory = {
        "bundle_version": "1.0",
        "experiment_artifact_version": ARTIFACT_VERSION,
        "run_prefix": RUN_PREFIX,
        "matched_seed_count": 30,
        "run_count": 60,
        "allowlisted_file_count": len(entries),
        "omitted_run_sidecars": omitted_sidecars,
        "redaction": redaction,
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
    if is_link_or_reparse(output) or is_link_or_reparse(checksum):
        raise ValueError("symlink or reparse bundle output forbidden")
    write_archive(output, entries, inventory_bytes)

    archive_hash = digest_bytes(output.read_bytes())
    atomic_write_bytes(
        checksum,
        f"{archive_hash}  {output.name}\n".encode("ascii"),
    )
    print(
        json.dumps(
            {
                "output": output.name,
                "sha256": archive_hash,
                "allowlisted_file_count": len(entries),
                "omitted_sidecar_count": len(omitted_sidecars),
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
