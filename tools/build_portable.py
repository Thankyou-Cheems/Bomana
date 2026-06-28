#!/usr/bin/env python3
"""Build Bomana portable release assets (launcher + updatable app package)."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from bomana.launcher_core import (
    RELEASE_MANIFEST_DEFAULT_KEY_ID,
    ed25519_public_key_from_private_key,
    sign_release_manifest,
)

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
BRANDING_ICON = Path(APP_DIR) / "assets" / "branding" / "app.ico"
SIGNING_PRIVATE_KEY_ENV = "BOMANA_RELEASE_ED25519_PRIVATE_KEY"
SIGNING_PUBLIC_KEY_ENV = "BOMANA_RELEASE_ED25519_PUBLIC_KEY"
SIGNING_KEY_ID_ENV = "BOMANA_RELEASE_SIGNING_KEY_ID"


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
        help=(
            "Expected version; fails if it does not match the source metadata "
            "(app: bomana/metadata.py, launcher: launcher.pyw)"
        ),
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


def sign_manifest(manifest: dict[str, object]) -> dict[str, object]:
    private_key, key_id = release_signing_key_context()
    return sign_release_manifest(manifest, private_key, key_id=key_id)


def release_signing_key_context() -> tuple[str, str]:
    private_key = os.environ.get(SIGNING_PRIVATE_KEY_ENV, "").strip()
    if not private_key:
        raise RuntimeError(f"{SIGNING_PRIVATE_KEY_ENV} is required to sign release manifests")
    expected_public_key = os.environ.get(SIGNING_PUBLIC_KEY_ENV, "").strip()
    if not expected_public_key:
        raise RuntimeError(
            f"{SIGNING_PUBLIC_KEY_ENV} is required to pin the release signing public key"
        )
    actual_public_key = ed25519_public_key_from_private_key(private_key)
    if actual_public_key != expected_public_key:
        raise RuntimeError(f"{SIGNING_PRIVATE_KEY_ENV} does not match {SIGNING_PUBLIC_KEY_ENV}")
    key_id = os.environ.get(SIGNING_KEY_ID_ENV, RELEASE_MANIFEST_DEFAULT_KEY_ID).strip()
    if not key_id:
        raise RuntimeError(f"{SIGNING_KEY_ID_ENV} must not be empty")
    return private_key, key_id


def write_release_public_keys_module(root: Path) -> tuple[Path, str | None]:
    private_key, key_id = release_signing_key_context()
    public_key = ed25519_public_key_from_private_key(private_key)
    path = root / APP_DIR / "release_public_keys.py"
    original = path.read_text(encoding="utf-8") if path.exists() else None
    content = (
        '"""Generated release manifest verification keys for packaged launchers."""\n\n'
        f"RELEASE_MANIFEST_PUBLIC_KEYS = {{{key_id!r}: {public_key!r}}}\n"
    )
    path.write_text(content, encoding="utf-8")
    return path, original


def restore_release_public_keys_module(path: Path, original: str | None) -> None:
    if original is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(original, encoding="utf-8")


def replace_switches(code: str, switches: dict[str, str]) -> str:
    for key, value in switches.items():
        code = re.sub(rf"(?m)^{key}\s*=.*$", f"{key} = {value}", code)
    return code


def read_metadata_value(metadata_text: str, name: str, source: str = "bomana/metadata.py") -> str:
    m = re.search(rf'{name}\s*=\s*["\']([^"\']+)["\']', metadata_text)
    if not m:
        raise RuntimeError(f"Failed to find {name} in {source}")
    return m.group(1).strip()


def read_version(metadata_text: str) -> str:
    return read_metadata_value(metadata_text, "__version__")


def read_min_launcher_version(metadata_text: str) -> str:
    return read_metadata_value(metadata_text, "PORTABLE_MIN_LAUNCHER_VERSION")


def read_launcher_version(launcher_text: str) -> str:
    m = re.search(r'LAUNCHER_VERSION\s*=\s*["\']([^"\']+)["\']', launcher_text)
    if not m:
        raise RuntimeError("Failed to find LAUNCHER_VERSION in launcher.pyw")
    return m.group(1).strip()


def validate_requested_version(
    requested_version: str,
    target: str,
    app_version: str,
    launcher_version: str,
) -> None:
    requested = requested_version.strip()
    if not requested:
        return

    expected_versions: list[tuple[str, str, str]] = []
    if target in ("all", "app"):
        expected_versions.append(("app", app_version, "bomana/metadata.py __version__"))
    if target in ("all", "launcher"):
        expected_versions.append(("launcher", launcher_version, "launcher.pyw LAUNCHER_VERSION"))

    mismatches = [
        f"{label} expected {expected!r} from {source}"
        for label, expected, source in expected_versions
        if requested != expected
    ]
    if mismatches:
        raise RuntimeError(
            f"--version {requested!r} does not match source version(s): "
            + "; ".join(mismatches)
            + ". Update the source version first, or omit --version."
        )


def add_file_to_zip(zf: zipfile.ZipFile, root: Path, path: Path) -> None:
    rel = path.relative_to(root).as_posix()
    zf.write(path, rel)


def build_app_zip(root: Path, variant: str, version: str, out_dir: Path) -> Path:
    name = f"Bomana_app_{variant}_v{version}.zip"
    out_zip = out_dir / name
    if out_zip.exists():
        out_zip.unlink()

    ccrp_json_rel = Path("bomana/data/ccrp_bomb_params.json")
    ccrp_json = root / ccrp_json_rel
    legacy_ccrp_json = root / "ccrp_bomb_params.json"
    legacy_ccrp_py = root / "ccrp_bomb_params.py"

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
            rel_path = path.relative_to(root).as_posix()
            if variant != "Enhanced" and rel_path == ccrp_json_rel.as_posix():
                continue
            add_file_to_zip(zf, root, path)

        # Backward compatibility: legacy root-level CCRP file.
        if variant == "Enhanced" and not ccrp_json.exists():
            if legacy_ccrp_json.exists():
                add_file_to_zip(zf, root, legacy_ccrp_json)
            elif legacy_ccrp_py.exists():
                add_file_to_zip(zf, root, legacy_ccrp_py)

    return out_zip


def generate_version_info(work_dir: Path, version: str) -> Path:
    """Generate a version info file for PyInstaller to reduce AV false positives."""
    # Convert "1.1.0" -> (1, 1, 0, 0)
    nums = re.findall(r"\d+", version)
    parts = [int(x) for x in nums]
    while len(parts) < 4:
        parts.append(0)
    ver_tuple = tuple(parts[:4])

    content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={ver_tuple},
    prodvers={ver_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'080404b0',
        [StringStruct(u'CompanyName', u'Bomana Team'),
        StringStruct(u'FileDescription', u'Bomana Portable Launcher'),
        StringStruct(u'FileVersion', u'{version}'),
        StringStruct(u'InternalName', u'BomanaLauncher'),
        StringStruct(u'LegalCopyright', u'Copyright (c) 2024 Bomana Team'),
        StringStruct(u'OriginalFilename', u'Bomana_launcher.exe'),
        StringStruct(u'ProductName', u'Bomana'),
        StringStruct(u'ProductVersion', u'{version}')])
      ]), 
    VarFileInfo([VarStruct(u'Translation', [2052, 1200])])
  ]
)
"""
    path = work_dir / "file_version_info.txt"
    path.write_text(content, encoding="utf-8")
    return path


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
        str(root / BRANDING_ICON),
        "--hidden-import",
        "pystray._win32",
        "--hidden-import",
        "winsound",
        "--hidden-import",
        "bomana.release_public_keys",
        "--collect-submodules",
        "PIL",
        "--collect-submodules",
        "pystray",
        "--collect-all",
        "requests",
        "--collect-all",
        "certifi",
        "--distpath",
        str(out_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(work_dir),
        "--clean",
    ]

    # Add version info to reduce false positives
    version_file = generate_version_info(work_dir, version)
    cmd.extend(["--version-file", str(version_file)])

    # Launcher runtime resources (window icon + details dialog assets)
    assets_dir = root / APP_DIR / "assets"
    if assets_dir.exists():
        cmd.extend(["--add-data", f"{assets_dir};{APP_DIR}/assets"])

    cmd.append(str(root / "launcher.pyw"))
    keys_module, keys_module_original = write_release_public_keys_module(root)
    try:
        subprocess.run(cmd, check=True, cwd=root)
    finally:
        restore_release_public_keys_module(keys_module, keys_module_original)
    return out_dir / f"{name}.exe"


