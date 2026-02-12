# -*- coding: utf-8 -*-
"""WinUI runtime host: launch frontend exe and inject snapshot bridge URL."""

import os
import subprocess
from pathlib import Path
from typing import Optional

from bomana.ui.winui_bridge import WinUISnapshotBridge

# Default WinUI frontend locations inside app package.
_WINUI_EXE_CANDIDATES = (
    Path("winui/dist/Bomana.WinUI3.exe"),
    Path("winui/Bomana.WinUI3.exe"),
    Path("Bomana.WinUI3.exe"),
)


def _resolve_frontend_exe(base_dir: Path) -> Path:
    """Resolve WinUI frontend executable path."""
    override = os.environ.get("BOMANA_WINUI_EXE", "").strip()
    candidates = []

    if override:
        override_path = Path(override)
        if not override_path.is_absolute():
            override_path = (base_dir / override_path).resolve()
        candidates.append(override_path)

    for rel in _WINUI_EXE_CANDIDATES:
        candidates.append((base_dir / rel).resolve())

    # Dev build output candidates (prefer latest built executable).
    project_bin = (base_dir / "winui" / "Bomana.WinUI3" / "bin").resolve()
    if project_bin.exists():
        globbed = sorted(
            project_bin.rglob("Bomana.WinUI3.exe"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        candidates.extend(globbed)

    for path in candidates:
        if path.exists():
            return path

    hint = "\n".join(f"- {p}" for p in candidates)
    raise FileNotFoundError(
        "WinUI3 frontend executable not found. Checked:\n"
        f"{hint}\n"
        "Set BOMANA_WINUI_EXE to override the path."
    )


def run_winui_runtime(base_dir: Optional[Path] = None) -> int:
    """Run WinUI frontend process with local snapshot bridge.

    Returns:
        Frontend process exit code.
    """
    if base_dir is None:
        base_dir = Path(__file__).resolve().parents[2]
    base_dir = base_dir.resolve()
    frontend_exe = _resolve_frontend_exe(base_dir)

    bridge = WinUISnapshotBridge(host="127.0.0.1", port=0)
    bridge.start()

    env = os.environ.copy()
    env["BOMANA_SNAPSHOT_API_URL"] = f"{bridge.base_url}/snapshot"
    env["BOMANA_SNAPSHOT_HEALTH_URL"] = f"{bridge.base_url}/health"
    env["BOMANA_UI_BRIDGE_HOST"] = bridge.host
    env["BOMANA_UI_BRIDGE_PORT"] = str(bridge.port)

    try:
        proc = subprocess.Popen(
            [str(frontend_exe)],
            cwd=str(frontend_exe.parent),
            env=env,
        )
        return int(proc.wait())
    finally:
        bridge.stop()


def has_winui_frontend(base_dir: Optional[Path] = None) -> bool:
    """Check whether a runnable WinUI frontend executable is available."""
    if base_dir is None:
        base_dir = Path(__file__).resolve().parents[2]
    base_dir = base_dir.resolve()
    try:
        _resolve_frontend_exe(base_dir)
        return True
    except Exception:
        return False
