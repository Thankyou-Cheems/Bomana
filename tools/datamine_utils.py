"""Shared helpers for Bomana datamine extraction tools."""

from __future__ import annotations

import subprocess
from pathlib import Path

BOMBGUNS_SUBDIR = Path("aces.vromfs.bin_u") / "gamedata" / "weapons" / "bombguns"
FLIGHTMODELS_SUBDIR = Path("aces.vromfs.bin_u") / "gamedata" / "flightmodels"
_GIT_COMMAND_ERRORS = (OSError, subprocess.SubprocessError)


def require_datamine_dir(root: Path, relative_dir: Path) -> Path:
    """Return a required datamine directory or raise a clear error."""
    directory = root / relative_dir
    if not directory.exists():
        raise FileNotFoundError(f"missing directory: {directory}")
    return directory


def read_datamine_version(root: Path) -> str:
    """Read the datamine repo's game version marker when available."""
    version_path = root / "version"
    try:
        return version_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def read_git_commit(root: Path) -> str:
    """Return the current git commit for a datamine checkout when available."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except _GIT_COMMAND_ERRORS:
        return ""

    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def build_source_metadata(root: Path, relative_dir: Path) -> dict[str, str]:
    """Build reproducible source metadata for generated static JSON."""
    return {
        "source_root_name": root.name,
        "source_subdir": relative_dir.as_posix(),
        "source_version": read_datamine_version(root),
        "source_commit": read_git_commit(root),
    }
