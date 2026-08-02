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

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bomana.editions import (  # noqa: E402
    PUBLIC_CHANNELS,
    require_public_edition,
    variant_switch_matrix,
)
from bomana.release_closure import public_release_includes  # noqa: E402
from launcher.core import (  # noqa: E402
    RELEASE_MANIFEST_DEFAULT_KEY_ID,
    ed25519_public_key_from_private_key,
    sign_release_manifest,
)
from launcher.subscription_access import validate_license_public_key  # noqa: E402
from launcher.subscription_key_contract import (  # noqa: E402
    CHEEMSPAY_LICENSE_KEY_ID,
    CHEEMSPAY_LICENSE_PUBLIC_KEY_DER_BASE64URL,
    CHEEMSPAY_LICENSE_PUBLIC_KEYS,
)

VARIANT_SWITCHES = {channel: variant_switch_matrix()[channel] for channel in PUBLIC_CHANNELS}

FEATURE_PROFILE_PATH = Path("bomana/config/feature_profile.py")
EDITION_CHANNEL_ASSIGNMENT = re.compile(
    r'(?m)^EDITION_CHANNEL[ \t]*=[ \t]*["\'][^"\'\r\n]+["\'][ \t]*$'
)

APP_ENTRY = "Bomana.pyw"
APP_DIR = "bomana"
LAUNCHER_DIR = "launcher"
UNIVERSAL_LAUNCHER_NAME = "Bomana_launcher"
GREEN_VARIANT = "Lite"
GREEN_BUNDLE_NAME = "Bomana_Green_Lite"
GREEN_DISTRIBUTION_ENV = "BOMANA_DISTRIBUTION_MODE"
GREEN_DISTRIBUTION_VALUE = "green"
HOTKEY_BROKER_NAME = "BomanaHotkeyBroker.exe"
HOTKEY_BROKER_CHECKSUM_NAME = "BomanaHotkeyBroker.sha256"
BRANDING_ICON = Path(APP_DIR) / "assets" / "branding" / "app.ico"
SIGNING_PRIVATE_KEY_ENV = "BOMANA_RELEASE_ED25519_PRIVATE_KEY"
SIGNING_PUBLIC_KEY_ENV = "BOMANA_RELEASE_ED25519_PUBLIC_KEY"
SIGNING_KEY_ID_ENV = "BOMANA_RELEASE_SIGNING_KEY_ID"
SUBSCRIPTION_PUBLIC_KEY_ENV = "CHEEMSPAY_LICENSE_PUBLIC_KEY_DER_BASE64URL"
SUBSCRIPTION_KEY_ID_ENV = "CHEEMSPAY_LICENSE_KEY_ID"
PACKAGED_LAUNCHER_REQUIRES_PYTHON = ">=3.14"
PACKAGED_LAUNCHER_RUNTIME_MIN_LAUNCHER_VERSION = "3.4.0"
PACKAGED_LAUNCHER_RUNTIME_MODULES_BY_DEPENDENCY = {
    "requests": "requests",
    "certifi": "certifi",
    "pillow": "PIL",
    "pystray": "pystray",
}
PACKAGED_LAUNCHER_HIDDEN_IMPORTS = (
    "http.cookies",
    "http.server",
    "ipaddress",
    "mimetypes",
    "pystray._win32",
    "socketserver",
    "winsound",
    "bomana_subscription_public_keys",
    "launcher.release_public_keys",
)
PACKAGED_LAUNCHER_COLLECT_SUBMODULES = (
    "PIL",
    "pystray",
)
PACKAGED_LAUNCHER_COLLECT_ALL = (
    "requests",
    "certifi",
)
PACKAGED_GREEN_HIDDEN_IMPORTS = (
    "pystray._win32",
    "winsound",
)
PACKAGED_GREEN_COLLECT_SUBMODULES = (
    "PIL",
    "pystray",
)
PACKAGED_GREEN_COLLECT_ALL = (
    "requests",
    "certifi",
)
APP_RELEASE_SOURCE_SCOPES = (
    APP_ENTRY,
    "bomana_version.py",
    APP_DIR,
    "docs/CHANGELOG.md",
)
LAUNCHER_RELEASE_SOURCE_SCOPES = (
    "launcher.pyw",
    LAUNCHER_DIR,
    f"{APP_DIR}/editions.py",
    f"{APP_DIR}/assets",
)


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
        choices=PUBLIC_CHANNELS,
        default="Standard",
        help="Build a public App variant channel",
    )
    parser.add_argument(
        "--target",
        choices=("all", "app", "green", "launcher"),
        default="all",
        help="Build target: all / app package / Lite green bundle / launcher",
    )
    parser.add_argument(
        "--version",
        default="",
        help=(
            "Expected version; fails if it does not match the source metadata "
            "(app: bomana/metadata.py, launcher: launcher/metadata.py)"
        ),
    )
    parser.add_argument(
        "--output",
        default="dist",
        help="Output directory for release assets",
    )
    parser.add_argument(
        "--hotkey-broker",
        default="",
        help=(
            "prebuilt BomanaHotkeyBroker.exe for app packages; when omitted, "
            "tools/build_hotkey_broker.py builds it from source"
        ),
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def packaged_launcher_runtime_dependency_names() -> tuple[str, ...]:
    return tuple(PACKAGED_LAUNCHER_RUNTIME_MODULES_BY_DEPENDENCY)


def packaged_launcher_runtime_module_names() -> tuple[str, ...]:
    return tuple(PACKAGED_LAUNCHER_RUNTIME_MODULES_BY_DEPENDENCY.values())


def pyinstaller_launcher_runtime_args() -> list[str]:
    args: list[str] = []
    for module in PACKAGED_LAUNCHER_HIDDEN_IMPORTS:
        args.extend(["--hidden-import", module])
    for module in PACKAGED_LAUNCHER_COLLECT_SUBMODULES:
        args.extend(["--collect-submodules", module])
    for module in PACKAGED_LAUNCHER_COLLECT_ALL:
        args.extend(["--collect-all", module])
    return args


def pyinstaller_green_runtime_args() -> list[str]:
    args: list[str] = []
    for module in PACKAGED_GREEN_HIDDEN_IMPORTS:
        args.extend(["--hidden-import", module])
    for module in PACKAGED_GREEN_COLLECT_SUBMODULES:
        args.extend(["--collect-submodules", module])
    for module in PACKAGED_GREEN_COLLECT_ALL:
        args.extend(["--collect-all", module])
    return args


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
    path = root / LAUNCHER_DIR / "release_public_keys.py"
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


def write_subscription_public_keys_module(work_dir: Path) -> tuple[Path, Path]:
    """Generate the public CheemsPay key outside the source tree for PyInstaller."""

    configured_public_key = os.environ.get(SUBSCRIPTION_PUBLIC_KEY_ENV, "").strip()
    if not configured_public_key:
        raise RuntimeError(
            f"{SUBSCRIPTION_PUBLIC_KEY_ENV} is required and must match the repository trust contract"
        )
    configured_key_id = os.environ.get(SUBSCRIPTION_KEY_ID_ENV, "").strip()
    if not configured_key_id:
        raise RuntimeError(
            f"{SUBSCRIPTION_KEY_ID_ENV} is required and must match the repository trust contract"
        )
    if CHEEMSPAY_LICENSE_PUBLIC_KEYS.get(CHEEMSPAY_LICENSE_KEY_ID) != (
        CHEEMSPAY_LICENSE_PUBLIC_KEY_DER_BASE64URL
    ):
        raise RuntimeError("repository CheemsPay trust contract no longer contains its primary key")
    for public_key in CHEEMSPAY_LICENSE_PUBLIC_KEYS.values():
        validate_license_public_key(public_key)
    expected_public_key = CHEEMSPAY_LICENSE_PUBLIC_KEYS.get(configured_key_id)
    if expected_public_key is None:
        raise RuntimeError(
            f"{SUBSCRIPTION_KEY_ID_ENV} is not present in the repository CheemsPay trust root contract"
        )
    if configured_public_key != expected_public_key:
        raise RuntimeError(
            f"{SUBSCRIPTION_PUBLIC_KEY_ENV} does not match the repository CheemsPay trust root contract"
        )
    generated_dir = work_dir / "generated-runtime"
    generated_dir.mkdir(parents=True, exist_ok=False)
    path = generated_dir / "bomana_subscription_public_keys.py"
    path.write_text(
        '"""Generated CheemsPay receipt verification keys for packaged launchers."""\n\n'
        f"CHEEMSPAY_LICENSE_PUBLIC_KEYS = {dict(CHEEMSPAY_LICENSE_PUBLIC_KEYS)!r}\n",
        encoding="utf-8",
    )
    return generated_dir, path


def render_feature_profile(code: str, variant: str) -> str:
    """Render one package-local edition identity without modifying source."""

    edition = require_public_edition(variant)
    if len(EDITION_CHANNEL_ASSIGNMENT.findall(code)) != 1:
        raise RuntimeError("feature profile must define exactly one EDITION_CHANNEL")
    return EDITION_CHANNEL_ASSIGNMENT.sub(
        f'EDITION_CHANNEL = "{edition.channel}"',
        code,
        count=1,
    )


def read_metadata_value(metadata_text: str, name: str, source: str = "bomana/metadata.py") -> str:
    m = re.search(rf'{name}\s*=\s*["\']([^"\']+)["\']', metadata_text)
    if not m:
        raise RuntimeError(f"Failed to find {name} in {source}")
    return m.group(1).strip()


def read_version(metadata_text: str) -> str:
    return read_metadata_value(metadata_text, "__version__")


def read_min_launcher_version(metadata_text: str) -> str:
    return read_metadata_value(metadata_text, "PORTABLE_MIN_LAUNCHER_VERSION")


def read_app_required_launcher_version(boundary_text: str) -> str:
    match = re.search(
        r'APP_REQUIRED_LAUNCHER_VERSION(?:\s*:\s*Final)?\s*=\s*["\']([^"\']+)["\']',
        boundary_text,
    )
    if not match:
        raise RuntimeError("Failed to find APP_REQUIRED_LAUNCHER_VERSION in bomana_version.py")
    return match.group(1).strip()


def validate_app_launcher_floor(metadata_text: str, boundary_text: str) -> str:
    metadata_floor = read_min_launcher_version(metadata_text)
    boundary_floor = read_app_required_launcher_version(boundary_text)
    if boundary_floor != metadata_floor:
        raise RuntimeError(
            "App Launcher floor mismatch: "
            f"bomana/metadata.py={metadata_floor!r}, bomana_version.py={boundary_floor!r}"
        )
    return metadata_floor


def read_launcher_version(launcher_text: str, source: str = "launcher/metadata.py") -> str:
    m = re.search(r'LAUNCHER_VERSION\s*=\s*["\']([^"\']+)["\']', launcher_text)
    if not m:
        raise RuntimeError(f"Failed to find LAUNCHER_VERSION in {source}")
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
    if target in ("all", "app", "green"):
        expected_versions.append(("app", app_version, "bomana/metadata.py __version__"))
    if target in ("all", "launcher"):
        expected_versions.append(
            ("launcher", launcher_version, "launcher/metadata.py LAUNCHER_VERSION")
        )

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


def add_app_file_to_zip(
    zf: zipfile.ZipFile,
    root: Path,
    path: Path,
    variant: str,
) -> None:
    """Add an App file, rendering only the archived edition profile."""

    rel_path = path.relative_to(root)
    if rel_path != FEATURE_PROFILE_PATH:
        add_file_to_zip(zf, root, path)
        return

    rendered = render_feature_profile(path.read_text(encoding="utf-8"), variant)
    info = zipfile.ZipInfo.from_file(path, rel_path.as_posix())
    info.compress_type = zf.compression
    zf.writestr(info, rendered.encode("utf-8"))


def _release_source_scopes(target: str) -> tuple[str, ...]:
    scopes: list[str] = []
    if target in ("all", "app", "green"):
        scopes.extend(APP_RELEASE_SOURCE_SCOPES)
    if target in ("all", "launcher"):
        scopes.extend(LAUNCHER_RELEASE_SOURCE_SCOPES)
    return tuple(dict.fromkeys(scopes))


def _app_source_files(
    root: Path,
    variant: str,
    release_source_paths: frozenset[str] | None = None,
) -> tuple[Path, ...]:
    require_public_edition(variant)
    if release_source_paths is None:
        candidates = tuple((root / APP_DIR).rglob("*"))
    else:
        candidates = tuple(
            root / Path(rel_path)
            for rel_path in sorted(release_source_paths)
            if rel_path.startswith(f"{APP_DIR}/")
        )
    selected: list[Path] = []
    for path in candidates:
        if release_source_paths is not None and (path.is_symlink() or not path.is_file()):
            rel_path = path.relative_to(root).as_posix()
            raise RuntimeError(f"invalid tracked App package file: {rel_path}")
        if path.is_dir():
            continue
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        rel_path = path.relative_to(root).as_posix()
        if rel_path.startswith(f"{APP_DIR}/bin/"):
            continue
        if not public_release_includes(rel_path):
            continue
        selected.append(path)
    return tuple(selected)


def _unexpected_release_files(
    root: Path,
    target: str,
    variant: str,
    tracked_paths: frozenset[str],
) -> tuple[str, ...]:
    unexpected: set[str] = set()
    if target in ("all", "app", "green"):
        for path in _app_source_files(root, variant):
            rel_path = path.relative_to(root).as_posix()
            if rel_path not in tracked_paths:
                unexpected.add(rel_path)
    if target in ("all", "launcher"):
        assets_dir = root / APP_DIR / "assets"
        if assets_dir.exists():
            for path in assets_dir.rglob("*"):
                if path.is_dir() or "__pycache__" in path.parts:
                    continue
                if path.suffix in {".pyc", ".pyo"}:
                    continue
                rel_path = path.relative_to(root).as_posix()
                if not public_release_includes(rel_path):
                    continue
                if rel_path not in tracked_paths:
                    unexpected.add(rel_path)
    return tuple(sorted(unexpected))


def resolve_release_source_closure(
    root: Path,
    target: str,
    variant: str,
) -> frozenset[str]:
    """Resolve a clean, Git-tracked source inventory before signing a release."""
    scopes = _release_source_scopes(target)
    tracked_result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", *scopes],
        check=False,
        capture_output=True,
    )
    if tracked_result.returncode != 0:
        detail = tracked_result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"unable to resolve release source closure: {detail}")
    tracked_paths = frozenset(
        value
        for value in tracked_result.stdout.decode("utf-8", errors="strict").split("\0")
        if value
    )
    if not tracked_paths:
        raise RuntimeError("release source closure is empty")

    dirty_result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            *scopes,
        ],
        check=False,
        capture_output=True,
    )
    if dirty_result.returncode != 0:
        detail = dirty_result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"unable to verify release source closure: {detail}")
    dirty_entries = tuple(
        value
        for value in dirty_result.stdout.decode("utf-8", errors="replace").split("\0")
        if value
    )
    if dirty_entries:
        raise RuntimeError("release source tree is not clean: " + ", ".join(dirty_entries[:8]))

    unexpected = _unexpected_release_files(root, target, variant, tracked_paths)
    if unexpected:
        raise RuntimeError(
            "release source tree contains unexpected package files: " + ", ".join(unexpected[:8])
        )
    return tracked_paths


