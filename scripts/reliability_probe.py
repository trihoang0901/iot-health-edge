from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


BASELINE_COMMIT = "7030e4b30300dec65646e3091356ca00d9eaa8f5"


def _commit(source_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _source_provenance(source_root: Path) -> dict[str, Any]:
    files = (
        "edge/db.py",
        "edge/rules.py",
        "edge/service.py",
        "edge/mqtt_client.py",
    )
    digest = sha256()
    for relative in files:
        path = source_root / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    dirty = None
    try:
        result = subprocess.run(
            ["git", "-C", str(source_root), "status", "--porcelain", "--", *files],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
        dirty = bool(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "head_commit": _commit(source_root),
        "source_state": (
            "worktree_uncommitted"
            if dirty is True
            else "commit_clean"
            if dirty is False
            else "unknown"
        ),
        "rq1_source_files": list(files),
        "rq1_source_sha256": digest.hexdigest(),
    }


def telemetry_payload(*, boot_id: str, seq: int, spo2: float = 88.5) -> dict[str, Any]:
    return {
        "schema": "health.telemetry.v3",
        "device_id": "probe-node-01",
        "boot_id": boot_id,
        "seq": seq,
        "uptime_ms": seq * 1000,
        "vitals": {"heart_rate_bpm": 72.0, "spo2_pct": spo2},
        "wearable": {"wrist_surface_temp_c": 32.5},
        "motion": {"accel_g": 1.0, "gyro_dps": 1.0, "fall_state": "idle"},
        "quality": {
            "ppg": 0.95,
            "finger_present": True,
            "motion_artifact": False,
            "heart_rate_valid": True,
            "spo2_valid": True,
            "wrist_surface_temp_valid": True,
            "motion_valid": True,
        },
        "system": {
            "rssi_dbm": -52,
            "free_heap": 38_000,
            "fw": "reliability-probe",
            "faults": [],
        },
    }


def status_payload(*, boot_id: str, seq: int, online: bool) -> dict[str, Any]:
    return {
        "schema": "health.status.v1",
        "device_id": "probe-node-01",
        "boot_id": boot_id,
        "seq": seq,
        "uptime_ms": seq * 1000,
        "online": online,
        "reason": "probe_online" if online else "connection_lost",
        "system": {
            "rssi_dbm": -52,
            "free_heap": 38_000,
            "fw": "reliability-probe",
            "faults": [],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe atomic alerting and session freshness on a selected source tree."
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--implementation", choices=("baseline", "hardened"), required=True)
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--expected-source-sha256",
        help="Required scoped source SHA-256 for hardened mode.",
    )
    args = parser.parse_args(argv)
    source_root = args.source_root.resolve()
    if not (source_root / "edge" / "service.py").is_file():
        parser.error("--source-root does not contain edge/service.py")
    if not 1 <= args.repetitions <= 1000:
        parser.error("--repetitions must be between 1 and 1000")
    provenance = _source_provenance(source_root)
    if args.implementation == "baseline":
        if (
            provenance["head_commit"] != BASELINE_COMMIT
            or provenance["source_state"] != "commit_clean"
        ):
            parser.error("baseline source must be the clean pinned baseline commit")
    else:
        if not args.expected_source_sha256:
            parser.error("hardened mode requires --expected-source-sha256")
        if provenance["rq1_source_sha256"] != args.expected_source_sha256:
            parser.error("hardened source SHA-256 does not match the expected value")

    sys.path.insert(0, str(source_root))
    from edge.config import DemoRuleSettings  # noqa: PLC0415
    from edge.db import Database  # noqa: PLC0415
    from edge.rules import RuleEngine  # noqa: PLC0415
    from edge.service import InboundMessage, IngestionService  # noqa: PLC0415

    settings = DemoRuleSettings(hold_seconds=0.0, fall_recovery_seconds=0.0)

    def inbound(kind: str, payload: dict[str, Any], received: datetime) -> Any:
        return InboundMessage(
            topic=f"iot-health/v1/devices/{payload['device_id']}/{kind}",
            payload=json.dumps(payload, separators=(",", ":")).encode(),
            received_at=received,
        )

    runs: list[dict[str, Any]] = []
    for repetition in range(args.repetitions):
        with tempfile.TemporaryDirectory(prefix="nt532-reliability-") as temp_dir:
            root = Path(temp_dir)

            atomic_db = Database(root / "atomic.db")
            atomic_db.initialize()
            crashing_rules = RuleEngine(atomic_db, settings)
            atomic_service = IngestionService(atomic_db, crashing_rules)

            def crash_after_insert(*_args: Any, **_kwargs: Any) -> list[dict[str, object]]:
                raise RuntimeError("fault_injection_after_telemetry_insert")

            crashing_rules.evaluate = crash_after_insert  # type: ignore[method-assign]
            payload = telemetry_payload(boot_id="boot-atomic", seq=1)
            happened = datetime(2026, 8, 14, 0, 0, repetition, tzinfo=UTC)
            try:
                atomic_service.process_message(inbound("telemetry", payload, happened))
            except RuntimeError:
                pass

            restarted = IngestionService(atomic_db, RuleEngine(atomic_db, settings))
            retry = restarted.process_message(inbound("telemetry", payload, happened))
            telemetry_count = len(atomic_db.telemetry_history("probe-node-01"))
            alerts = atomic_db.list_alerts(device_id="probe-node-01")
            with atomic_db.connection() as connection:
                history_count = connection.execute(
                    "SELECT COUNT(*) FROM alert_history"
                ).fetchone()[0]
            atomic_pass = (
                bool(retry.accepted)
                and telemetry_count == 1
                and len(alerts) == 1
                and history_count == 1
            )

            session_db = Database(root / "session.db")
            session_db.initialize()
            session_service = IngestionService(session_db, RuleEngine(session_db, settings))
            start = datetime(2026, 8, 14, 1, 0, repetition, tzinfo=UTC)
            session_service.process_message(
                inbound("status", status_payload(boot_id="boot-a", seq=1, online=True), start)
            )
            session_service.process_message(
                inbound(
                    "telemetry",
                    telemetry_payload(boot_id="boot-b", seq=1, spo2=98.0),
                    start + timedelta(seconds=1),
                )
            )
            stale_result = session_service.process_message(
                inbound(
                    "status",
                    status_payload(boot_id="boot-a", seq=2, online=False),
                    start + timedelta(seconds=2),
                )
            )
            device = session_db.get_device("probe-node-01") or {}
            session_pass = (
                device.get("boot_id") == "boot-b"
                and device.get("online") is True
                and getattr(stale_result, "disposition", None) == "stale"
            )

            runs.append(
                {
                    "repetition": repetition + 1,
                    "atomic_alert": {
                        "pass": atomic_pass,
                        "retry_accepted": bool(retry.accepted),
                        "retry_duplicate": bool(retry.duplicate),
                        "telemetry_count": telemetry_count,
                        "alert_count": len(alerts),
                        "alert_history_count": history_count,
                    },
                    "old_lwt_session": {
                        "pass": session_pass,
                        "current_boot_id": device.get("boot_id"),
                        "online": device.get("online"),
                        "stale_disposition": getattr(stale_result, "disposition", None),
                    },
                }
            )

    output = {
        "artifact_version": "1.0",
        "implementation": args.implementation,
        "commit": provenance["head_commit"],
        "baseline_commit": BASELINE_COMMIT,
        "source_provenance": provenance,
        "repetitions": args.repetitions,
        "deterministic_repeatability_only": True,
        "inferential_confidence_interval": None,
        "cases": {
            "atomic_alert_passed": sum(run["atomic_alert"]["pass"] for run in runs),
            "old_lwt_session_passed": sum(run["old_lwt_session"]["pass"] for run in runs),
        },
        "runs": runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(output, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({"output": str(args.output), **output["cases"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
