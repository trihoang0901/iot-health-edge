from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import re
import threading
from typing import Any

from simulator.aggregate import AggregateError, validate_completed_run
from simulator.experiment import ARTIFACT_VERSION


RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
PUBLIC_ARTIFACT_VERSION = ARTIFACT_VERSION
ARTIFACT_NAMES = ("manifest.json", "summary.json", "samples.jsonl")
MAX_VALIDATION_WORKERS = 8
VALIDATION_BATCH_SIZE = 32

MANIFEST_FIELDS = {
    "artifact_version",
    "run_id",
    "status",
    "created_at",
    "completed_at",
    "profile",
    "scenario",
    "seed",
    "count",
    "interval_seconds",
    "protocol",
    "topic_namespace",
    "device_id",
    "boot_id",
    "schema",
    "commit",
    "source_provenance",
    "config_hash",
    "clock_domain",
    "polling_resolution_ms",
    "observe_timeout_seconds",
    "injection_point",
    "claims",
}

SUMMARY_FIELDS = {
    "artifact_version",
    "run_id",
    "status",
    "scheduled",
    "intentionally_dropped",
    "unique_logical_publish_attempted",
    "attempt_count",
    "published",
    "ingested",
    "api_observed",
    "delivery_ratio",
    "attempted_delivery_ratio",
    "scheduled_observation_ratio",
    "intentional_drop_ratio",
    "latency_sample_count",
    "schedule_to_api_latency_sample_count",
    "publish_to_api_upper_bound_p50_ms",
    "publish_to_api_upper_bound_p95_ms",
    "schedule_to_api_upper_bound_p50_ms",
    "schedule_to_api_upper_bound_p95_ms",
    "schedule_slip_p50_ms",
    "schedule_slip_p95_ms",
    "schedule_slip_max_ms",
    "percentiles_available",
    "minimum_percentile_samples",
    "polling_resolution_ms",
    "clock_domain",
    "injection_point",
    "network_claim",
    "error_codes",
}

PROFILE_FIELDS = {
    "name",
    "version",
    "description_vi",
    "base_delay_ms",
    "jitter_ms",
    "intentional_drop_rate",
    "outage_fraction",
    "profile_kind",
    "network_claim",
    "injection_point",
}
PROTOCOL_FIELDS = {"name", "version", "transport"}
CLAIM_FIELDS = {
    "profile_kind",
    "network_claim",
    "measured_5g",
    "primary_latency_kind",
    "diagnostic_latency_kind",
}
PUBLIC_SOURCE_FIELDS = {"scope", "source_state", "source_sha256"}


class ExperimentNotFoundError(LookupError):
    pass


class ExperimentRegistry:
    """Publish only completed v5 runs reconciled against their raw JSONL.

    The aggregate validator performs one strict read of manifest, summary and all
    samples.  We then expose an allowlisted view of those same in-memory values,
    avoiding a validate-then-reread race and never returning filesystem paths or
    the provenance file list.
    """

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)
        self._cache: dict[
            str, tuple[tuple[tuple[int, int], ...], dict[str, Any]]
        ] = {}
        self._cache_lock = threading.Lock()

    def list_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if not self.base_dir.is_dir():
            return []
        candidates: list[tuple[int, Path]] = []
        try:
            entries = list(self.base_dir.iterdir())
        except OSError:
            return []
        for item in entries:
            try:
                if (
                    item.is_symlink()
                    or not item.is_dir()
                    or not RUN_ID_RE.fullmatch(item.name)
                ):
                    continue
                candidates.append((item.stat().st_mtime_ns, item))
            except OSError:
                continue
        candidates.sort(key=lambda candidate: candidate[0], reverse=True)
        results: list[dict[str, Any]] = []
        for offset in range(0, len(candidates), VALIDATION_BATCH_SIZE):
            batch = candidates[offset : offset + VALIDATION_BATCH_SIZE]
            worker_count = min(MAX_VALIDATION_WORKERS, len(batch))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [
                    executor.submit(self.get_run, item.name) for _, item in batch
                ]
                for future in futures:
                    try:
                        results.append(future.result())
                    except (
                        ExperimentNotFoundError,
                        ValueError,
                        OSError,
                        json.JSONDecodeError,
                    ):
                        continue
                    if len(results) >= limit:
                        break
            if len(results) >= limit:
                break
        return results

    def get_run(self, run_id: str) -> dict[str, Any]:
        try:
            run_dir = self._resolve_run_dir(run_id)
            signature = self._artifact_signature(run_dir, run_id)
            with self._cache_lock:
                cached = self._cache.get(run_id)
                if cached is not None and cached[0] == signature:
                    return deepcopy(cached[1])
                self._cache.pop(run_id, None)

            validated = validate_completed_run(run_dir)
            manifest = {
                key: validated.manifest[key]
                for key in MANIFEST_FIELDS
                if key in validated.manifest
            }
            summary = {
                key: validated.summary[key]
                for key in SUMMARY_FIELDS
                if key in validated.summary
            }
            for key, fields in (
                ("profile", PROFILE_FIELDS),
                ("protocol", PROTOCOL_FIELDS),
                ("claims", CLAIM_FIELDS),
                ("source_provenance", PUBLIC_SOURCE_FIELDS),
            ):
                if isinstance(manifest.get(key), dict):
                    manifest[key] = {
                        field: manifest[key][field]
                        for field in fields
                        if field in manifest[key]
                    }
            result = {"manifest": manifest, "summary": summary}
            final_signature = self._artifact_signature(run_dir, run_id)
            if final_signature != signature:
                raise ExperimentNotFoundError(run_id)
            with self._cache_lock:
                self._cache[run_id] = (final_signature, result)
            return deepcopy(result)
        except ExperimentNotFoundError:
            with self._cache_lock:
                self._cache.pop(run_id, None)
            raise
        except (AggregateError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            with self._cache_lock:
                self._cache.pop(run_id, None)
            raise ExperimentNotFoundError(run_id) from exc

    def _resolve_run_dir(self, run_id: str) -> Path:
        if not RUN_ID_RE.fullmatch(run_id):
            raise ExperimentNotFoundError(run_id)
        root = self.base_dir.resolve()
        candidate = (root / run_id).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_dir():
            raise ExperimentNotFoundError(run_id)
        return candidate

    @staticmethod
    def _artifact_signature(
        run_dir: Path, run_id: str
    ) -> tuple[tuple[int, int], ...]:
        signature: list[tuple[int, int]] = []
        for name in ARTIFACT_NAMES:
            path = run_dir / name
            if path.is_symlink() or not path.is_file():
                raise ExperimentNotFoundError(run_id)
            stat = path.stat()
            signature.append((stat.st_mtime_ns, stat.st_size))
        return tuple(signature)