def _stage_launcher_assets(
    root: Path,
    work_dir: Path,
    release_source_paths: frozenset[str] | None,
) -> Path:
    assets_dir = root / APP_DIR / "assets"
    staged_assets = work_dir / "release-assets"
    staged_assets.mkdir(parents=True, exist_ok=False)
    asset_prefix = f"{APP_DIR}/assets/"
    if release_source_paths is None:
        asset_paths = (
            path.relative_to(root).as_posix() for path in assets_dir.rglob("*") if path.is_file()
        )
    else:
        asset_paths = iter(release_source_paths)
    for rel_path in sorted(asset_paths):
        if not rel_path.startswith(asset_prefix):
            continue
        if not public_release_includes(rel_path):
            continue
        source = root / Path(rel_path)
        if source.is_symlink() or not source.is_file():
            raise RuntimeError(f"invalid tracked Launcher asset: {rel_path}")
        destination = staged_assets / Path(rel_path).relative_to(Path(APP_DIR) / "assets")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return staged_assets


def resolve_hotkey_broker(root: Path, configured_path: str) -> Path:
    if configured_path.strip():
        broker = Path(configured_path).resolve()
    else:
        output = root / "build" / "hotkey-broker-release"
        subprocess.run(
            [
                sys.executable,
                str(root / "tools" / "build_hotkey_broker.py"),
                "--mode",
                "release",
                "--output",
                str(output),
            ],
            cwd=root,
            check=True,
        )
        broker = output / HOTKEY_BROKER_NAME
    if not broker.is_file() or broker.name != HOTKEY_BROKER_NAME:
        raise RuntimeError(f"missing fixed-name hotkey broker: {broker}")
    return broker


