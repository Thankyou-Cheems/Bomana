# enforces: docs/specs/weapon-fire-control.md WFC-21

"""Hard boundary for the production offline ballistic prediction path."""

from __future__ import annotations

import ast
from pathlib import Path

PREDICTION_MODULES = (
    Path("bomana/core/offline_ballistics_model.py"),
    Path("bomana/core/offline_rigidbody_solver.py"),
    Path("bomana/core/ballistics.py"),
    Path("bomana/core/telemetry.py"),
    Path("bomana/core/release_state.py"),
    Path("bomana/core/release_observation.py"),
    Path("bomana/core/ccrp_scheduler.py"),
    Path("bomana/core/logic.py"),
    Path("bomana/core/atmosphere.py"),
    Path("bomana/core/terrain_elevation.py"),
)
FORBIDDEN_RUNTIME_TOKENS = (
    "ReadProcessMemory",
    "OpenProcess",
    "PROCESS_VM_READ",
    "VirtualQueryEx",
    "NtReadVirtualMemory",
    "CreateToolhelp32Snapshot",
    "probe_war_thunder",
    "tools.research",
    "aces.exe",
)
FORBIDDEN_IMPORT_ROOTS = {
    "ctypes",
    "pymem",
    "psutil",
    "win32api",
    "win32process",
}


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_prediction_dependency_set_has_no_live_process_reader() -> None:
    for path in PREDICTION_MODULES:
        source = path.read_text(encoding="utf-8")
        imports = _import_roots(path)
        assert imports.isdisjoint(FORBIDDEN_IMPORT_ROOTS), path
        for token in FORBIDDEN_RUNTIME_TOKENS:
            assert token not in source, f"{path} contains forbidden runtime token {token}"


def test_old_empirical_model_is_absent_from_production_package() -> None:
    assert not Path("bomana/core/bomb_trajectory_model.py").exists()
    production_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("bomana").rglob("*.py")
    )
    assert "generic_freefall_ccip_v2" not in production_sources
    assert "FREEFALL_DRAG_COEFFICIENT_MULT" not in production_sources
    assert "trajectory_drag_coefficient_mult" not in production_sources
