#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build Bomana portable release assets (launcher + updatable app package)."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Dict, Optional

VARIANT_SWITCHES = {
    "Enhanced": {
        "ENABLE_CCRP": "True",
        "ENABLE_ZONES": "True",
        "ENABLE_AIRFIELDS": "True",
        "ENABLE_FUEL": "True",
        "ENABLE_CHECKLIST": "True",
        "ENABLE_ADVANCED_SETTINGS": "True",
    },
    "Standard": {
        "ENABLE_CCRP": "False",
        "ENABLE_ZONES": "True",
        "ENABLE_AIRFIELDS": "True",
        "ENABLE_FUEL": "True",
        "ENABLE_CHECKLIST": "True",
        "ENABLE_ADVANCED_SETTINGS": "True",
    },
    "Lite": {
        "ENABLE_CCRP": "False",
        "ENABLE_ZONES": "False",
        "ENABLE_AIRFIELDS": "False",
        "ENABLE_FUEL": "False",
        "ENABLE_CHECKLIST": "False",
        "ENABLE_ADVANCED_SETTINGS": "True",
    },
}

APP_ENTRY = "Bomana.pyw"
APP_DIR = "bomana"
UNIVERSAL_LAUNCHER_NAME = "Bomana_launcher"


def safe_print(msg: str) -> None:
    text = str(msg)
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        fallback = text.encode(enc, errors="backslashreplace").decode(enc, errors="replace")
        print(fallback)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variant",
        choices=sorted(VARIANT_SWITCHES.keys()),
        default="Enhanced",
        help="Build variant channel",
    )
    parser.add_argument(
        "--target",
        choices=("all", "app", "launcher"),
        default="all",
        help="Build target: all / app package only / launcher only",
    )
    parser.add_argument(
        "--version",
        default="",
        help="Override version (default: read __version__ from bomana/config.py)",
    )
    parser.add_argument(
        "--output",
        default="dist",
        help="Output directory for release assets",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def replace_switches(code: str, switches: Dict[str, str]) -> str:
    for key, value in switches.items():
        code = re.sub(rf"(?m)^{key}\s*=.*$", f"{key} = {value}", code)
    return code


def read_version(config_text: str) -> str:
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', config_text)
    if not m:
        raise RuntimeError("Failed to find __version__ in bomana/config.py")
    return m.group(1).strip()


def add_file_to_zip(zf: zipfile.ZipFile, root: Path, path: Path) -> None:
    rel = path.relative_to(root).as_posix()
    zf.write(path, rel)


def build_app_zip(root: Path, variant: str, version: str, out_dir: Path) -> Path:
    name = f"Bomana_app_{variant}_v{version}.zip"
    out_zip = out_dir / name
    if out_zip.exists():
        out_zip.unlink()

    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        add_file_to_zip(zf, root, root / APP_ENTRY)

        app_root = root / APP_DIR
        for path in app_root.rglob("*"):
            if path.is_dir():
                continue
            if "__pycache__" in path.parts:
                continue
            if path.suffix in {".pyc", ".pyo"}:
                continue
            add_file_to_zip(zf, root, path)

        for asset in ("app.png", "sponsor_wechat.png"):
            p = root / asset
            if p.exists():
                add_file_to_zip(zf, root, p)

        if variant == "Enhanced":
            ccrp_json = root / "ccrp_bomb_params.json"
            ccrp_py = root / "ccrp_bomb_params.py"
            if ccrp_json.exists():
                add_file_to_zip(zf, root, ccrp_json)
            elif ccrp_py.exists():
                add_file_to_zip(zf, root, ccrp_py)

    return out_zip


def build_launcher(root: Path, version: str, out_dir: Path) -> Path:
    name = f"{UNIVERSAL_LAUNCHER_NAME}_v{version}"
    work_dir = root / "build" / "pyinstaller" / "UniversalLauncher"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconsole",
        "--onefile",
        "--name",
        name,
        "--icon",
        str(root / "app.ico"),
        "--hidden-import",
        "pystray._win32",
        "--collect-submodules",
        "PIL",
        "--collect-submodules",
        "pystray",
        "--collect-all",
        "requests",
        "--distpath",
        str(out_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(work_dir),
        "--clean",
    ]

    # Launcher runtime resources (window icon + details dialog assets)
    icon_file = root / "app.ico"
    if icon_file.exists():
        cmd.extend(["--add-data", f"{icon_file};."])
    sponsor_file = root / "sponsor_wechat.png"
    if sponsor_file.exists():
        cmd.extend(["--add-data", f"{sponsor_file};."])

    cmd.append(str(root / "launcher.pyw"))
    subprocess.run(cmd, check=True, cwd=root)
    return out_dir / f"{name}.exe"


def write_manifest(out_dir: Path, variant: str, version: str, app_zip_name: str, app_sha256: str) -> Path:
    manifest = {
        "schema_version": 1,
        "channel": variant,
        "app_version": version,
        "entrypoint": APP_ENTRY,
        "package_asset": app_zip_name,
        "package_sha256": app_sha256,
    }
    path = out_dir / f"manifest_{variant}.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_checksum_info(
    out_dir: Path,
    variant: str,
    version: str,
    app_zip: Optional[Path],
    launcher: Optional[Path],
    target: str,
) -> Path:
    lines = [
        "Bomana Portable Build",
        "====================",
        "",
        f"variant: {variant}",
        f"version: {version}",
        f"target:  {target}",
        "",
    ]
    if app_zip and app_zip.exists():
        lines.append(f"{app_zip.name}  SHA256  {sha256_file(app_zip)}")
    if launcher and launcher.exists():
        lines.append(f"{launcher.name}  SHA256  {sha256_file(launcher)}")
    lines.append("")
    if target == "launcher":
        path = out_dir / "checksums_launcher.txt"
    elif target == "app":
        path = out_dir / f"checksums_app_{variant}.txt"
    else:
        path = out_dir / f"checksums_portable_{variant}.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    out_dir = (root / args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    config_path = root / "bomana" / "config.py"
    original = config_path.read_text(encoding="utf-8")

    app_zip: Optional[Path] = None
    manifest: Optional[Path] = None
    launcher: Optional[Path] = None

    try:
        version = args.version.strip() or read_version(original)

        if args.target in ("all", "app"):
            patched = replace_switches(original, VARIANT_SWITCHES[args.variant])
            config_path.write_text(patched, encoding="utf-8")
            version = args.version.strip() or read_version(patched)
            app_zip = build_app_zip(root, args.variant, version, out_dir)
            app_sha = sha256_file(app_zip)
            manifest = write_manifest(out_dir, args.variant, version, app_zip.name, app_sha)

        if args.target in ("all", "launcher"):
            launcher = build_launcher(root, version, out_dir)

        checksum_variant = "Universal" if args.target == "launcher" else args.variant
        checksum = write_checksum_info(out_dir, checksum_variant, version, app_zip, launcher, args.target)

        safe_print(f"[OK] variant={checksum_variant} version={version} target={args.target}")
        if app_zip and app_zip.exists():
            safe_print(f"  - app package: {app_zip}")
        if manifest and manifest.exists():
            safe_print(f"  - manifest:    {manifest}")
        if launcher and launcher.exists():
            safe_print(f"  - launcher:    {launcher}")
        safe_print(f"  - checksum:    {checksum}")
        return 0
    finally:
        config_path.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