def build_app_zip(
    root: Path,
    variant: str,
    version: str,
    out_dir: Path,
    hotkey_broker: Path,
    release_source_paths: frozenset[str],
) -> Path:
    edition = require_public_edition(variant)
    name = f"Bomana_app_{variant}_v{version}.zip"
    out_zip = out_dir / name
    if out_zip.exists():
        out_zip.unlink()

    version_boundary = root / "bomana_version.py"
    required_runtime_paths = [version_boundary]
    missing_runtime_assets = [
        path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
        for path in required_runtime_paths
        if not path.exists()
    ]
    if missing_runtime_assets:
        raise RuntimeError(
            "missing shared App runtime assets: " + ", ".join(missing_runtime_assets)
        )

    app_source_files = _app_source_files(root, variant, release_source_paths)
    expected_entries = {
        APP_ENTRY,
        "bomana_version.py",
        *(path.relative_to(root).as_posix() for path in app_source_files),
        f"{APP_DIR}/bin/{HOTKEY_BROKER_NAME}",
        f"{APP_DIR}/bin/{HOTKEY_BROKER_CHECKSUM_NAME}",
    }

    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        add_file_to_zip(zf, root, root / APP_ENTRY)
        add_file_to_zip(zf, root, version_boundary)

        for path in app_source_files:
            add_app_file_to_zip(zf, root, path, edition.channel)

        broker_sha256 = sha256_file(hotkey_broker)
        zf.write(
            hotkey_broker,
            f"{APP_DIR}/bin/{HOTKEY_BROKER_NAME}",
        )
        zf.writestr(
            f"{APP_DIR}/bin/{HOTKEY_BROKER_CHECKSUM_NAME}",
            f"{broker_sha256}  {HOTKEY_BROKER_NAME}\n",
        )

    with zipfile.ZipFile(out_zip, "r") as archive:
        names = archive.namelist()
    if len(names) != len(expected_entries) or set(names) != expected_entries:
        out_zip.unlink(missing_ok=True)
        raise RuntimeError("App package contents do not match the release source closure")

    return out_zip