def write_manifest(
    out_dir: Path,
    variant: str,
    version: str,
    app_zip_name: str,
    app_sha256: str,
    min_launcher_version: str,
) -> Path:
    manifest = {
        "schema_version": 1,
        "channel": variant,
        "app_version": version,
        "min_launcher_version": min_launcher_version,
        "entrypoint": APP_ENTRY,
        "package_asset": app_zip_name,
        "package_sha256": app_sha256,
    }
    manifest = sign_manifest(manifest)
    path = out_dir / f"manifest_{variant}.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_launcher_manifest(
    out_dir: Path,
    version: str,
    launcher_name: str,
    launcher_sha256: str,
    launcher_size_bytes: int,
) -> Path:
    manifest = {
        "schema_version": 1,
        "launcher_version": version,
        "launcher_asset": launcher_name,
        "launcher_sha256": launcher_sha256,
        "launcher_size_bytes": launcher_size_bytes,
    }
    manifest = sign_manifest(manifest)
    path = out_dir / "launcher_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_checksum_info(
    out_dir: Path,
    variant: str,
    app_version: str | None,
    launcher_version: str | None,
    app_zip: Path | None,
    launcher: Path | None,
    target: str,
) -> Path:
    lines = [
        "Bomana Portable Build",
        "====================",
        "",
        f"variant: {variant}",
    ]
    if app_version:
        lines.append(f"app_version: {app_version}")
    if launcher_version:
        lines.append(f"launcher_version: {launcher_version}")
    lines.extend(
        [
            f"target:  {target}",
            "",
        ]
    )
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
        raise ValueError(f"unsupported checksum target: {target}")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    out_dir = (root / args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    config_path = root / "bomana" / "config.py"
    metadata_path = root / "bomana" / "metadata.py"
    launcher_path = root / "launcher.pyw"
    config_stat = config_path.stat()
    original = config_path.read_text(encoding="utf-8")
    metadata_text = metadata_path.read_text(encoding="utf-8")
    launcher_text = launcher_path.read_text(encoding="utf-8")
    config_patched = False

    app_zip: Path | None = None
    manifest: Path | None = None
    launcher: Path | None = None
    launcher_manifest: Path | None = None
    app_version: str | None = None
    launcher_version: str | None = None
    checksums: list[Path] = []

    try:
        source_app_version = read_version(metadata_text)
        min_launcher_version = read_min_launcher_version(metadata_text)
        source_launcher_version = read_launcher_version(launcher_text)
        validate_requested_version(
            args.version,
            args.target,
            source_app_version,
            source_launcher_version,
        )

        if args.target in ("all", "app"):
            app_version = source_app_version
            patched = replace_switches(original, VARIANT_SWITCHES[args.variant])
            if patched != original:
                config_path.write_text(patched, encoding="utf-8")
                config_patched = True
            app_zip = build_app_zip(root, args.variant, app_version, out_dir)
            app_sha = sha256_file(app_zip)
            manifest = write_manifest(
                out_dir,
                args.variant,
                app_version,
                app_zip.name,
                app_sha,
                min_launcher_version,
            )

        if args.target in ("all", "launcher"):
            launcher_version = source_launcher_version
            launcher = build_launcher(root, launcher_version, out_dir)
            launcher_sha = sha256_file(launcher)
            launcher_manifest = write_launcher_manifest(
                out_dir,
                launcher_version,
                launcher.name,
                launcher_sha,
                launcher.stat().st_size,
            )

        if args.target in ("all", "app"):
            checksums.append(
                write_checksum_info(
                    out_dir,
                    args.variant,
                    app_version,
                    None,
                    app_zip,
                    None,
                    "app",
                )
            )
        if args.target in ("all", "launcher"):
            checksums.append(
                write_checksum_info(
                    out_dir,
                    "Universal",
                    None,
                    launcher_version,
                    None,
                    launcher,
                    "launcher",
                )
            )

        checksum_variant = "Universal" if args.target == "launcher" else args.variant
        safe_print(
            f"[OK] variant={checksum_variant} app_version={app_version or '-'} "
            f"launcher_version={launcher_version or '-'} "
            f"target={args.target}"
        )
        if app_zip and app_zip.exists():
            safe_print(f"  - app package: {app_zip}")
        if manifest and manifest.exists():
            safe_print(f"  - manifest:    {manifest}")
        if launcher and launcher.exists():
            safe_print(f"  - launcher:    {launcher}")
        if launcher_manifest and launcher_manifest.exists():
            safe_print(f"  - launcher manifest: {launcher_manifest}")
        for checksum in checksums:
            safe_print(f"  - checksum:    {checksum}")
        return 0
    finally:
        if config_patched:
            config_path.write_text(original, encoding="utf-8")
            os.utime(config_path, ns=(config_stat.st_atime_ns, config_stat.st_mtime_ns))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        safe_print(f"[ERROR] {exc}")
        raise SystemExit(1) from None
