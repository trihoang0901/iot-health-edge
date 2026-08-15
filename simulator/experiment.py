from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen
import uuid

from .mqtt_simulator import (
    DEVICE_ID_RE,
    SCENARIOS,
    MqttPublisher,
    RuntimeConfig,
    ScenarioStream,
)
from .network_profiles import PROFILES, build_schedule, get_profile


ARTIFACT_VERSION = "5.0"
MIN_PERCENTILE_SAMPLES = 20
MAX_API_RESPONSE_BYTES = 2 * 1024 * 1024
SOURCE_FINGERPRINT_SCOPE = "runner_source_fingerprint"
RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SOURCE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    "pyproject.toml",
    "edge/app.py",
    "edge/config.py",
    "edge/db.py",
    "edge/experiments.py",
    "edge/mqtt_client.py",
    "edge/rules.py",
    "edge/schemas.py",
    "edge/service.py",
    "simulator/experiment.py",
    "simulator/aggregate.py",
    "simulator/mqtt_simulator.py",
    "simulator/network_profiles.py",
)


@dataclass(frozen=True, slots=True)
class PollObservation:
    observed: bool
    error_code: str | None
    infrastructure_error: bool = False


def utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def percentile(values: list[float], percentile_value: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile_value
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def summarize_samples(
    run_id: str,
    samples: list[dict[str, Any]],
    *,
    status: str,
    polling_resolution_ms: int,
) -> dict[str, Any]:
    telemetry = [sample for sample in samples if sample.get("stream") == "telemetry"]
    publish_attempted = [sample for sample in telemetry if sample.get("publish_attempted")]
    unique_attempted = {
        (
            sample["device_id"],
            sample["boot_id"],
            sample["stream"],
            sample["seq"],
        )
        for sample in publish_attempted
    }
    observed = [sample for sample in telemetry if sample.get("api_observed")]
    unique_observed = {
        (
            sample["device_id"],
            sample["boot_id"],
            sample["stream"],
            sample["seq"],
        )
        for sample in observed
    }
    publish_latencies = [
        float(sample["publish_to_api_upper_bound_ms"])
        for sample in observed
        if isinstance(sample.get("publish_to_api_upper_bound_ms"), (int, float))
    ]
    schedule_latencies = [
        float(sample["schedule_to_api_upper_bound_ms"])
        for sample in observed
        if isinstance(sample.get("schedule_to_api_upper_bound_ms"), (int, float))
    ]
    schedule_slips = [
        float(sample["schedule_slip_ms"])
        for sample in telemetry
        if isinstance(sample.get("schedule_slip_ms"), (int, float))
    ]
    percentiles_available = (
        len(publish_latencies) >= MIN_PERCENTILE_SAMPLES
        and len(schedule_latencies) >= MIN_PERCENTILE_SAMPLES
    )
    error_codes = sorted(
        {
            str(sample["error_code"])
            for sample in samples
            if sample.get("error_code")
        }
    )
    attempted_delivery_ratio = (
        round(len(unique_observed & unique_attempted) / len(unique_attempted), 6)
        if unique_attempted
        else None
    )
    scheduled_observation_ratio = (
        None
        if status == "planned"
        else round(len(unique_observed) / len(telemetry), 6)
        if telemetry
        else None
    )
    intentional_drop_count = sum(
        bool(sample.get("intentionally_dropped")) for sample in telemetry
    )
    return {
        "artifact_version": ARTIFACT_VERSION,
        "run_id": run_id,
        "status": status,
        "scheduled": len(telemetry),
        "intentionally_dropped": intentional_drop_count,
        "unique_logical_publish_attempted": len(unique_attempted),
        "attempt_count": sum(int(sample.get("attempt_count", 0)) for sample in telemetry),
        "published": sum(bool(sample.get("published")) for sample in telemetry),
        "ingested": sum(bool(sample.get("ingested")) for sample in telemetry),
        "api_observed": len(unique_observed),
        "attempted_delivery_ratio": attempted_delivery_ratio,
        # Compatibility alias retained for existing API/dashboard consumers.
        "delivery_ratio": attempted_delivery_ratio,
        "scheduled_observation_ratio": scheduled_observation_ratio,
        "intentional_drop_ratio": (
            round(intentional_drop_count / len(telemetry), 6) if telemetry else None
        ),
        "latency_sample_count": len(publish_latencies),
        "schedule_to_api_latency_sample_count": len(schedule_latencies),
        "publish_to_api_upper_bound_p50_ms": (
            round(percentile(publish_latencies, 0.50), 3)
            if percentiles_available
            else None
        ),
        "publish_to_api_upper_bound_p95_ms": (
            round(percentile(publish_latencies, 0.95), 3)
            if percentiles_available
            else None
        ),
        "schedule_to_api_upper_bound_p50_ms": (
            round(percentile(schedule_latencies, 0.50), 3)
            if percentiles_available
            else None
        ),
        "schedule_to_api_upper_bound_p95_ms": (
            round(percentile(schedule_latencies, 0.95), 3)
            if percentiles_available
            else None
        ),
        "schedule_slip_p50_ms": (
            round(percentile(schedule_slips, 0.50), 3) if schedule_slips else None
        ),
        "schedule_slip_p95_ms": (
            round(percentile(schedule_slips, 0.95), 3) if schedule_slips else None
        ),
        "schedule_slip_max_ms": round(max(schedule_slips), 3) if schedule_slips else None,
        "percentiles_available": percentiles_available,
        "minimum_percentile_samples": MIN_PERCENTILE_SAMPLES,
        "polling_resolution_ms": polling_resolution_ms,
        "clock_domain": "host_monotonic_same_process",
        "injection_point": "before_mqtt_publish",
        "network_claim": "none",
        "error_codes": error_codes,
    }


def _git_commit(source_root: Path = SOURCE_ROOT) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
        value = result.stdout.strip()
        return value if re.fullmatch(r"[0-9a-f]{40}", value) else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def source_provenance(source_root: Path = SOURCE_ROOT) -> dict[str, Any]:
    digest = sha256()
    for relative in SOURCE_FILES:
        path = source_root / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")

    source_state = "unknown"
    try:
        result = subprocess.run(
            ["git", "-C", str(source_root), "status", "--porcelain", "--", *SOURCE_FILES],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
        source_state = "worktree_uncommitted" if result.stdout.strip() else "commit_clean"
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "scope": SOURCE_FINGERPRINT_SCOPE,
        "head_commit": _git_commit(source_root),
        "source_state": source_state,
        "source_sha256": digest.hexdigest(),
        "source_files": list(SOURCE_FILES),
    }


def config_material(
    *,
    profile: Any,
    scenario: str,
    count: int,
    seed: int,
    interval_seconds: float,
    device_id: str,
    polling_resolution_ms: int,
    observe_timeout_seconds: float,
) -> dict[str, Any]:
    return {
        "profile": profile.public_dict(),
        "scenario": scenario,
        "count": count,
        "seed": seed,
        "interval_seconds": interval_seconds,
        "device_id": device_id,
        "schema": "health.telemetry.v3",
        "polling_resolution_ms": polling_resolution_ms,
        "observe_timeout_seconds": observe_timeout_seconds,
    }


def config_digest(material: dict[str, Any]) -> str:
    return sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write(
        path,
        (json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode(
            "utf-8"
        ),
    )


def _write_samples(path: Path, samples: list[dict[str, Any]]) -> None:
    _atomic_write(
        path,
        "".join(
            json.dumps(sample, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            + "\n"
            for sample in samples
        ).encode("utf-8"),
    )


def _poll_observed(
    api_base: str,
    *,
    device_id: str,
    boot_id: str,
    seq: int,
    timeout_seconds: float,
    polling_resolution_ms: int,
) -> PollObservation:
    endpoint = (
        f"{api_base.rstrip('/')}/api/v1/devices/{quote(device_id, safe='')}/telemetry"
        "?limit=1000"
    )
    deadline = time.monotonic() + timeout_seconds
    successful_poll = False
    terminal_poll_healthy = False
    while time.monotonic() < deadline:
        try:
            with urlopen(endpoint, timeout=min(2.0, timeout_seconds)) as response:  # noqa: S310
                body = _read_json_response(response)
            if not isinstance(body, dict) or not isinstance(body.get("data"), list):
                return PollObservation(False, "api_infrastructure_unavailable", True)
            successful_poll = True
            terminal_poll_healthy = True
            if any(
                item.get("boot_id") == boot_id and item.get("seq") == seq
                for item in body.get("data", [])
            ):
                return PollObservation(True, None)
        except HTTPError as exc:
            if exc.code == 404:
                successful_poll = True
                terminal_poll_healthy = True
                time.sleep(polling_resolution_ms / 1000)
                continue
            if exc.code == 503:
                return PollObservation(False, "api_infrastructure_unavailable", True)
            return PollObservation(False, "api_infrastructure_unavailable", True)
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            # A previous healthy response is not enough to prove the API stayed
            # available until this observation window closed.  A later
            # transport failure must be recovered by another valid poll.
            terminal_poll_healthy = False
        time.sleep(polling_resolution_ms / 1000)
    if not successful_poll or not terminal_poll_healthy:
        return PollObservation(False, "api_infrastructure_unavailable", True)
    return PollObservation(False, "api_observation_timeout")


def _read_json_response(response: Any) -> dict[str, Any]:
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_API_RESPONSE_BYTES:
                raise ValueError("api_response_too_large")
        except ValueError as exc:
            raise ValueError("api_response_size_invalid") from exc
    raw = response.read(MAX_API_RESPONSE_BYTES + 1)
    if len(raw) > MAX_API_RESPONSE_BYTES:
        raise ValueError("api_response_too_large")
    body = json.loads(raw.decode("utf-8", errors="strict"))
    if not isinstance(body, dict):
        raise ValueError("api_response_not_object")
    return body


def _require_api_ready(api_base: str) -> None:
    endpoint = f"{api_base.rstrip('/')}/healthz"
    try:
        with urlopen(endpoint, timeout=3.0) as response:  # noqa: S310
            body = _read_json_response(response)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("edge_api_unavailable") from exc
    if body.get("status") != "ok":
        raise RuntimeError("edge_api_not_ready")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Chạy thí nghiệm MQTT một node với app impairment tái lập; "
            "không phải phép đo packet loss hoặc 5G."
        )
    )
    parser.add_argument("--profile", choices=tuple(PROFILES), default="lan-baseline")
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--device-id", default=os.getenv("DEVICE_ID", "health-node-01"))
    parser.add_argument("--broker", default=os.getenv("MQTT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MQTT_PORT", "1883")))
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--observe-timeout", type=float, default=5.0)
    parser.add_argument("--polling-resolution-ms", type=int, default=100)
    parser.add_argument("--output-dir", type=Path, default=Path("evidence/runs"))
    parser.add_argument("--run-id")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 10_000:
        parser.error("--count phai trong khoang 1..10000")
    if not 0 < args.interval <= 60:
        parser.error("--interval phai lon hon 0 va khong qua 60 giay")
    if not DEVICE_ID_RE.fullmatch(args.device_id):
        parser.error("--device-id khong hop le")
    if not 1 <= args.port <= 65_535:
        parser.error("--port phai trong khoang 1..65535")
    if not 0 < args.observe_timeout <= 60:
        parser.error("--observe-timeout phai lon hon 0 va khong qua 60 giay")
    if not 20 <= args.polling_resolution_ms <= 5_000:
        parser.error("--polling-resolution-ms phai trong khoang 20..5000")
    if args.run_id is not None and not RUN_ID_RE.fullmatch(args.run_id):
        parser.error("--run-id phai khop ^[a-z0-9][a-z0-9._-]{0,63}$")
    if not args.dry_run and (
        not os.getenv("SIMULATOR_MQTT_USERNAME")
        or not os.getenv("SIMULATOR_MQTT_PASSWORD")
    ):
        parser.error(
            "can SIMULATOR_MQTT_USERNAME va SIMULATOR_MQTT_PASSWORD khi chay measured"
        )
    return args


