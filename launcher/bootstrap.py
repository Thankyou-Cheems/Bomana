"""Application bootstrap helpers for the portable launcher."""

from __future__ import annotations

import importlib
import os
import runpy
import sys
from pathlib import Path
from typing import Any


def source_site_packages(base: Path) -> tuple[Path, ...]:
    venv_dir = base / ".venv"
    version_tag = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates = (
        venv_dir / "Lib" / "site-packages",
        venv_dir / "lib" / version_tag / "site-packages",
        venv_dir / "lib" / "site-packages",
    )
    return tuple(path for path in candidates if path.exists())


def prepare_source_test_runtime(base: Path) -> None:
    for site_packages in reversed(source_site_packages(base)):
        site_text = str(site_packages)
        if site_text not in sys.path:
            sys.path.insert(0, site_text)


def reset_embedded_app_modules() -> None:
    """Clear launcher-bundled bomana modules before handing off to the app package."""

    stale_modules = [
        name for name in tuple(sys.modules.keys()) if name == "bomana" or name.startswith("bomana.")
    ]
    for name in stale_modules:
        sys.modules.pop(name, None)
    importlib.invalidate_caches()


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except Exception:
        return False
    return True


def spec_points_within(spec: Any, root: Path) -> bool:
    locations: list[Path] = []
    origin = getattr(spec, "origin", None)
    if origin and origin not in ("built-in", "frozen", "namespace"):
        locations.append(Path(str(origin)))
    search_locations = getattr(spec, "submodule_search_locations", None)
    if search_locations:
        locations.extend(Path(str(location)) for location in search_locations)
    return any(path_is_within(location, root) for location in locations)


class AppPackageBomanaFinder:
    """Prefer installed app-package bomana modules over PyInstaller's frozen importer."""

    def __init__(self, app_dir: Path) -> None:
        self.app_dir = app_dir.resolve()

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        if fullname != "bomana" and not fullname.startswith("bomana."):
            return None
        search_path = [str(self.app_dir)] if fullname == "bomana" else path
        if search_path is None:
            search_dir = self.app_dir / "bomana"
            for part in fullname.split(".")[1:-1]:
                search_dir /= part
            search_path = [str(search_dir)]
        spec = importlib.machinery.PathFinder.find_spec(fullname, search_path)
        if spec is None or not spec_points_within(spec, self.app_dir):
            return None
        return spec


def launch_app(
    base: Path,
    channel: str,
    *,
    recover_incomplete_install,
    app_runtime_dir,
    is_local_app_ready,
    is_source_test_run,
    default_entrypoint: str,
) -> None:
    recover_incomplete_install(base)
    app_dir = app_runtime_dir(base)
    entry = app_dir / default_entrypoint
    if not is_local_app_ready(base):
        raise RuntimeError("本地应用不存在，请联网后重试。")

    if is_source_test_run(base):
        prepare_source_test_runtime(base)
    reset_embedded_app_modules()
    os.environ["BOMANA_CHANNEL"] = channel
    os.environ["BOMANA_RUNTIME_ROOT"] = str(app_dir)
    os.chdir(app_dir)
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    finder = AppPackageBomanaFinder(app_dir)
    sys.meta_path.insert(0, finder)
    try:
        runpy.run_path(str(entry), run_name="__main__")
    finally:
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)