def stage_green_app(
    root: Path,
    work_dir: Path,
    hotkey_broker: Path,
    release_source_paths: frozenset[str],
) -> Path:
    """Stage an immutable Lite-only source tree for the frozen green build."""

    staged_root = work_dir / "source"
    staged_root.mkdir(parents=True, exist_ok=False)
    for rel_path in (APP_ENTRY, "bomana_version.py"):
        if rel_path not in release_source_paths:
            raise RuntimeError(f"green source closure is missing {rel_path}")
        source = root / rel_path
        destination = staged_root / rel_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    for source in _app_source_files(root, GREEN_VARIANT, release_source_paths):
        rel_path = source.relative_to(root)
        destination = staged_root / rel_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if rel_path == FEATURE_PROFILE_PATH:
            destination.write_text(
                render_feature_profile(source.read_text(encoding="utf-8"), GREEN_VARIANT),
                encoding="utf-8",
            )
        else:
            shutil.copy2(source, destination)

    broker_dir = staged_root / APP_DIR / "bin"
    broker_dir.mkdir(parents=True, exist_ok=True)
    staged_broker = broker_dir / HOTKEY_BROKER_NAME
    shutil.copy2(hotkey_broker, staged_broker)
    (broker_dir / HOTKEY_BROKER_CHECKSUM_NAME).write_text(
        f"{sha256_file(staged_broker)}  {HOTKEY_BROKER_NAME}\n",
        encoding="ascii",
    )
    return staged_root


