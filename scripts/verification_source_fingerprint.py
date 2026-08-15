from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    ".gitattributes",
    ".dockerignore",
    ".env.example",
    ".gitignore",
    "README.md",
    "START-IOT-HEALTH-EDGE.bat",
    "package.json",
    "pnpm-lock.yaml",
    "pyproject.toml",
)
ROOT_DIRS = (
    "deploy",
    "edge",
    "firmware/health-node",
    "scripts",
    "simulator",
    "tests",
)
SKIP_PARTS = {
    ".pio",
    ".pio-core",
    "__pycache__",
    "generated",
    "node_modules",
}
SKIP_NAMES = {".env", "desktop.ini", "secrets.h"}
STABLE_IDENTITY_FIELDS = ("scope", "source_sha256", "source_files")
WINDOWS_REPARSE_POINT = 0x0400


def is_link_or_reparse(path: Path) -> bool:
    """Detect symlinks and Windows junction/reparse points without following them."""

    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & WINDOWS_REPARSE_POINT
    )


def ensure_safe_path(path: Path, root: Path) -> None:
    """Require an existing path and all its ancestors to stay inside real root."""

    root_absolute = Path(os.path.abspath(root))
    path_absolute = Path(os.path.abspath(path))
    try:
        relative = path_absolute.relative_to(root_absolute)
    except ValueError as exc:
        raise ValueError(f"path escapes verification root: {path}") from exc
    current = root_absolute
    if is_link_or_reparse(current):
        raise ValueError(f"symlink or reparse root forbidden: {root}")
    for part in relative.parts:
        current /= part
        if is_link_or_reparse(current):
            raise ValueError(f"symlink or reparse input forbidden: {relative.as_posix()}")
    try:
        resolved_root = root_absolute.resolve(strict=True)
        resolved_path = path_absolute.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"missing verification input: {relative.as_posix()}") from exc
    if not resolved_path.is_relative_to(resolved_root):
        raise ValueError(f"resolved path escapes verification root: {relative.as_posix()}")


def verification_files() -> list[str]:
    files: set[str] = set()
    for relative in ROOT_FILES:
        path = ROOT / relative
        if not path.exists() and not path.is_symlink():
            raise FileNotFoundError(f"missing verification input: {relative}")
        ensure_safe_path(path, ROOT)
        if not path.is_file():
            raise FileNotFoundError(f"missing verification input: {relative}")
        files.add(relative)
    for directory in ROOT_DIRS:
        base = ROOT / directory
        if not base.exists() and not base.is_symlink():
            raise FileNotFoundError(f"missing verification input directory: {directory}")
        ensure_safe_path(base, ROOT)
        if not base.is_dir():
            raise FileNotFoundError(f"missing verification input directory: {directory}")
        for path in base.rglob("*"):
            relative = path.relative_to(ROOT)
            if any(part in SKIP_PARTS for part in relative.parts):
                continue
            if path.name.casefold() in SKIP_NAMES:
                continue
            ensure_safe_path(path, ROOT)
            if path.is_file():
                files.add(relative.as_posix())
    return sorted(files)


def git_value(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def stable_content_identity(provenance: Mapping[str, object]) -> dict[str, object]:
    """Return the content identity that remains valid across evidence commits."""

    return {field: provenance.get(field) for field in STABLE_IDENTITY_FIELDS}


def build_fingerprint() -> dict[str, object]:
    files = verification_files()
    digest = sha256()
    for relative in files:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update((ROOT / relative).read_bytes())
        digest.update(b"\0")
    status = git_value(["status", "--porcelain", "--", *files])
    return {
        "scope": "verification_inputs_v1",
        "head_commit": git_value(["rev-parse", "HEAD"]) or "unknown",
        "source_state": (
            "unknown"
            if status is None
            else "worktree_uncommitted"
            if status
            else "commit_clean"
        ),
        "source_sha256": digest.hexdigest(),
        "source_files": files,
    }


def main() -> int:
    payload = build_fingerprint()
    print(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