def run_experiment(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    run_id = args.run_id or (
        f"run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-"
        f"{args.profile}-{uuid.uuid4().hex[:6]}"
    )
    profile = get_profile(args.profile)
    schedule = build_schedule(profile, count=args.count, seed=args.seed)
    run_dir = args.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    material = config_material(
        profile=profile,
        scenario=args.scenario,
        count=args.count,
        seed=args.seed,
        interval_seconds=args.interval,
        device_id=args.device_id,
        polling_resolution_ms=args.polling_resolution_ms,
        observe_timeout_seconds=args.observe_timeout,
    )
    config_hash = config_digest(material)
    runtime = RuntimeConfig(
        broker=args.broker,
        port=args.port,
        username=os.getenv("SIMULATOR_MQTT_USERNAME"),
        password=os.getenv("SIMULATOR_MQTT_PASSWORD"),
        device_id=args.device_id,
        scenario=args.scenario,
        interval=args.interval,
        count=args.count,
        seed=args.seed,
        tls=False,
        ca_cert=None,
        connect_timeout=10.0,
        dry_run=args.dry_run,
    )
    stream = ScenarioStream(runtime)
    # A measured run needs a fresh identity so API polling cannot match telemetry
    # left by an earlier execution that reused the same human-readable run ID.
    # Dry-run identity remains deterministic because it never publishes.
    stream.boot_id = (
        uuid.uuid5(uuid.NAMESPACE_URL, f"{run_id}:{args.seed}").hex
        if args.dry_run
        else uuid.uuid4().hex
    )

    provenance = source_provenance()
    manifest = {
        "artifact_version": ARTIFACT_VERSION,
        "run_id": run_id,
        "status": "planned" if args.dry_run else "running",
        "created_at": utc_iso(),
        "completed_at": None,
        "profile": profile.public_dict(),
        "scenario": args.scenario,
        "seed": args.seed,
        "count": args.count,
        "interval_seconds": args.interval,
        "protocol": {"name": "MQTT", "version": "3.1.1", "transport": "TCP"},
        "topic_namespace": "iot-health/v1/devices/{device_id}/{stream}",
        "device_id": args.device_id,
        "boot_id": stream.boot_id,
        "schema": "health.telemetry.v3",
        "commit": provenance["head_commit"],
        "source_provenance": provenance,
        "config_hash": config_hash,
        "clock_domain": "host_monotonic_same_process",
        "polling_resolution_ms": args.polling_resolution_ms,
        "observe_timeout_seconds": args.observe_timeout,
        "injection_point": profile.injection_point,
        "claims": {
            "profile_kind": profile.profile_kind,
            "network_claim": profile.network_claim,
            "measured_5g": False,
            "primary_latency_kind": "schedule_to_api_polling_upper_bound",
            "diagnostic_latency_kind": "publish_to_api_polling_upper_bound",
        },
    }
    _write_json(run_dir / "manifest.json", manifest)

    samples: list[dict[str, Any]] = []
    publisher: MqttPublisher | None = None
    status = "planned" if args.dry_run else "running"
    try:
        if not args.dry_run:
            _require_api_ready(args.api_base)
            publisher = MqttPublisher(replace(runtime, dry_run=False), stream)
            publisher.connect()
            publisher.publish(stream.status(True, "experiment_started"))

        run_started = time.monotonic()
        for scheduled in schedule:
            scheduled_offset_ms = round(scheduled.index * args.interval * 1000, 3)
            slot_due = run_started + (scheduled.index * args.interval)
            wait_for_slot = slot_due - time.monotonic()
            while not args.dry_run and wait_for_slot > 0:
                time.sleep(wait_for_slot)
                wait_for_slot = slot_due - time.monotonic()
            slot_started = time.monotonic()
            schedule_slip_ms = (
                0.0
                if args.dry_run
                else round(max(0.0, slot_started - slot_due) * 1000, 3)
            )
            # Payload generation is part of the scheduled observation path.  Do
            # it only after the absolute slot boundary so schedule->API captures
            # runner work as well as impairment, publish, ingestion and polling.
            message = stream.telemetry(args.scenario, scheduled.index, args.count)
            sample: dict[str, Any] = {
                "artifact_version": ARTIFACT_VERSION,
                "run_id": run_id,
                "device_id": args.device_id,
                "boot_id": stream.boot_id,
                "stream": "telemetry",
                "seq": message.payload["seq"],
                "scheduled_index": scheduled.index,
                "scheduled": True,
                "scheduled_delay_ms": scheduled.delay_ms,
                "scheduled_offset_ms": scheduled_offset_ms,
                "schedule_slip_ms": schedule_slip_ms,
                "slot_to_publish_ms": None,
                "intentionally_dropped": scheduled.intentionally_dropped,
                "drop_reason": scheduled.drop_reason,
                "publish_attempted": False,
                "attempt_count": 0,
                "published": False,
                "ingested": False,
                "api_observed": False,
                "publish_to_api_upper_bound_ms": None,
                "schedule_to_api_upper_bound_ms": None,
                "polling_error_bound_ms": args.polling_resolution_ms,
                "error_code": None,
            }
            if not args.dry_run:
                time.sleep(scheduled.delay_ms / 1000)
            if args.dry_run or scheduled.intentionally_dropped:
                samples.append(sample)
                continue

            publish_started = time.monotonic()
            sample["slot_to_publish_ms"] = round(
                (publish_started - slot_due) * 1000, 3
            )
            sample["publish_attempted"] = True
            sample["attempt_count"] = 1
            try:
                publisher.publish(message)  # type: ignore[union-attr]
                sample["published"] = True
                observation = _poll_observed(
                    args.api_base,
                    device_id=args.device_id,
                    boot_id=stream.boot_id,
                    seq=int(message.payload["seq"]),
                    timeout_seconds=args.observe_timeout,
                    polling_resolution_ms=args.polling_resolution_ms,
                )
                sample["ingested"] = observation.observed
                sample["api_observed"] = observation.observed
                sample["error_code"] = observation.error_code
                if observation.observed:
                    observed_at = time.monotonic()
                    sample["publish_to_api_upper_bound_ms"] = round(
                        (observed_at - publish_started) * 1000, 3
                    )
                    sample["schedule_to_api_upper_bound_ms"] = round(
                        (observed_at - slot_due) * 1000, 3
                    )
                elif observation.infrastructure_error:
                    status = "partial"
            except (OSError, RuntimeError, ValueError):
                sample["error_code"] = "mqtt_publish_failed"
                status = "partial"
            samples.append(sample)
            if status == "partial" and sample["error_code"] == "api_infrastructure_unavailable":
                break
        if not args.dry_run and status == "running":
            status = "completed"
    except (OSError, RuntimeError, ValueError):
        status = "failed"
    finally:
        if publisher is not None:
            if publisher.is_connected:
                try:
                    publisher.publish(stream.status(False, "experiment_complete"))
                except Exception:
                    pass
            try:
                publisher.close()
            except Exception:
                pass

    manifest["status"] = status
    manifest["completed_at"] = utc_iso()
    summary = summarize_samples(
        run_id,
        samples,
        status=status,
        polling_resolution_ms=args.polling_resolution_ms,
    )
    _write_samples(run_dir / "samples.jsonl", samples)
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "manifest.json", manifest)
    return run_dir, summary


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run_dir, summary = run_experiment(args)
    except (OSError, ValueError) as exc:
        print(f"Experiment failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "run_id": summary["run_id"],
                "status": summary["status"],
                "artifact_dir": str(run_dir),
                "network_claim": "none",
            },
            ensure_ascii=False,
        )
    )
    return 0 if summary["status"] in {"planned", "completed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