def generate_green_runtime_hook(work_dir: Path) -> Path:
    path = work_dir / "green_runtime_hook.py"
    path.write_text(
        f"import os\nos.environ[{GREEN_DISTRIBUTION_ENV!r}] = {GREEN_DISTRIBUTION_VALUE!r}\n",
        encoding="ascii",
    )
    return path


def generate_green_version_info(work_dir: Path, version: str) -> Path:
    nums = re.findall(r"\d+", version)
    parts = [int(value) for value in nums]
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
      [StringTable(
        u'080404b0',
        [StringStruct(u'CompanyName', u'Bomana Team'),
        StringStruct(u'FileDescription', u'Bomana Lite Green Edition'),
        StringStruct(u'FileVersion', u'{version}'),
        StringStruct(u'InternalName', u'BomanaGreenLite'),
        StringStruct(u'LegalCopyright', u'Copyright (c) 2024-2026 Bomana Team'),
        StringStruct(u'OriginalFilename', u'Bomana_Green_Lite.exe'),
        StringStruct(u'ProductName', u'Bomana Lite Green Edition'),
        StringStruct(u'ProductVersion', u'{version}')])
      ]),
    VarFileInfo([VarStruct(u'Translation', [2052, 1200])])
  ]
)
"""
    path = work_dir / "green_file_version_info.txt"
    path.write_text(content, encoding="utf-8")
    return path


def _write_green_readme(bundle_dir: Path, version: str) -> None:
    (bundle_dir / "README_GREEN.txt").write_text(
        (
            f"Bomana Lite Green v{version}\n"
            "============================\n\n"
            "解压整个目录后运行同目录内的 Bomana_Green_Lite 可执行文件。\n"
            "无需安装 Python，也不需要 Bomana Launcher。请勿只复制 EXE。\n\n"
            "该版本仅包含 Lite 功能。启动时会在后台按 UTC 日期上报一次匿名日活；\n"
            "网络失败不会阻止或延迟主界面。创建用户目录下的 .bomana_disable_dau\n"
            "空文件，或设置 BOMANA_DISABLE_DAU=1，可禁用该上报。\n"
        ),
        encoding="utf-8",
    )


def verify_green_bundle_layout(bundle: Path, executable_stem: str) -> None:
    prefix = f"{executable_stem}/"
    executable = f"{prefix}{executable_stem}.exe"
    broker = f"{prefix}_internal/{APP_DIR}/bin/{HOTKEY_BROKER_NAME}"
    broker_checksum = f"{prefix}_internal/{APP_DIR}/bin/{HOTKEY_BROKER_CHECKSUM_NAME}"
    with zipfile.ZipFile(bundle, "r") as archive:
        names = set(archive.namelist())
    if executable not in names:
        raise RuntimeError("green bundle is missing its standalone executable")
    if broker not in names or broker_checksum not in names:
        raise RuntimeError("green bundle is missing the zero-install hotkey broker")
    if not any(
        name.startswith(f"{prefix}_internal/python3") and name.endswith(".dll") for name in names
    ):
        raise RuntimeError("green bundle is missing the bundled Python runtime")
    if any("launcher" in name.lower() for name in names):
        raise RuntimeError("green bundle unexpectedly contains Launcher files")


def build_green_bundle(
    root: Path,
    variant: str,
    version: str,
    out_dir: Path,
    hotkey_broker: Path,
    release_source_paths: frozenset[str],
) -> Path:
    if variant != GREEN_VARIANT:
        raise RuntimeError("green distribution is Lite-only")

    executable_stem = f"{GREEN_BUNDLE_NAME}_v{version}"
    work_dir = root / "build" / "pyinstaller" / "GreenLite"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    staged_root = stage_green_app(root, work_dir, hotkey_broker, release_source_paths)
    runtime_hook = generate_green_runtime_hook(work_dir)
    version_file = generate_green_version_info(work_dir, version)
    pyinstaller_dist = work_dir / "dist"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconsole",
        "--onedir",
        "--name",
        executable_stem,
        "--icon",
        str(staged_root / BRANDING_ICON),
        "--paths",
        str(staged_root),
        "--runtime-hook",
        str(runtime_hook),
        "--version-file",
        str(version_file),
        *pyinstaller_green_runtime_args(),
        "--distpath",
        str(pyinstaller_dist),
        "--workpath",
        str(work_dir / "work"),
        "--specpath",
        str(work_dir / "spec"),
        "--clean",
    ]
    for rel_path in (Path(APP_DIR) / "assets", Path(APP_DIR) / "data", Path(APP_DIR) / "bin"):
        source = staged_root / rel_path
        if source.exists():
            cmd.extend(["--add-data", f"{source};{rel_path.as_posix()}"])
    cmd.append(str(staged_root / APP_ENTRY))
    subprocess.run(cmd, check=True, cwd=staged_root)

    bundle_dir = pyinstaller_dist / executable_stem
    _write_green_readme(bundle_dir, version)
    out_bundle = out_dir / f"{executable_stem}.zip"
    out_bundle.unlink(missing_ok=True)
    with zipfile.ZipFile(out_bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(bundle_dir.rglob("*")):
            if path.is_file():
                rel_path = path.relative_to(bundle_dir).as_posix()
                zf.write(path, f"{executable_stem}/{rel_path}")
    verify_green_bundle_layout(out_bundle, executable_stem)
    return out_bundle


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


def build_launcher(
    root: Path,
    version: str,
    out_dir: Path,
    release_source_paths: frozenset[str],
) -> Path:
    name = f"{UNIVERSAL_LAUNCHER_NAME}_v{version}"
    work_dir = root / "build" / "pyinstaller" / "UniversalLauncher"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = _stage_launcher_assets(root, work_dir, release_source_paths)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconsole",
        "--onefile",
        "--name",
        name,
        "--icon",
        str(assets_dir / BRANDING_ICON.relative_to(Path(APP_DIR) / "assets")),
        *pyinstaller_launcher_runtime_args(),
        "--distpath",
        str(out_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(work_dir),
        "--clean",
    ]

    generated_keys_dir, _subscription_keys_module = write_subscription_public_keys_module(work_dir)
    cmd.extend(["--paths", str(generated_keys_dir)])

    # Add version info to reduce false positives
    version_file = generate_version_info(work_dir, version)
    cmd.extend(["--version-file", str(version_file)])

    # Launcher runtime resources (window icon + details dialog assets)
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
    changelog_name: str,
    changelog_sha256: str,
) -> Path:
    manifest = {
        "schema_version": 2,
        "channel": variant,
        "app_version": version,
        "min_launcher_version": min_launcher_version,
        "entrypoint": APP_ENTRY,
        "package_asset": app_zip_name,
        "package_sha256": app_sha256,
        "changelog_asset": changelog_name,
        "changelog_sha256": changelog_sha256,
    }
    manifest = sign_manifest(manifest)
    path = out_dir / f"manifest_{variant}.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_changelog_asset(root: Path, out_dir: Path, variant: str, version: str) -> Path:
    source = (root / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    marker = f"## [{version}]"
    start = source.find(marker)
    if start < 0:
        raise RuntimeError(f"docs/CHANGELOG.md missing release section {marker}")
    next_heading = source.find("\n## [", start + len(marker))
    notes = source[start : next_heading if next_heading >= 0 else len(source)].strip() + "\n"
    path = out_dir / f"CHANGELOG_{variant}_v{version}.md"
    path.write_text(notes, encoding="utf-8")
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


def write_green_checksum_info(out_dir: Path, version: str, bundle: Path) -> Path:
    path = out_dir / "checksums_green_Lite.txt"
    path.write_text(
        "\n".join(
            (
                "Bomana Lite Green Build",
                "=======================",
                "",
                f"app_version: {version}",
                "channel: Lite",
                "distribution: green",
                "requires_launcher: false",
                "python_runtime_bundled: true",
                "",
                f"{bundle.name}  SHA256  {sha256_file(bundle)}",
                "",
            )
        ),
        encoding="utf-8",
    )
    return path


def main() -> int:
    args = parse_args()
    if args.target == "green" and args.variant != GREEN_VARIANT:
        raise ValueError("green target requires --variant Lite")
    root = Path(__file__).resolve().parent.parent
    out_dir = (root / args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    feature_profile_path = root / "bomana" / "config" / "feature_profile.py"
    metadata_path = root / "bomana" / "metadata.py"
    version_boundary_path = root / "bomana_version.py"
    launcher_metadata_path = root / "launcher" / "metadata.py"
    original_feature_profile_bytes = feature_profile_path.read_bytes()
    metadata_text = metadata_path.read_text(encoding="utf-8")
    version_boundary_text = version_boundary_path.read_text(encoding="utf-8")
    launcher_metadata_text = launcher_metadata_path.read_text(encoding="utf-8")

    app_zip: Path | None = None
    manifest: Path | None = None
    launcher: Path | None = None
    launcher_manifest: Path | None = None
    green_bundle: Path | None = None
    app_version: str | None = None
    launcher_version: str | None = None
    checksums: list[Path] = []
    changelog: Path | None = None

    try:
        source_app_version = read_version(metadata_text)
        min_launcher_version = validate_app_launcher_floor(
            metadata_text,
            version_boundary_text,
        )
        source_launcher_version = read_launcher_version(
            launcher_metadata_text,
            "launcher/metadata.py",
        )
        validate_requested_version(
            args.version,
            args.target,
            source_app_version,
            source_launcher_version,
        )
        release_source_paths = resolve_release_source_closure(
            root,
            args.target,
            args.variant,
        )

        hotkey_broker: Path | None = None
        if args.target in ("all", "app", "green"):
            hotkey_broker = resolve_hotkey_broker(root, args.hotkey_broker)

        if args.target in ("all", "app"):
            app_version = source_app_version
            assert hotkey_broker is not None
            app_zip = build_app_zip(
                root,
                args.variant,
                app_version,
                out_dir,
                hotkey_broker,
                release_source_paths,
            )
            app_sha = sha256_file(app_zip)
            changelog = write_changelog_asset(root, out_dir, args.variant, app_version)
            manifest = write_manifest(
                out_dir,
                args.variant,
                app_version,
                app_zip.name,
                app_sha,
                min_launcher_version,
                changelog.name,
                sha256_file(changelog),
            )

        if args.target in ("all", "green"):
            app_version = source_app_version
            assert hotkey_broker is not None
            green_bundle = build_green_bundle(
                root,
                GREEN_VARIANT,
                app_version,
                out_dir,
                hotkey_broker,
                release_source_paths,
            )
            checksums.append(write_green_checksum_info(out_dir, app_version, green_bundle))

        if args.target in ("all", "launcher"):
            launcher_version = source_launcher_version
            launcher = build_launcher(
                root,
                launcher_version,
                out_dir,
                release_source_paths,
            )
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

        if args.target == "launcher":
            checksum_variant = "Universal"
        elif args.target == "green":
            checksum_variant = "Green Lite"
        else:
            checksum_variant = args.variant
        safe_print(
            f"[OK] variant={checksum_variant} app_version={app_version or '-'} "
            f"launcher_version={launcher_version or '-'} "
            f"target={args.target}"
        )
        if app_zip and app_zip.exists():
            safe_print(f"  - app package: {app_zip}")
        if manifest and manifest.exists():
            safe_print(f"  - manifest:    {manifest}")
        if changelog and changelog.exists():
            safe_print(f"  - changelog:   {changelog}")
        if green_bundle and green_bundle.exists():
            safe_print(f"  - green bundle: {green_bundle}")
        if launcher and launcher.exists():
            safe_print(f"  - launcher:    {launcher}")
        if launcher_manifest and launcher_manifest.exists():
            safe_print(f"  - launcher manifest: {launcher_manifest}")
        for checksum in checksums:
            safe_print(f"  - checksum:    {checksum}")
        return 0
    finally:
        if feature_profile_path.read_bytes() != original_feature_profile_bytes:
            raise RuntimeError("portable build modified the source feature profile")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        safe_print(f"[ERROR] {exc}")
        raise SystemExit(1) from None
