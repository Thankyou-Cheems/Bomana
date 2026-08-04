# -*- coding: utf-8 -*-
"""Bomana portable launcher with user-friendly GUI update flow."""

import contextlib
import ctypes
import hashlib
import ipaddress
import json
import os
import queue
import re
import shutil
import socket

# Configure SSL context for HTTPS connections (critical for PyInstaller)
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import uuid
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Callable, Dict, Iterable, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import (
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from bomana_version import (
    MIN_SUPPORTED_APP_VERSION,
    MIN_SUPPORTED_LAUNCHER_VERSION,
    VersionCompatibilityError,
    require_minimum_version,
)
from bomana.editions import (
    CHANNEL_ALIASES as _EDITION_CHANNEL_ALIASES,
    CHANNEL_DETAILS as _EDITION_CHANNEL_DETAILS,
    CHANNEL_DISPLAY_NAMES as _EDITION_CHANNEL_DISPLAY_NAMES,
    WEB_COCKPIT_CHANNELS as _EDITION_WEB_COCKPIT_CHANNELS,
)
from launcher.core import (
    DOWNLOAD_SOURCE_CHOICES,
    DOWNLOAD_SOURCE_DETAILS,
    DOWNLOAD_SOURCE_LABEL_TO_MODE as _DOWNLOAD_SOURCE_LABEL_TO_MODE,
    DOWNLOAD_SOURCE_MODE_AUTO,
    DOWNLOAD_SOURCE_MODE_GITHUB,
    DOWNLOAD_SOURCE_MODE_PRIMARY,
    LaunchDecision,
    download_source_label as _download_source_label,
    find_asset as _find_asset,
    format_min_launcher_requirement as _format_min_launcher_requirement,
    format_size_text as _format_size_text,
    join_base_url_path as _join_base_url_path,
    normalize_download_source_mode as _normalize_download_source_mode,
    require_remote_checksum as _require_remote_checksum,
    sha256_bytes as _sha256_bytes,
    verify_release_manifest_signature as _verify_release_manifest_signature,
    version_is_newer as _version_is_newer,
)
from launcher.subscription_access import (
    AuthorizedArtifactRequest,
    CHEEMSPAY_BASE_URL,
    CHEEMSPAY_LICENSE_PUBLIC_KEYS,
    CheemsPaySubscriptionAuthority,
    DeviceAuthorizationState,
    ReceiptVerifier,
    SubscriptionAccessDecision,
    SubscriptionAccessReason,
)
from launcher.subscription_store import create_default_subscription_store
from launcher.subscription_workflow import SubscriptionWorkflow
from bomana.ui.tk_style import style_action_button
from bomana.utils.system import Win32, select_ui_font_family
from launcher import bootstrap as _launcher_bootstrap
from launcher import distribution_build as _launcher_distribution_build
from launcher import download_cache as _launcher_download_cache
from launcher import install_txn
from launcher import launch_contract as _launcher_launch_contract
from launcher import manifest_sources as _launcher_manifest_sources
from launcher import self_update as _launcher_self_update
from launcher import subscriber_artifacts as _subscriber_artifacts
from launcher import terrain_store as _launcher_terrain_store
from launcher import terrain_presentation as _launcher_terrain_presentation
from launcher import terrain_transport as _launcher_terrain_transport
from launcher import telemetry as _launcher_telemetry
from launcher.metadata import LAUNCHER_VERSION

try:
    import certifi

    _ssl_context = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _ssl_context = ssl.create_default_context()

# Launcher metadata
_DISTRIBUTION_BUILD_METADATA = _launcher_distribution_build.current_build_metadata()


def _display_name_for_build(
    metadata: _launcher_distribution_build.DistributionBuildMetadata | None = None,
) -> str:
    selected = _DISTRIBUTION_BUILD_METADATA if metadata is None else metadata
    suffix = " [隔离测试]" if selected.isolated_test else ""
    return f"Bomana香焦{suffix}"


def _effective_download_source_mode(
    value: object,
    *,
    metadata: _launcher_distribution_build.DistributionBuildMetadata | None = None,
) -> str:
    selected = _DISTRIBUTION_BUILD_METADATA if metadata is None else metadata
    if not selected.github_fallback_allowed:
        return DOWNLOAD_SOURCE_MODE_PRIMARY
    return _normalize_download_source_mode(value)


DISPLAY_NAME = _display_name_for_build()
REPO_OWNER = "Thankyou-Cheems"
REPO_NAME = "Bomana"
PROJECT_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"
DEFAULT_CHANNEL = "Standard"
PUBLIC_FALLBACK_CHANNEL = "Standard"
APP_DIR_NAME = install_txn.APP_DIR_NAME
APP_PREVIOUS_DIR_NAME = install_txn.APP_PREVIOUS_DIR_NAME
APP_BACKUP_DIR_NAME = install_txn.APP_BACKUP_DIR_NAME
APP_CHANNELS_DIR_NAME = install_txn.APP_CHANNELS_DIR_NAME
STATE_FILE_NAME = "launcher_state.json"
LOG_FILE_NAME = "launcher.log"
INSTALL_ID_FILE_NAME = ".bomana_install_id"
UPDATE_LOCK_FILE_NAME = install_txn.UPDATE_LOCK_FILE_NAME
UPDATE_LOCK_STALE_SEC = install_txn.UPDATE_LOCK_STALE_SEC
TEMP_META_FILE_NAME = ".bomana_temp_meta.json"
LAUNCHER_UPDATE_RESULT_FILE_NAME = ".bomana_launcher_update_result.json"
LAUNCHER_SELF_UPDATE_WORKDIR_PREFIX = "bomana_launcher_update_"
LAUNCHER_SELF_UPDATE_TEMP_STALE_SEC = 3 * 24 * 60 * 60
DOWNLOAD_DIR_ENV_NAME = "BOMANA_LAUNCHER_DOWNLOAD_DIR"
DOWNLOAD_DIR_NAME = "downloads"
USER_DOWNLOADS_APP_DIR_NAME = "Bomana"
LEGACY_LAUNCHER_SELF_UPDATE_FILES = (
    "BomanaLauncher_update.new.exe",
    "BomanaLauncher_backup.old.exe",
    "bomana_update_launcher_apply.ps1",
)
DEFAULT_ENTRYPOINT = "Bomana.pyw"
NET_TIMEOUT_SEC = 8.0
PRIMARY_TIMEOUT_SEC = 4.0
PRIMARY_RETRY_TIMEOUT_SEC = 8.0
UA = f"BomanaLauncher/{LAUNCHER_VERSION}"
PRIMARY_UPDATE_BASE_URL = _launcher_distribution_build.resolve_runtime_base_url(
    os.environ.get("BOMANA_UPDATE_BASE_URL"),
    metadata=_DISTRIBUTION_BUILD_METADATA,
)
PRIMARY_VERSION_API_PATH = "/api/v1/version"
PRIMARY_LAUNCHER_API_PATH = "/api/v1/launcher"
PRIMARY_EVENT_API_PATH = "/api/v1/event"
PRIMARY_DISTRIBUTION_DESCRIPTOR_PATH = "/distribution-descriptor.json"
PRIMARY_TERRAIN_MANIFEST_PATH = "/downloads/terrain/terrain_manifest.json"
PRIMARY_TERRAIN_CATALOG_PATH = "/downloads/terrain/terrain_catalog.json"
PRIMARY_TERRAIN_OBJECTS_PATH = "/downloads/terrain/objects/"
CHEEMSPAY_STORE_URL = f"{CHEEMSPAY_BASE_URL.rstrip('/')}/"
GITHUB_TERRAIN_RELEASE_TAG = os.environ.get(
    "BOMANA_TERRAIN_RELEASE_TAG",
    "terrain-v1",
).strip()
# 默认优先使用国内服务分发下载包；只有显式关闭时才回退为“仅版本检查”。
PRIMARY_ALLOW_PACKAGE_DOWNLOAD = (
    True
    if not _DISTRIBUTION_BUILD_METADATA.github_fallback_allowed
    else os.environ.get("BOMANA_PRIMARY_ALLOW_PACKAGE_DOWNLOAD", "1").strip().lower()
    not in ("0", "false", "no", "off")
)
BRANDING_ICON_FILE = "bomana/assets/branding/app.ico"
BRANDING_SPONSOR_FILE = "bomana/assets/branding/sponsor_wechat.png"

RELEASES_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/latest"
OFFICIAL_SITE_URL = "https://bomana.ruikang.wang/"
_USE_SYSTEM_PROXY = True
_URL_OPENERS: Dict[str, Any] = {}
_PROXY_MODE_LOCAL = threading.local()
DEFAULT_WEB_DASHBOARD_AUTOSTART = True
DEFAULT_WEB_DASHBOARD_AUTO_OPEN = False
DEFAULT_WEB_DASHBOARD_LAN_ENABLED = False
_PENDING_WEB_DASHBOARD_AUTOSTART = DEFAULT_WEB_DASHBOARD_AUTOSTART
_PENDING_WEB_DASHBOARD_AUTO_OPEN = DEFAULT_WEB_DASHBOARD_AUTO_OPEN
_PENDING_WEB_DASHBOARD_LAN_ENABLED = DEFAULT_WEB_DASHBOARD_LAN_ENABLED
_PENDING_DISPLAYED_RECOVERY_WARNING = ""
_APP_HOST_ACTIVE = threading.Event()
_FAKE_IP_NETWORKS = (
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("100.64.0.0/10"),
)

_CHANNEL_MAP = dict(_EDITION_CHANNEL_ALIASES)

CHANNEL_DISPLAY_NAMES = dict(_EDITION_CHANNEL_DISPLAY_NAMES)

_THEME = {
    "BG": "#10151d",
    "CARD": "#1a2330",
    "CARD_ALT": "#131b25",
    "CARD_SOFT": "#202b39",
    "BORDER": "#354258",
    "SEPARATOR": "#2a3648",
    "TEXT": "#f2f6fb",
    "TEXT_DIM": "#bac7d8",
    "TEXT_MUTED": "#7f8da0",
    "BLUE": "#5ab0ff",
    "GREEN": "#6ed081",
    "YELLOW": "#f2c14e",
    "RED": "#ff6b6b",
    "ORANGE": "#ff9a52",
}

_LAUNCHER_SPINNER_FRAMES = ("|", "/", "-", "\\")

CHANNEL_DETAILS = {
    channel: dict(details) for channel, details in _EDITION_CHANNEL_DETAILS.items()
}

WEB_COCKPIT_CHANNELS = frozenset(_EDITION_WEB_COCKPIT_CHANNELS)

require_minimum_version(
    LAUNCHER_VERSION,
    MIN_SUPPORTED_LAUNCHER_VERSION,
    identity_name="启动器版本",
)


def _strict_saved_bool(state: Dict[str, Any], key: str, default: bool) -> bool:
    value = state.get(key, default)
    return value if isinstance(value, bool) else default


def _channel_supports_web_cockpit(channel: object) -> bool:
    return _normalize_channel(channel) in WEB_COCKPIT_CHANNELS


def _effective_web_preferences_for_channel(
    channel: object,
    autostart: bool,
    auto_open: bool,
    lan_enabled: bool,
) -> tuple[bool, bool, bool, bool]:
    """Return effective Web prefs and whether a degradation notice is needed.

    The fourth element is True when the user requested Web on a channel that
    does not ship the cockpit (prefs stay saved, but launch handoff forces off).
    It is an internal degradation flag; public-channel startup remains silent.
    """
    if not all(isinstance(value, bool) for value in (autostart, auto_open, lan_enabled)):
        raise TypeError("Web launch preferences must be bools")
    if lan_enabled:
        autostart = True
    if not autostart:
        lan_enabled = False
    if _channel_supports_web_cockpit(channel):
        return autostart, auto_open, lan_enabled, False
    degraded = bool(autostart or auto_open or lan_enabled)
    return False, False, False, degraded


def _web_cockpit_degradation_message(channel: object) -> str:
    ch = _normalize_channel(channel) or str(channel or "")
    return (
        f"当前通道（{_channel_display_name(ch)}）的应用包不包含网页驾驶舱。\n\n"
        "启动器中已勾选的「随 App 启动网页 / 启动后打开本机页面 / 局域网」"
        "仅在超级爆弹版生效；本次启动将忽略这些选项。\n\n"
        "偏好设置仍会保留，切换回超级爆弹版后可继续使用。"
    )


_SUBSCRIPTION_REASON_COPY = {
    SubscriptionAccessReason.MISSING_RECEIPT: "尚未登录 CheemsPay 或本机没有订阅收据",
    SubscriptionAccessReason.INVALID_RECEIPT: "本机订阅收据无效，请重新登录",
    SubscriptionAccessReason.RECEIPT_EXPIRED: "离线订阅收据已过期，请联网刷新",
    SubscriptionAccessReason.ENTITLEMENT_EXPIRED: "超级爆弹版订阅已到期",
    SubscriptionAccessReason.WRONG_DEVICE: "订阅收据与本机设备身份不匹配",
    SubscriptionAccessReason.WRONG_APP: "订阅收据不属于 Bomana",
    SubscriptionAccessReason.MISSING_FEATURE: "当前权益不包含超级爆弹版",
}


def _subscription_access_copy(decision: SubscriptionAccessDecision) -> str:
    if decision.allowed and decision.receipt is not None:
        expiry = decision.receipt.service_expires_at.astimezone().strftime("%Y-%m-%d %H:%M")
        return f"CheemsPay 已授权 · 订阅到期 {expiry}"
    return _SUBSCRIPTION_REASON_COPY.get(decision.reason, "超级爆弹版需要有效订阅")


def _set_pending_web_preferences(
    autostart: bool,
    auto_open: bool,
    lan_enabled: bool,
) -> None:
    if not all(isinstance(value, bool) for value in (autostart, auto_open, lan_enabled)):
        raise TypeError("Web launch preferences must be bools")
    if lan_enabled:
        autostart = True
    if not autostart:
        lan_enabled = False
    global _PENDING_WEB_DASHBOARD_AUTOSTART
    global _PENDING_WEB_DASHBOARD_AUTO_OPEN
    global _PENDING_WEB_DASHBOARD_LAN_ENABLED
    _PENDING_WEB_DASHBOARD_AUTOSTART = autostart
    _PENDING_WEB_DASHBOARD_AUTO_OPEN = auto_open
    _PENDING_WEB_DASHBOARD_LAN_ENABLED = lan_enabled


def _set_pending_recovery_warning(warning: object) -> None:
    global _PENDING_DISPLAYED_RECOVERY_WARNING
    _PENDING_DISPLAYED_RECOVERY_WARNING = str(warning or "").strip()


def _launcher_meets_minimum(minimum: object) -> bool:
    try:
        require_minimum_version(
            LAUNCHER_VERSION,
            minimum,
            identity_name="启动器版本",
        )
    except VersionCompatibilityError:
        return False
    return True


def _strict_signed_app_versions(
    manifest: Dict[str, Any],
    *,
    label: str,
) -> Tuple[str, str]:
    _verify_release_manifest_signature(
        manifest,
        manifest_label=label,
        expected_kind="app",
    )
    return (
        require_minimum_version(
            manifest.get("app_version"),
            MIN_SUPPORTED_APP_VERSION,
            identity_name="已验证签名清单应用版本",
        ),
        require_minimum_version(
            manifest.get("min_launcher_version"),
            MIN_SUPPORTED_LAUNCHER_VERSION,
            identity_name="已验证签名清单最低启动器版本",
        ),
    )


def _strict_signed_launcher_version(manifest: Dict[str, Any], *, label: str) -> str:
    _verify_release_manifest_signature(
        manifest,
        manifest_label=label,
        expected_kind="launcher",
    )
    return require_minimum_version(
        manifest.get("launcher_version"),
        MIN_SUPPORTED_LAUNCHER_VERSION,
        identity_name="已验证签名清单启动器版本",
    )


def _strict_signed_terrain_manifest(
    manifest: Dict[str, Any],
    *,
    label: str,
) -> _launcher_terrain_store.TerrainManifest:
    _verify_release_manifest_signature(
        manifest,
        manifest_label=label,
        expected_kind="terrain",
    )
    trusted = _launcher_manifest_sources.verified_terrain_manifest_fields(
        manifest,
        label=label,
    )
    return _launcher_terrain_store.parse_terrain_manifest(trusted)


def _strict_signed_terrain_catalog(
    document: Dict[str, Any],
    *,
    metadata: _launcher_distribution_build.DistributionBuildMetadata | None = None,
) -> _launcher_terrain_store.TerrainCatalog:
    selected = _DISTRIBUTION_BUILD_METADATA if metadata is None else metadata
    payload = _launcher_launch_contract.parse_terrain_catalog_contract(
        document,
        public_keys=selected.artifact_public_keys,
    )
    return _launcher_terrain_store.parse_terrain_catalog(payload)


def _terrain_catalog_document(envelope: Dict[str, Any]) -> Dict[str, Any] | None:
    nested = envelope.get("signed_catalog")
    if isinstance(nested, dict):
        return nested
    if envelope.get("kind") == _launcher_launch_contract.TERRAIN_CATALOG_CONTRACT_KIND:
        return envelope
    return None


def _distribution_trust_for_build(
    metadata: _launcher_distribution_build.DistributionBuildMetadata | None = None,
) -> _launcher_launch_contract.DistributionTrust:
    selected = _DISTRIBUTION_BUILD_METADATA if metadata is None else metadata
    factory = (
        _launcher_launch_contract.DistributionTrust.test
        if selected.isolated_test
        else _launcher_launch_contract.DistributionTrust.production
    )
    return factory(selected.artifact_public_keys)


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _resource_path(filename: str) -> Path:
    """Resolve resource path for source mode and PyInstaller onefile mode."""
    try:
        bundle_root = Path(sys._MEIPASS)
        candidate = bundle_root / filename
        if candidate.exists():
            return candidate
    except Exception:
        pass
    return _base_dir() / filename


def _is_frozen_launcher() -> bool:
    return bool(getattr(sys, "frozen", False)) and bool(str(getattr(sys, "executable", "")).strip())


def _has_config_marker(base: Path) -> bool:
    return (base / "bomana" / "config" / "__init__.py").exists()


def _is_source_test_run(base: Path) -> bool:
    if _is_frozen_launcher():
        return False
    return (base / DEFAULT_ENTRYPOINT).exists() and _has_config_marker(base)


def _app_runtime_dir(base: Path, channel: object | None = None) -> Path:
    if _is_source_test_run(base):
        return base
    target = install_txn.app_slot_dir(base, channel)
    if channel is None or target.exists():
        return target
    legacy = install_txn.app_slot_dir(base)
    if legacy.exists():
        legacy_channel = install_txn.read_app_channel_identity(legacy)
        if not legacy_channel or legacy_channel == _normalize_channel(channel):
            return legacy
    return target


def _previous_app_dir(base: Path, channel: object | None = None) -> Path:
    target = install_txn.previous_app_slot_dir(base, channel)
    if channel is None or target.exists():
        return target
    legacy = install_txn.previous_app_slot_dir(base)
    if legacy.exists():
        legacy_channel = install_txn.read_app_channel_identity(legacy)
        if not legacy_channel or legacy_channel == _normalize_channel(channel):
            return legacy
    return target


def _apply_window_icon(window: tk.Misc) -> None:
    icon_path = _resource_path(BRANDING_ICON_FILE)
    if not icon_path.exists():
        return
    try:
        window.iconbitmap(default=str(icon_path))
    except Exception:
        pass


def _place_child_dialog(
    dialog: tk.Toplevel,
    parent: tk.Misc,
    *,
    width: int,
    height: int,
    min_width: int,
    min_height: int,
    screen_padding: int = 48,
) -> None:
    """Size and center a child dialog while keeping it on the visible screen."""

    parent.update_idletasks()
    screen_width = max(1, int(dialog.winfo_screenwidth()))
    screen_height = max(1, int(dialog.winfo_screenheight()))
    available_width = max(1, screen_width - (screen_padding * 2))
    available_height = max(1, screen_height - (screen_padding * 2))
    actual_min_width = min(int(min_width), available_width)
    actual_min_height = min(int(min_height), available_height)
    actual_width = min(max(int(width), actual_min_width), available_width)
    actual_height = min(max(int(height), actual_min_height), available_height)
    dialog.minsize(actual_min_width, actual_min_height)

    parent_width = max(1, int(parent.winfo_width()))
    parent_height = max(1, int(parent.winfo_height()))
    x = int(parent.winfo_rootx()) + (parent_width - actual_width) // 2
    y = int(parent.winfo_rooty()) + (parent_height - actual_height) // 2
    x = min(max(0, x), max(0, screen_width - actual_width))
    y = min(max(0, y), max(0, screen_height - actual_height))
    dialog.geometry(f"{actual_width}x{actual_height}+{x}+{y}")


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _base_path_key(base: Path) -> str:
    try:
        base_text = str(base.resolve())
    except Exception:
        base_text = str(base)
    return hashlib.sha256(base_text.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _fallback_data_root(base: Path) -> Path:
    env_root = os.environ.get("BOMANA_LAUNCHER_DATA_DIR", "").strip()
    if env_root:
        return Path(env_root).expanduser()
    appdata = os.environ.get("LOCALAPPDATA", "").strip() or os.environ.get("APPDATA", "").strip()
    if appdata:
        root = Path(appdata) / "Bomana" / "launcher"
    else:
        root = Path.home() / ".bomana" / "launcher"
    return root / _base_path_key(base)


def _can_write_dir(path: Path) -> bool:
    probe: Optional[Path] = None
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".bomana_write_probe_{os.getpid()}_{time.monotonic_ns()}"
        with probe.open("w", encoding="utf-8") as f:
            f.write("ok")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        if probe is not None:
            try:
                probe.unlink(missing_ok=True)
            except Exception:
                pass
        return False


def _launcher_data_root(base: Path) -> Path:
    env_root = os.environ.get("BOMANA_LAUNCHER_DATA_DIR", "").strip()
    if env_root:
        root = Path(env_root).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        return root
    if _can_write_dir(base):
        return base
    root = _fallback_data_root(base)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _user_downloads_dir() -> Path:
    profile = os.environ.get("USERPROFILE", "").strip()
    if profile:
        return Path(profile) / "Downloads" / USER_DOWNLOADS_APP_DIR_NAME
    return Path.home() / "Downloads" / USER_DOWNLOADS_APP_DIR_NAME


def _unique_paths(paths: Tuple[Path, ...]) -> Tuple[Path, ...]:
    return _launcher_download_cache.unique_paths(paths)


def _download_dir_candidates(base: Path) -> Tuple[Path, ...]:
    return _launcher_download_cache.download_dir_candidates(
        base,
        env_root=os.environ.get(DOWNLOAD_DIR_ENV_NAME, "").strip(),
        user_downloads_dir=_user_downloads_dir,
        launcher_data_root=_launcher_data_root,
        temp_root=Path(tempfile.gettempdir()),
        base_path_key=_base_path_key,
        download_dir_name=DOWNLOAD_DIR_NAME,
    )


def _launcher_download_dir(base: Path) -> Path:
    return _launcher_download_cache.launcher_download_dir(
        base,
        candidates=_download_dir_candidates,
        can_write_dir=_can_write_dir,
    )


def _download_cache_filename(
    prefix: str,
    remote_version: str,
    artifact_name: str,
    checksum: str,
    suffix: str,
) -> str:
    return _launcher_download_cache.download_cache_filename(
        prefix,
        remote_version,
        artifact_name,
        checksum,
        suffix,
        sha256_bytes=_sha256_bytes,
    )


def _ps_string(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("win") and hasattr(os, "startfile"):
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)], close_fds=True)
        return
    subprocess.Popen(["xdg-open", str(path)], close_fds=True)


def _windows_system_dir() -> Path:
    kernel32 = getattr(getattr(ctypes, "windll", None), "kernel32", None)
    if kernel32 is None:
        raise RuntimeError("无法定位 Windows 系统目录")

    get_system_directory = kernel32.GetSystemDirectoryW
    get_system_directory.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    get_system_directory.restype = ctypes.c_uint

    buffer = ctypes.create_unicode_buffer(260)
    length = int(get_system_directory(buffer, len(buffer)))
    if length > len(buffer):
        buffer = ctypes.create_unicode_buffer(length + 1)
        length = int(get_system_directory(buffer, len(buffer)))
    if length <= 0:
        raise RuntimeError("无法定位 Windows 系统目录")
    return Path(buffer.value).resolve()


def _system_windows_powershell_exe() -> Path:
    powershell = _windows_system_dir() / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not powershell.is_file():
        raise RuntimeError(f"无法定位系统 PowerShell：{powershell}")
    return powershell


def _data_path(base: Path, filename: str) -> Path:
    return _launcher_data_root(base) / filename


def _data_read_candidates(base: Path, filename: str) -> Tuple[Path, ...]:
    paths = [_data_path(base, filename)]
    legacy = base / filename
    try:
        if legacy.resolve() != paths[0].resolve():
            paths.append(legacy)
    except Exception:
        if legacy != paths[0]:
            paths.append(legacy)
    return tuple(paths)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as f:
        tmp_path = Path(f.name)
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    try:
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass


def _append_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, text.encode("utf-8", errors="replace"))
    finally:
        os.close(fd)


def _write_json_data_file(base: Path, filename: str, data: Dict[str, Any]) -> None:
    _atomic_write_text(
        _data_path(base, filename),
        json.dumps(data, ensure_ascii=False, indent=2),
    )


def _read_json_data_file(base: Path, filename: str) -> Dict[str, Any]:
    for path in _data_read_candidates(base, filename):
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception as exc:
            try:
                _append_text_atomic(
                    _data_path(base, LOG_FILE_NAME),
                    f"[{_now_utc_iso()}] 读取 {filename} 失败，已保留原文件 {path}：{exc}\n",
                )
            except Exception:
                pass
            continue
    return {}


def _log(base: Path, msg: str) -> None:
    try:
        _append_text_atomic(_data_path(base, LOG_FILE_NAME), f"[{_now_utc_iso()}] {msg}\n")
    except Exception:
        pass


def _show_error(title: str, msg: str) -> None:
    try:
        Win32.enable_dpi()
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, msg)
        root.destroy()
    except tk.TclError:
        pass


def _show_warning(title: str, msg: str) -> bool:
    root = None
    try:
        Win32.enable_dpi()
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(title, msg)
        return True
    except tk.TclError:
        return False
    finally:
        if root is not None:
            try:
                root.destroy()
            except tk.TclError:
                pass


def _show_handoff_recovery_warning(warning: str) -> bool:
    return _show_warning(
        f"{DISPLAY_NAME} 安装恢复警告",
        (f"{warning}\n\n有效的本地 App 将继续启动；请在退出后处理上述安装槽问题。"),
    )


def _set_use_system_proxy(enabled: bool) -> None:
    global _USE_SYSTEM_PROXY
    _USE_SYSTEM_PROXY = bool(enabled)


def _current_use_system_proxy() -> bool:
    override = getattr(_PROXY_MODE_LOCAL, "use_system_proxy", None)
    if override is not None:
        return bool(override)
    return bool(_USE_SYSTEM_PROXY)


def _set_thread_proxy_override(enabled: Optional[bool]) -> None:
    if enabled is None:
        try:
            delattr(_PROXY_MODE_LOCAL, "use_system_proxy")
        except AttributeError:
            pass
        return
    _PROXY_MODE_LOCAL.use_system_proxy = bool(enabled)


class _RejectRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _get_url_opener(
    use_system_proxy: Optional[bool] = None,
    *,
    allow_redirects: bool = True,
) -> Any:
    use_proxy = _current_use_system_proxy() if use_system_proxy is None else bool(use_system_proxy)
    key = f"{'proxy' if use_proxy else 'direct'}:{'redirect' if allow_redirects else 'fixed'}"
    opener = _URL_OPENERS.get(key)
    if opener is not None:
        return opener

    handlers = [HTTPHandler(), HTTPSHandler(context=_ssl_context)]
    if not allow_redirects:
        handlers.append(_RejectRedirectHandler())
    if use_proxy:
        handlers.append(ProxyHandler())
    else:
        handlers.append(ProxyHandler({}))
    opener = build_opener(*handlers)
    _URL_OPENERS[key] = opener
    return opener


def _open_url(
    req: Request,
    timeout: float,
    use_system_proxy: Optional[bool] = None,
    *,
    allow_redirects: bool = True,
):
    opener = _get_url_opener(
        use_system_proxy=use_system_proxy,
        allow_redirects=allow_redirects,
    )
    return opener.open(req, timeout=timeout)


def _resolved_ipv4_addrs(hostname: str) -> Tuple[str, ...]:
    host = str(hostname or "").strip()
    if not host:
        return ()
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)
    except Exception:
        return ()
    addrs = []
    for info in infos:
        try:
            addr = str(info[4][0]).strip()
        except Exception:
            addr = ""
        if addr and (addr not in addrs):
            addrs.append(addr)
    return tuple(addrs)


def _is_fake_ip_address(address: str) -> bool:
    try:
        ip_obj = ipaddress.ip_address(str(address).strip())
    except Exception:
        return False
    return any(ip_obj in network for network in _FAKE_IP_NETWORKS)


def _primary_network_hint(api_url: str) -> str:
    host = str(urlparse(api_url).hostname or "").strip()
    if not host:
        return ""
    addrs = _resolved_ipv4_addrs(host)
    fake_addrs = [addr for addr in addrs if _is_fake_ip_address(addr)]
    if not fake_addrs:
        return ""
    fake_text = ", ".join(fake_addrs)
    return (
        f"检测到更新域名 {host} 被解析到代理/TUN fake-ip ({fake_text})。"
        "这通常是 Clash/Mihomo TUN fake-ip 模式导致的，不是腾讯云文件缺失。"
        "请切换 GitHub 下载源，或让该域名走真实 DNS/关闭 fake-ip 后再试。"
    )


def _fetch_bytes(
    url: str,
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
    cancel_cb: Optional[Callable[[], bool]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout_sec: Optional[float] = None,
    max_bytes: Optional[int] = None,
    allow_redirects: bool = True,
) -> bytes:
    with tempfile.TemporaryDirectory(prefix="bomana_fetch_") as tmp:
        dest = Path(tmp) / "download.bin"
        _download_to_file(
            url,
            dest,
            progress_cb=progress_cb,
            cancel_cb=cancel_cb,
            headers=headers,
            timeout_sec=timeout_sec,
            resume=False,
            max_bytes=max_bytes,
            allow_redirects=allow_redirects,
        )
        return dest.read_bytes()


def _response_status(resp: Any) -> int:
    for attr in ("status", "code"):
        value = getattr(resp, attr, None)
        if value is not None:
            try:
                return int(value)
            except Exception:
                pass
    try:
        return int(resp.getcode())
    except Exception:
        return 200


def _parse_total_from_content_range(value: str) -> Optional[int]:
    m = re.search(r"/(\d+|\*)\s*$", str(value or "").strip())
    if not m or m.group(1) == "*":
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _download_to_file(
    url: str,
    dest: Path,
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
    cancel_cb: Optional[Callable[[], bool]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout_sec: Optional[float] = None,
    resume: bool = True,
    max_bytes: Optional[int] = None,
    allow_redirects: bool = True,
) -> Path:
    if max_bytes is not None and max_bytes < 0:
        raise ValueError("max_bytes must not be negative")
    req_headers = {
        "User-Agent": UA,
        "Accept": "application/json, application/vnd.github+json, */*",
    }
    if headers:
        req_headers.update(headers)

    dest.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest.with_name(f"{dest.name}.part")
    resume_from = 0
    if resume and part_path.exists():
        try:
            resume_from = max(0, part_path.stat().st_size)
        except Exception:
            resume_from = 0
    if max_bytes is not None and resume_from > max_bytes:
        part_path.unlink(missing_ok=True)
        raise RuntimeError("下载内容超过允许大小")
    if resume_from > 0:
        req_headers["Range"] = f"bytes={resume_from}-"

    req = Request(
        url,
        headers=req_headers,
    )
    open_kwargs = {} if allow_redirects else {"allow_redirects": False}
    with _open_url(
        req,
        timeout=(timeout_sec if timeout_sec is not None else NET_TIMEOUT_SEC),
        **open_kwargs,
    ) as resp:
        status = _response_status(resp)
        append_existing = resume_from > 0 and status == 206
        if resume_from > 0 and not append_existing:
            resume_from = 0
            try:
                part_path.unlink(missing_ok=True)
            except Exception:
                pass

        total: Optional[int] = None
        try:
            content_range = str(resp.headers.get("Content-Range", "")).strip()
            total = _parse_total_from_content_range(content_range)
            if total is None:
                header = resp.headers.get("Content-Length")
                total = int(header) + resume_from if header else None
        except Exception:
            total = None
        if max_bytes is not None and total is not None and total > max_bytes:
            raise RuntimeError("下载内容超过允许大小")

        downloaded = resume_from
        mode = "ab" if append_existing else "wb"
        try:
            with part_path.open(mode) as f:
                while True:
                    if cancel_cb and cancel_cb():
                        raise RuntimeError("已取消当前操作")
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    if max_bytes is not None and downloaded + len(chunk) > max_bytes:
                        raise RuntimeError("下载内容超过允许大小")
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(downloaded, total)
                    if cancel_cb and cancel_cb():
                        raise RuntimeError("已取消当前操作")
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            raise

        if progress_cb:
            progress_cb(downloaded, total)
    os.replace(part_path, dest)
    return dest


def _fetch_json(url: str) -> Dict[str, Any]:
    raw = _fetch_bytes(url)
    return json.loads(raw.decode("utf-8"))


def _fetch_json_with_timeout(url: str, timeout_sec: float) -> Dict[str, Any]:
    raw = _fetch_bytes(url, timeout_sec=timeout_sec)
    return json.loads(raw.decode("utf-8"))


def _http_error_detail(err: HTTPError) -> str:
    detail = ""
    try:
        raw = err.read()
        if raw:
            text = raw.decode("utf-8", errors="replace").strip()
            if text:
                try:
                    payload = json.loads(text)
                except Exception:
                    payload = None
                if isinstance(payload, dict):
                    for key in ("detail", "message", "error"):
                        value = str(payload.get(key, "")).strip()
                        if value:
                            detail = value
                            break
                if not detail:
                    detail = text
    except Exception:
        detail = ""
    if detail:
        return detail
    return str(getattr(err, "reason", "") or getattr(err, "msg", "") or err)


def _fetch_primary_json_payload(
    api_url: str, params: Dict[str, str], timeout_sec: float
) -> Dict[str, Any]:
    request_url = f"{api_url}?{urlencode(params)}"
    try:
        payload = _fetch_json_with_timeout(request_url, timeout_sec)
    except HTTPError as err:
        raise RuntimeError(f"HTTP {err.code}: {_http_error_detail(err)}") from err
    except URLError as err:
        reason = str(getattr(err, "reason", "") or err).strip()
        hint = _primary_network_hint(api_url)
        message = reason or str(err)
        if hint:
            message = f"{message}; {hint}"
        raise RuntimeError(message) from err

    if not isinstance(payload, dict):
        raise RuntimeError("国内更新服务返回格式异常")
    return payload


def _fetch_primary_version_payload(
    version_url: str, params: Dict[str, str], timeout_sec: float
) -> Dict[str, Any]:
    return _fetch_primary_json_payload(version_url, params, timeout_sec)


def _fetch_content_length(url: str, timeout_sec: Optional[float] = None) -> Optional[int]:
    timeout = timeout_sec if timeout_sec is not None else NET_TIMEOUT_SEC
    req = Request(url, method="HEAD", headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with _open_url(req, timeout=timeout) as resp:
            header = resp.headers.get("Content-Length")
            if header:
                value = int(header)
                return value if value >= 0 else None
    except Exception:
        pass

    # Some CDNs reject HEAD; fallback to a 1-byte range request.
    try:
        req2 = Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Range": "bytes=0-0"})
        with _open_url(req2, timeout=timeout) as resp2:
            content_range = str(resp2.headers.get("Content-Range", "")).strip()
            m = re.search(r"/(\d+)$", content_range)
            if m:
                value = int(m.group(1))
                return value if value >= 0 else None
            header2 = resp2.headers.get("Content-Length")
            if header2:
                value = int(header2)
                return value if value >= 0 else None
    except Exception:
        pass
    return None


def _post_json(url: str, payload: Dict[str, Any], timeout_sec: float) -> Dict[str, Any]:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        url,
        data=raw,
        method="POST",
        headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with _open_url(req, timeout=timeout_sec) as resp:
        data = resp.read()
    if not data:
        return {}
    return json.loads(data.decode("utf-8"))


def _detect_channel() -> str:
    env = os.environ.get("BOMANA_CHANNEL", "").strip().lower()
    if env in _CHANNEL_MAP:
        return _CHANNEL_MAP[env]

    exe_name = (
        Path(sys.executable).name if getattr(sys, "frozen", False) else Path(__file__).name
    ).lower()
    for key, value in _CHANNEL_MAP.items():
        if key in exe_name:
            return value
    return DEFAULT_CHANNEL


def _normalize_channel(value: Any) -> str:
    text = str(value or "").strip()
    if text in CHANNEL_DETAILS:
        return text
    mapped = _CHANNEL_MAP.get(text.lower())
    return mapped or ""


def _installed_app_channel(base: Path, channel: object | None = None) -> str:
    """Read the packaged edition marker without importing untrusted app code."""

    if channel is not None:
        return install_txn.read_app_channel_identity(
            _app_runtime_dir(base, _normalize_channel(channel) or channel)
        )
    for candidate in CHANNEL_DETAILS:
        found = install_txn.read_app_channel_identity(_app_runtime_dir(base, candidate))
        if found:
            return found
    return install_txn.read_app_channel_identity(_app_runtime_dir(base))


def _channel_display_name(value: Any) -> str:
    canonical = _normalize_channel(value)
    return CHANNEL_DISPLAY_NAMES.get(canonical, str(value or "").strip())


def _validate_app_manifest_channel(
    manifest: Dict[str, Any], expected_channel: str, label: str
) -> None:
    _launcher_manifest_sources.validate_app_manifest_channel(
        {"channel": _normalize_channel(manifest.get("channel", ""))},
        _normalize_channel(expected_channel),
        label,
    )


def _validate_app_manifest_entrypoint(entrypoint_value: Any, label: str) -> str:
    try:
        return _launcher_manifest_sources.validate_app_manifest_entrypoint(
            entrypoint_value,
            label,
            DEFAULT_ENTRYPOINT,
        )
    except RuntimeError as exc:
        entrypoint = str(entrypoint_value or DEFAULT_ENTRYPOINT).strip() or DEFAULT_ENTRYPOINT
        if "入口文件不受支持" in str(exc):
            raise RuntimeError(f"{label}入口文件不受支持: {entrypoint}") from exc
        raise


def _select_startup_channel(base: Path, detected_channel: str) -> str:
    saved_channel = _normalize_channel(_read_state(base).get("channel", ""))
    return saved_channel or detected_channel


def _app_entrypoint_for_runtime(base: Path, channel: object | None = None) -> str:
    app_dir = _app_runtime_dir(base, channel)
    return install_txn.read_app_entrypoint_identity(app_dir) or DEFAULT_ENTRYPOINT


def _is_local_app_ready(base: Path, channel: object | None = None) -> bool:
    try:
        runtime_dir = _app_runtime_dir(base, channel)
        entrypoint = _app_entrypoint_for_runtime(base, channel)
        install_txn.validate_app_package_root(runtime_dir, entrypoint)
        canonical_channel = install_txn.normalize_app_channel(channel)
        if (
            canonical_channel is not None
            and (runtime_dir / install_txn.INSTALLATION_IDENTITY_FILE_NAME).is_file()
        ):
            install_txn.require_signed_installation_identity(runtime_dir, canonical_channel)
    except Exception:
        return False
    return True


def _is_previous_app_ready(base: Path, channel: object | None = None) -> bool:
    try:
        previous_dir = _previous_app_dir(base, channel)
        entrypoint = install_txn.read_app_entrypoint_identity(previous_dir) or DEFAULT_ENTRYPOINT
        install_txn.validate_app_package_root(previous_dir, entrypoint)
        install_txn.require_compatible_app_version(
            previous_dir,
            identity_name="回退应用版本",
        )
        canonical_channel = install_txn.normalize_app_channel(channel)
        if (
            canonical_channel is not None
            and (previous_dir / install_txn.INSTALLATION_IDENTITY_FILE_NAME).is_file()
        ):
            install_txn.require_signed_installation_identity(previous_dir, canonical_channel)
    except Exception:
        return False
    return True


def _recover_incomplete_install(base: Path) -> str:
    recovery_errors: list[str] = []

    def record_recovery_error(target: Path, message: str) -> None:
        _log(target, message)
        recovery_errors.append(str(message).strip())

    steps = install_txn.InstallTransaction.recover_incomplete_all(
        base,
        log_cb=record_recovery_error,
    )
    if recovery_errors:
        # Keep the user-facing warning focused on the failed recovery slot;
        # a safe legacy migration can be retried on the next launch.
        steps = [step for step in steps if not step.startswith("migrate_")]
    if steps:
        _log(base, f"检测到上次安装未完成，已恢复：{', '.join(steps)}")
    return recovery_errors[-1] if recovery_errors else ""


def _write_state(base: Path, state: Dict[str, Any]) -> None:
    try:
        _write_json_data_file(base, STATE_FILE_NAME, state)
    except Exception:
        pass


def _read_state(base: Path) -> Dict[str, Any]:
    return _read_json_data_file(base, STATE_FILE_NAME)


def _read_temp_meta(base: Path) -> Dict[str, Any]:
    return _read_json_data_file(base, TEMP_META_FILE_NAME)


def _write_temp_meta(base: Path, data: Dict[str, Any]) -> None:
    try:
        _write_json_data_file(base, TEMP_META_FILE_NAME, data)
    except Exception:
        pass


def _cleanup_stale_launcher_self_update_temp(base: Path) -> None:
    temp_root = Path(tempfile.gettempdir())
    cleaned = []
    try:
        for path in temp_root.iterdir():
            if not path.name.startswith(LAUNCHER_SELF_UPDATE_WORKDIR_PREFIX):
                continue
            try:
                age = time.time() - path.stat().st_mtime
            except Exception:
                age = 0
            if age < LAUNCHER_SELF_UPDATE_TEMP_STALE_SEC:
                continue
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                try:
                    path.unlink()
                except Exception:
                    continue
            cleaned.append(path.name)
    except Exception as e:
        _log(base, f"清理启动器自更新临时目录失败：{e}")
        return

    if cleaned:
        detail = ", ".join(cleaned[:5])
        if len(cleaned) > 5:
            detail += " ..."
        _log(base, f"已清理过期启动器自更新临时目录：{detail}")


def _cleanup_legacy_launcher_self_update_files(base: Path) -> None:
    current_target: Optional[Path] = None
    if _is_frozen_launcher():
        try:
            current_target = Path(sys.executable).resolve()
        except Exception:
            current_target = None

    cleaned = []
    for name in LEGACY_LAUNCHER_SELF_UPDATE_FILES:
        path = base / name
        try:
            if current_target is not None and path.exists() and path.resolve() == current_target:
                continue
        except Exception:
            pass
        try:
            path.unlink()
            cleaned.append(name)
        except FileNotFoundError:
            continue
        except Exception:
            continue

    if cleaned:
        _log(base, f"已清理旧版启动器自更新残留文件：{', '.join(cleaned)}")


def _cleanup_temp_files_on_launcher_upgrade(base: Path) -> None:
    meta = _read_temp_meta(base)
    prev_version = str(meta.get("launcher_version", "")).strip()
    should_update_meta = prev_version != LAUNCHER_VERSION
    if prev_version and prev_version != LAUNCHER_VERSION:
        cleaned = []
        lock_path = base / UPDATE_LOCK_FILE_NAME
        lock_active = False
        try:
            if lock_path.exists():
                age = time.time() - lock_path.stat().st_mtime
                lock_active = age < UPDATE_LOCK_STALE_SEC
        except Exception:
            lock_active = True

        if not lock_active:
            try:
                for p in base.iterdir():
                    if p.name.startswith("bomana_update_"):
                        if p.is_dir():
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            try:
                                p.unlink()
                            except Exception:
                                pass
                        cleaned.append(p.name)
            except Exception:
                pass
            if cleaned:
                _log(
                    base,
                    f"检测到启动器升级（v{prev_version} -> v{LAUNCHER_VERSION}），已清理临时文件：{', '.join(cleaned)}",
                )
        else:
            _log(
                base,
                f"检测到启动器升级（v{prev_version} -> v{LAUNCHER_VERSION}），存在进行中的更新任务，暂不清理临时文件。",
            )
            should_update_meta = False

    if should_update_meta:
        _write_temp_meta(
            base,
            {
                "launcher_version": LAUNCHER_VERSION,
                "updated_utc": _now_utc_iso(),
            },
        )


def _consume_launcher_update_result(base: Path) -> str:
    path = next(
        (
            candidate
            for candidate in _data_read_candidates(base, LAUNCHER_UPDATE_RESULT_FILE_NAME)
            if candidate.exists()
        ),
        None,
    )
    if path is None:
        return ""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        _log(base, f"读取启动器自更新结果失败：{e}")
        try:
            path.unlink()
        except Exception:
            pass
        return ""

    visible_notice = ""
    try:
        status = str(payload.get("status", "")).strip().lower()
        version = str(payload.get("target_version", "")).strip()
        message = str(payload.get("message", "")).strip()
        if status == "success":
            notice = _launcher_self_update.visible_update_notice(
                status,
                version,
                LAUNCHER_VERSION,
            )
            if notice:
                visible_notice = notice
                _log(base, f"启动器自更新成功：{notice} {message}".strip())
            else:
                _log(
                    base,
                    f"启动器自更新结果版本不匹配：helper={version or '未知'}，当前={LAUNCHER_VERSION}",
                )
        elif status == "error":
            detail = message or "未知错误"
            _log(base, f"启动器自更新失败：{detail}")
            _show_error(
                f"{DISPLAY_NAME} 启动器更新失败",
                f"上一次启动器自更新未完成。\n错误：{detail}\n详细信息请查看 launcher.log。",
            )
    finally:
        try:
            path.unlink()
        except Exception:
            pass
    return visible_notice


def _load_or_create_install_id(base: Path) -> str:
    path = _data_path(base, INSTALL_ID_FILE_NAME)
    try:
        for candidate in _data_read_candidates(base, INSTALL_ID_FILE_NAME):
            if not candidate.exists():
                continue
            text = candidate.read_text(encoding="utf-8").strip().lower()
            if re.fullmatch(r"[0-9a-f]{32}", text):
                return text
    except Exception:
        pass

    install_id = uuid.uuid4().hex
    try:
        _atomic_write_text(path, install_id)
    except Exception:
        pass
    return install_id


def _read_machine_guid() -> str:
    try:
        import winreg  # type: ignore

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        return str(guid).strip()
    except Exception:
        return ""


def _build_client_identity(base: Path) -> Dict[str, str]:
    install_id = _load_or_create_install_id(base)
    machine_guid = _read_machine_guid()
    if machine_guid:
        raw = f"{DISPLAY_NAME}|machine|{machine_guid}"
    else:
        machine_name = os.environ.get("COMPUTERNAME", "").strip()
        raw = f"{DISPLAY_NAME}|fallback|{machine_name}|{install_id}"
    device_id = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:32]
    return {
        "install_id": install_id,
        "device_id": device_id,
    }


def _latest_release_url() -> str:
    return f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"


def _releases_list_url(limit: int = 20) -> str:
    safe_limit = max(1, min(int(limit), 100))
    return f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases?per_page={safe_limit}"


def _attempt_primary_request(
    base: Path,
    request_name: str,
    start_detail: str,
    fetcher: Callable[[float], Dict[str, Any]],
    status_cb: Optional[Callable[[str, str, Optional[float], str], None]] = None,
) -> Dict[str, Any]:
    def notify(
        title: str,
        detail: str = "",
        progress: Optional[float] = None,
        level: str = "info",
    ) -> None:
        if status_cb:
            status_cb(title, detail, progress, level)

    notify("正在检查更新", start_detail, None, "info")
    original_proxy_mode = bool(_USE_SYSTEM_PROXY)
    attempts = [
        (original_proxy_mode, PRIMARY_TIMEOUT_SEC),
        (original_proxy_mode, PRIMARY_RETRY_TIMEOUT_SEC),
        ((not original_proxy_mode), PRIMARY_RETRY_TIMEOUT_SEC),
    ]
    tried_modes = []
    try:
        last_exc: Optional[Exception] = None
        for use_proxy, timeout_sec in attempts:
            key = (use_proxy, timeout_sec)
            if key in tried_modes:
                continue
            tried_modes.append(key)
            _set_thread_proxy_override(use_proxy)
            mode_name = "system-proxy" if use_proxy else "direct"
            try:
                result = fetcher(timeout_sec)
                _log(
                    base,
                    f"{request_name}成功(mode={mode_name}, timeout={timeout_sec:.1f}s)",
                )
                return result
            except Exception as e:
                last_exc = e
                _log(
                    base,
                    f"{request_name}失败(mode={mode_name}, timeout={timeout_sec:.1f}s)：{e}",
                )
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"{request_name}失败")
    finally:
        _set_thread_proxy_override(None)


def _authorized_subscriber_artifact(
    provider: Callable[[str], AuthorizedArtifactRequest],
    resource: str,
) -> AuthorizedArtifactRequest:
    access = provider(resource)
    if access.resource != resource:
        raise RuntimeError("CheemsPay 返回了不匹配的订阅制品授权")
    return access


def _fetch_subscriber_json(
    provider: Callable[[str], AuthorizedArtifactRequest],
    resource: str,
    *,
    label: str,
) -> Dict[str, Any]:
    access = _authorized_subscriber_artifact(provider, resource)
    raw = _fetch_bytes(
        access.download_url,
        headers={"Accept": "application/json", **access.headers()},
        max_bytes=1024 * 1024,
        allow_redirects=False,
    )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label}不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label}格式无效")
    return payload


def _fetch_manifest_from_subscriber(
    provider: Callable[[str], AuthorizedArtifactRequest],
) -> Dict[str, Any]:
    manifest = _fetch_subscriber_json(
        provider,
        _subscriber_artifacts.APP_MANIFEST_RESOURCE,
        label="CheemsPay 订阅应用清单",
    )
    remote_version, min_launcher_version = _strict_signed_app_versions(
        manifest,
        label="CheemsPay 订阅应用清单 ",
    )
    trusted = _launcher_manifest_sources.verified_app_manifest_fields(
        manifest,
        channel="Enhanced",
        label="CheemsPay 订阅应用清单 ",
        default_entrypoint=DEFAULT_ENTRYPOINT,
    )
    package_asset = str(trusted["package_asset"])
    changelog_asset = str(trusted["changelog_asset"])
    return {
        "remote_version": remote_version,
        "min_launcher_version": min_launcher_version,
        "signed_manifest": manifest,
        "package_resource": _subscriber_artifacts.app_asset_resource(package_asset),
        "package_sha256": str(trusted["package_sha256"]),
        "package_asset": package_asset,
        "entrypoint": str(trusted["entrypoint"]),
        "package_size": None,
        "changelog_resource": _subscriber_artifacts.app_asset_resource(changelog_asset),
        "changelog_asset": changelog_asset,
        "changelog_sha256": str(trusted["changelog_sha256"]),
        "source_name": "CheemsPay 订阅制品网关",
    }


def _fetch_terrain_manifest_from_subscriber(
    provider: Callable[[str], AuthorizedArtifactRequest],
) -> Dict[str, Any]:
    manifest = _fetch_subscriber_json(
        provider,
        _subscriber_artifacts.TERRAIN_MANIFEST_RESOURCE,
        label="CheemsPay 订阅地形清单",
    )
    if manifest.get("kind") == _launcher_launch_contract.TERRAIN_CATALOG_CONTRACT_KIND:
        return _terrain_catalog_result(
            manifest,
            label="CheemsPay 订阅地形目录 ",
            source_name="CheemsPay 订阅制品网关",
            object_base_url="",
        )
    return _terrain_manifest_result(
        manifest,
        label="CheemsPay 订阅地形清单 ",
        source_name="CheemsPay 订阅制品网关",
        object_base_urls=(),
    )


def _manifest_from_github_release(release: Dict[str, Any], channel: str) -> Dict[str, Any]:
    assets = release.get("assets", [])
    tag_name = str(release.get("tag_name", "")).strip()

    manifest_name = f"manifest_{channel}.json"
    manifest_asset = _find_asset(assets, manifest_name)
    if not manifest_asset:
        raise RuntimeError(f"未找到发布清单: {manifest_name}")

    manifest_url = str(manifest_asset.get("browser_download_url", "")).strip()
    if not manifest_url:
        raise RuntimeError("发布清单下载地址无效")

    manifest = _fetch_json(manifest_url)
    remote_version, min_launcher_version = _strict_signed_app_versions(
        manifest,
        label=f"{manifest_name} ",
    )
    trusted = _launcher_manifest_sources.verified_app_manifest_fields(
        manifest,
        channel=channel,
        label=f"{manifest_name} ",
        default_entrypoint=DEFAULT_ENTRYPOINT,
    )
    package_asset = str(trusted["package_asset"])
    package_sha256 = str(trusted["package_sha256"])
    entrypoint = str(trusted["entrypoint"])

    app_asset = _find_asset(assets, package_asset)
    if not app_asset:
        raise RuntimeError(f"未找到应用包: {package_asset}")
    package_url = str(app_asset.get("browser_download_url", "")).strip()
    if not package_url:
        raise RuntimeError("应用包下载地址无效")
    package_size = app_asset.get("size", None)
    changelog_asset = str(trusted["changelog_asset"])
    changelog_release_asset = _find_asset(assets, changelog_asset)
    if not changelog_release_asset:
        raise RuntimeError(f"未找到更新日志: {changelog_asset}")
    changelog_url = str(changelog_release_asset.get("browser_download_url", "")).strip()
    if not changelog_url:
        raise RuntimeError("更新日志下载地址无效")

    return {
        "remote_version": remote_version,
        "min_launcher_version": min_launcher_version,
        "signed_manifest": manifest,
        "package_url": package_url,
        "package_sha256": package_sha256,
        "package_asset": package_asset,
        "entrypoint": entrypoint,
        "package_size": package_size,
        "changelog_url": changelog_url,
        "changelog_asset": changelog_asset,
        "changelog_sha256": str(trusted["changelog_sha256"]),
        "source_name": (f"GitHub ({tag_name})" if tag_name else "GitHub"),
    }


def _launcher_manifest_from_github_release(release: Dict[str, Any]) -> Dict[str, Any]:
    assets = release.get("assets", [])
    tag_name = str(release.get("tag_name", "")).strip()
    manifest_asset = _find_asset(assets, "launcher_manifest.json")
    if not manifest_asset:
        raise RuntimeError("未找到启动器发布清单")
    manifest_url = str(manifest_asset.get("browser_download_url", "")).strip()
    if not manifest_url:
        raise RuntimeError("启动器发布清单下载地址无效")
    manifest = _fetch_json(manifest_url)
    remote_version = _strict_signed_launcher_version(
        manifest,
        label="launcher_manifest.json ",
    )
    trusted = _launcher_manifest_sources.verified_launcher_manifest_fields(
        manifest,
        label="launcher_manifest.json ",
    )
    asset_name = str(trusted["package_asset"])

    launcher_asset = _find_asset(assets, asset_name)
    if not launcher_asset:
        raise RuntimeError(f"未找到启动器安装包: {asset_name}")
    package_url = str(launcher_asset.get("browser_download_url", "")).strip()
    if not package_url:
        raise RuntimeError("启动器下载地址无效")
    package_sha256 = str(trusted["package_sha256"])

    return {
        "remote_version": remote_version,
        "package_url": package_url,
        "package_sha256": package_sha256,
        "package_asset": asset_name,
        "package_size": launcher_asset.get("size", None),
        "source_name": (f"GitHub ({tag_name})" if tag_name else "GitHub"),
    }


def _fetch_manifest_from_github(channel: str) -> Dict[str, Any]:
    latest_release = _fetch_json(_latest_release_url())
    latest_err_msg = ""
    try:
        return _manifest_from_github_release(latest_release, channel)
    except Exception as latest_err:
        latest_tag = str(latest_release.get("tag_name", "")).strip()
        latest_err_msg = str(latest_err)

    # 若 latest 是 launcher-only 发布（无 manifest），回退到最近若干 release 中
    # 第一个可用的 app 发布，避免更新检查失败。
    releases = _fetch_json(_releases_list_url(20))
    if not isinstance(releases, list):
        raise RuntimeError("GitHub releases 返回格式异常")

    checked = 0
    for rel in releases:
        if not isinstance(rel, dict):
            continue
        tag = str(rel.get("tag_name", "")).strip()
        if latest_tag and tag == latest_tag:
            continue
        try:
            manifest = _manifest_from_github_release(rel, channel)
            if checked > 0:
                manifest["source_name"] = f"{manifest.get('source_name', 'GitHub')} fallback"
            return manifest
        except Exception:
            checked += 1
            continue

    raise RuntimeError(
        f"未找到可用发布清单: manifest_{channel}.json (latest={latest_tag}, err={latest_err_msg})"
    )


def _fetch_launcher_manifest_from_github() -> Dict[str, Any]:
    releases = _fetch_json(_releases_list_url(20))
    if not isinstance(releases, list):
        raise RuntimeError("GitHub releases 返回格式异常")

    first_err = ""
    for rel in releases:
        if not isinstance(rel, dict):
            continue
        try:
            return _launcher_manifest_from_github_release(rel)
        except Exception as e:
            if not first_err:
                first_err = str(e)
            continue
    raise RuntimeError(f"未找到可用启动器发布（err={first_err or 'unknown'}）")


def _github_terrain_release_base_url() -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", GITHUB_TERRAIN_RELEASE_TAG):
        raise RuntimeError("GitHub 地形发布标签配置无效")
    return (
        f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/download/"
        f"{GITHUB_TERRAIN_RELEASE_TAG}/"
    )


def _terrain_manifest_result(
    manifest: Dict[str, Any],
    *,
    label: str,
    source_name: str,
    object_base_urls: Tuple[str, ...],
) -> Dict[str, Any]:
    parsed = _strict_signed_terrain_manifest(manifest, label=label)
    result = dict(manifest)
    result.update(
        {
            "terrain_pack_id": parsed.pack_id,
            "terrain_revision": parsed.revision,
            "map_count": parsed.map_count,
            "total_size_bytes": parsed.total_size_bytes,
            "source_name": source_name,
            "object_base_urls": object_base_urls,
        }
    )
    return result


def _terrain_catalog_result(
    document: Dict[str, Any],
    *,
    label: str,
    source_name: str,
    object_base_url: str,
    metadata: _launcher_distribution_build.DistributionBuildMetadata | None = None,
) -> Dict[str, Any]:
    try:
        catalog = _strict_signed_terrain_catalog(document, metadata=metadata)
    except Exception as exc:
        raise RuntimeError(f"{label}签名或结构无效") from exc
    all_map_ids = tuple(terrain_map.map_id for terrain_map in catalog.maps)
    projection = _terrain_catalog_selection_projection(catalog, all_map_ids)
    return {
        "signed_catalog": dict(document),
        "terrain_catalog_id": catalog.catalog_id,
        "terrain_revision": catalog.revision,
        "map_count": len(catalog.maps),
        "total_size_bytes": projection["selected_size_bytes"],
        "source_name": str(source_name or "").strip() or "地形更新服务",
        "object_base_url": str(object_base_url or "").strip(),
    }


def _fetch_terrain_manifest_from_github() -> Dict[str, Any]:
    release_base = _github_terrain_release_base_url()
    manifest_url = urljoin(release_base, _launcher_terrain_store.TERRAIN_MANIFEST_ASSET)
    manifest = _fetch_json(manifest_url)
    return _terrain_manifest_result(
        manifest,
        label="GitHub 地形更新清单 ",
        source_name=f"GitHub ({GITHUB_TERRAIN_RELEASE_TAG})",
        object_base_urls=(release_base,),
    )


def _fetch_terrain_manifest_from_primary(
    timeout_sec: float = PRIMARY_TIMEOUT_SEC,
) -> Dict[str, Any]:
    if not PRIMARY_UPDATE_BASE_URL:
        raise RuntimeError("未配置国内更新服务")
    manifest_url = _join_base_url_path(
        PRIMARY_UPDATE_BASE_URL,
        PRIMARY_TERRAIN_MANIFEST_PATH,
    )
    raw = _fetch_bytes(manifest_url, timeout_sec=timeout_sec)
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("国内地形更新清单不是有效 JSON") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("国内地形更新清单格式无效")
    object_base = _join_base_url_path(
        PRIMARY_UPDATE_BASE_URL,
        PRIMARY_TERRAIN_OBJECTS_PATH,
    )
    return _terrain_manifest_result(
        manifest,
        label="国内地形更新清单 ",
        source_name="腾讯云地形更新服务",
        object_base_urls=(object_base,),
    )


def _fetch_terrain_catalog_from_primary(
    timeout_sec: float = PRIMARY_TIMEOUT_SEC,
) -> Dict[str, Any]:
    descriptor_url = _join_base_url_path(
        PRIMARY_UPDATE_BASE_URL,
        PRIMARY_DISTRIBUTION_DESCRIPTOR_PATH,
    )
    descriptor_raw = _fetch_bytes(
        descriptor_url,
        timeout_sec=timeout_sec,
        max_bytes=1024 * 1024,
    )
    try:
        descriptor_document = json.loads(descriptor_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("分发描述符不是有效 JSON") from exc
    if not isinstance(descriptor_document, dict):
        raise RuntimeError("分发描述符格式无效")
    trust = _distribution_trust_for_build()
    descriptor = _launcher_launch_contract.parse_distribution_descriptor(
        descriptor_document,
        public_keys=_DISTRIBUTION_BUILD_METADATA.artifact_public_keys,
        trust=trust,
    )
    reference = descriptor.reference_for("terrain", "Enhanced")
    if reference.object_base_url is None:
        raise RuntimeError("分发描述符缺少地形对象地址")
    catalog_url = reference.manifest_url
    raw = _fetch_bytes(catalog_url, timeout_sec=timeout_sec, max_bytes=1024 * 1024)
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("隔离测试地形目录不是有效 JSON") from exc
    if not isinstance(document, dict):
        raise RuntimeError("隔离测试地形目录格式无效")
    if (
        _launcher_launch_contract.contract_document_sha256(document)
        != reference.manifest_sha256
    ):
        raise RuntimeError("分发描述符与地形目录摘要不匹配")
    return _terrain_catalog_result(
        document,
        label="隔离测试地形目录 ",
        source_name="隔离测试地形服务",
        object_base_url=reference.object_base_url,
    )


def _fetch_isolated_test_app_manifest(channel: str) -> Dict[str, Any]:
    manifest_url = _join_base_url_path(
        PRIMARY_UPDATE_BASE_URL,
        f"/manifests/manifest_{channel}.json",
    )
    payload = _fetch_json(manifest_url)
    remote_version, min_launcher_version = _strict_signed_app_versions(
        payload,
        label="隔离测试应用清单 ",
    )
    trusted = _launcher_manifest_sources.verified_app_manifest_fields(
        payload,
        channel=channel,
        label="隔离测试应用清单 ",
        default_entrypoint=DEFAULT_ENTRYPOINT,
    )
    package_asset = str(trusted["package_asset"])
    changelog_asset = str(trusted["changelog_asset"])
    return {
        "remote_version": remote_version,
        "min_launcher_version": min_launcher_version,
        "signed_manifest": payload,
        "package_url": _join_base_url_path(
            PRIMARY_UPDATE_BASE_URL,
            f"/downloads/{package_asset}",
        ),
        "package_sha256": str(trusted["package_sha256"]),
        "package_asset": package_asset,
        "entrypoint": str(trusted["entrypoint"]),
        "package_size": None,
        "changelog_url": _join_base_url_path(
            PRIMARY_UPDATE_BASE_URL,
            f"/downloads/{changelog_asset}",
        ),
        "changelog_asset": changelog_asset,
        "changelog_sha256": str(trusted["changelog_sha256"]),
        "source_name": "隔离测试静态分发",
    }


def _fetch_isolated_test_launcher_manifest() -> Dict[str, Any]:
    payload = _fetch_json(
        _join_base_url_path(PRIMARY_UPDATE_BASE_URL, "/launcher_manifest.json")
    )
    remote_version = _strict_signed_launcher_version(
        payload,
        label="隔离测试启动器清单 ",
    )
    trusted = _launcher_manifest_sources.verified_launcher_manifest_fields(
        payload,
        label="隔离测试启动器清单 ",
    )
    launcher_asset = str(trusted["package_asset"])
    return {
        "remote_version": remote_version,
        "signed_manifest": payload,
        "package_url": _join_base_url_path(
            PRIMARY_UPDATE_BASE_URL,
            f"/downloads/{launcher_asset}",
        ),
        "package_sha256": str(trusted["package_sha256"]),
        "package_asset": launcher_asset,
        "package_size": int(trusted["launcher_size_bytes"]),
        "source_name": "隔离测试静态分发",
    }


def _fetch_manifest_from_primary(
    channel: str,
    local_version: str,
    identity: Dict[str, str],
    timeout_sec: float = PRIMARY_TIMEOUT_SEC,
) -> Dict[str, Any]:
    if not PRIMARY_UPDATE_BASE_URL:
        raise RuntimeError("未配置国内更新服务")

    params = {
        "channel": channel,
        "launcher_version": LAUNCHER_VERSION,
        "local_version": local_version,
        "device_id": identity.get("device_id", ""),
        "install_id": identity.get("install_id", ""),
    }
    version_url = _join_base_url_path(PRIMARY_UPDATE_BASE_URL, PRIMARY_VERSION_API_PATH)
    used_anonymous_fallback = False
    try:
        payload = _fetch_primary_version_payload(version_url, params, timeout_sec)
    except Exception as first_err:
        # 服务端偶发在身份参数路径上超时或返回 5xx，回退到匿名请求以提升成功率。
        anon_params = dict(params)
        anon_params["device_id"] = ""
        anon_params["install_id"] = ""
        if anon_params == params:
            raise
        try:
            payload = _fetch_primary_version_payload(version_url, anon_params, timeout_sec)
            used_anonymous_fallback = True
        except Exception as anon_err:
            raise RuntimeError(f"{first_err}; 匿名回退失败: {anon_err}") from anon_err
    remote_version, min_launcher_version = _strict_signed_app_versions(
        payload,
        label="国内应用更新清单 ",
    )
    trusted = _launcher_manifest_sources.verified_app_manifest_fields(
        payload,
        channel=channel,
        label="国内应用更新清单 ",
        default_entrypoint=DEFAULT_ENTRYPOINT,
    )
    raw_package_url = str(payload.get("package_url", "")).strip()
    package_url = (
        _join_base_url_path(PRIMARY_UPDATE_BASE_URL, raw_package_url) if raw_package_url else ""
    )
    package_sha256 = str(trusted["package_sha256"])
    package_size = payload.get("package_size_bytes", payload.get("package_size"))
    changelog_asset = str(trusted["changelog_asset"])
    # Prefer the service-provided absolute URL when present; fall back to package dir.
    changelog_url = str(payload.get("changelog_url", "")).strip() or urljoin(
        package_url, changelog_asset
    )
    entrypoint = str(trusted["entrypoint"])
    source_name = str(payload.get("source_name", "腾讯云更新服务")).strip() or "腾讯云更新服务"
    if used_anonymous_fallback:
        source_name = f"{source_name} (匿名回退)"

    return {
        "remote_version": remote_version,
        "min_launcher_version": min_launcher_version,
        "signed_manifest": payload,
        "package_url": package_url,
        "package_sha256": package_sha256,
        "package_asset": str(trusted["package_asset"]),
        "entrypoint": entrypoint,
        "package_size": package_size,
        "changelog_url": changelog_url,
        "changelog_asset": changelog_asset,
        "changelog_sha256": str(trusted["changelog_sha256"]),
        "source_name": source_name,
    }


def _fetch_launcher_manifest_from_primary(
    identity: Dict[str, str],
    timeout_sec: float = PRIMARY_TIMEOUT_SEC,
) -> Dict[str, Any]:
    if not PRIMARY_UPDATE_BASE_URL:
        raise RuntimeError("未配置国内更新服务")

    params = {
        "launcher_version": LAUNCHER_VERSION,
        "device_id": identity.get("device_id", ""),
        "install_id": identity.get("install_id", ""),
    }
    launcher_url = _join_base_url_path(PRIMARY_UPDATE_BASE_URL, PRIMARY_LAUNCHER_API_PATH)
    used_anonymous_fallback = False
    try:
        payload = _fetch_primary_json_payload(launcher_url, params, timeout_sec)
    except Exception as first_err:
        anon_params = dict(params)
        anon_params["device_id"] = ""
        anon_params["install_id"] = ""
        if anon_params == params:
            raise
        try:
            payload = _fetch_primary_json_payload(launcher_url, anon_params, timeout_sec)
            used_anonymous_fallback = True
        except Exception as anon_err:
            raise RuntimeError(f"{first_err}; 匿名回退失败: {anon_err}") from anon_err

    remote_version = _strict_signed_launcher_version(
        payload,
        label="国内启动器更新清单 ",
    )
    trusted = _launcher_manifest_sources.verified_launcher_manifest_fields(
        payload,
        label="国内启动器更新清单 ",
    )
    raw_package_url = str(payload.get("package_url", "")).strip()
    package_url = (
        _join_base_url_path(PRIMARY_UPDATE_BASE_URL, raw_package_url) if raw_package_url else ""
    )
    package_sha256 = str(trusted["package_sha256"])
    package_size = payload.get("package_size_bytes", payload.get("package_size"))
    source_name = str(payload.get("source_name", "腾讯云更新服务")).strip() or "腾讯云更新服务"
    if used_anonymous_fallback:
        source_name = f"{source_name} (匿名回退)"

    return {
        "remote_version": remote_version,
        "package_url": package_url,
        "package_sha256": package_sha256,
        "package_asset": str(trusted["package_asset"]),
        "package_size": package_size,
        "source_name": source_name,
    }


def _report_primary_event(
    base: Path,
    identity: Dict[str, str],
    event_name: str,
    channel: str,
    app_version: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    if (not PRIMARY_UPDATE_BASE_URL) or _is_source_test_run(base):
        return

    payload: Dict[str, Any] = {
        "event": event_name,
        "event_time_utc": _now_utc_iso(),
        "channel": channel,
        "launcher_version": LAUNCHER_VERSION,
        "app_version": app_version,
        "device_id": identity.get("device_id", ""),
        "install_id": identity.get("install_id", ""),
    }
    if extra:
        payload.update(extra)

    try:
        event_url = _join_base_url_path(PRIMARY_UPDATE_BASE_URL, PRIMARY_EVENT_API_PATH)
        _post_json(event_url, payload, timeout_sec=PRIMARY_TIMEOUT_SEC)
    except Exception as e:
        _log(base, f"事件上报失败({event_name})：{e}")


def _resolve_update_manifest(
    base: Path,
    channel: str,
    identity: Dict[str, str],
    download_source_mode: str = DOWNLOAD_SOURCE_MODE_AUTO,
    status_cb: Optional[Callable[[str, str, Optional[float], str], None]] = None,
) -> Tuple[str, Dict[str, Any]]:
    def notify(
        title: str,
        detail: str = "",
        progress: Optional[float] = None,
        level: str = "info",
    ) -> None:
        if status_cb:
            status_cb(title, detail, progress, level)

    local_version = install_txn.read_local_app_version(_app_runtime_dir(base, channel))
    source_mode = _effective_download_source_mode(download_source_mode)

    manifest: Optional[Dict[str, Any]] = None
    primary_err: Optional[Exception] = None
    should_try_primary = (
        source_mode != DOWNLOAD_SOURCE_MODE_GITHUB
        and PRIMARY_UPDATE_BASE_URL
        and (not _is_source_test_run(base))
    )
    if should_try_primary:
        try:
            manifest = _attempt_primary_request(
                base,
                "腾讯云版本检查",
                "优先连接腾讯云更新服务...",
                lambda timeout_sec: _fetch_manifest_from_primary(
                    channel,
                    local_version,
                    identity,
                    timeout_sec=timeout_sec,
                ),
                status_cb=notify,
            )

            if manifest is not None:
                remote_version_preview = str(manifest.get("remote_version", "")).strip()
                package_url_preview = str(manifest.get("package_url", "")).strip()
                need_fallback = _version_is_newer(remote_version_preview, local_version) and (
                    (not PRIMARY_ALLOW_PACKAGE_DOWNLOAD) or (not package_url_preview)
                )
                if need_fallback:
                    if source_mode == DOWNLOAD_SOURCE_MODE_PRIMARY:
                        raise RuntimeError("腾讯云更新服务未提供应用下载包")
                    _log(base, "腾讯云更新服务仅用于版本检测，下载源切换为 GitHub")
                    notify(
                        "发现新版本",
                        "腾讯云仅提供版本号，正在切换 GitHub 下载源...",
                        None,
                        "info",
                    )
                    manifest = None
        except Exception as e:
            primary_err = e
            _log(base, f"腾讯云更新服务不可用：{e}")
            if source_mode == DOWNLOAD_SOURCE_MODE_PRIMARY:
                raise
            notify("国内服务暂不可用", "正在切换 GitHub 回退...", None, "warning")

    if manifest is None:
        if source_mode == DOWNLOAD_SOURCE_MODE_PRIMARY:
            raise RuntimeError("腾讯云更新服务未返回可用更新清单")
        notify("正在检查更新", "连接 GitHub 获取最新版本信息...", None, "info")
        try:
            manifest = _fetch_manifest_from_github(channel)
        except Exception as e:
            if primary_err is not None:
                raise RuntimeError(
                    f"国内更新服务不可用({primary_err})，GitHub 回退失败({e})"
                ) from e
            raise

    if manifest is None:
        raise RuntimeError("更新清单字段缺失")
    return local_version, manifest


def _resolve_launcher_update_manifest(
    base: Path,
    identity: Dict[str, str],
    download_source_mode: str = DOWNLOAD_SOURCE_MODE_AUTO,
    status_cb: Optional[Callable[[str, str, Optional[float], str], None]] = None,
) -> Dict[str, Any]:
    def notify(
        title: str,
        detail: str = "",
        progress: Optional[float] = None,
        level: str = "info",
    ) -> None:
        if status_cb:
            status_cb(title, detail, progress, level)

    manifest: Optional[Dict[str, Any]] = None
    primary_err: Optional[Exception] = None
    source_mode = _effective_download_source_mode(download_source_mode)
    should_try_primary = (
        source_mode != DOWNLOAD_SOURCE_MODE_GITHUB
        and PRIMARY_UPDATE_BASE_URL
        and (not _is_source_test_run(base))
    )
    if should_try_primary:
        try:
            manifest = _attempt_primary_request(
                base,
                "腾讯云启动器版本检查",
                "正在检查启动器版本...",
                lambda timeout_sec: _fetch_launcher_manifest_from_primary(
                    identity,
                    timeout_sec=timeout_sec,
                ),
                status_cb=notify,
            )
            if manifest is not None:
                remote_version = str(manifest.get("remote_version", "")).strip()
                package_url = str(manifest.get("package_url", "")).strip()
                if _version_is_newer(remote_version, LAUNCHER_VERSION) and (
                    (not PRIMARY_ALLOW_PACKAGE_DOWNLOAD) or (not package_url)
                ):
                    if source_mode == DOWNLOAD_SOURCE_MODE_PRIMARY:
                        raise RuntimeError("腾讯云启动器更新服务未提供下载包")
                    _log(base, "腾讯云启动器更新服务仅提供版本号，下载源切换为 GitHub")
                    manifest = None
        except Exception as e:
            primary_err = e
            _log(base, f"腾讯云启动器更新服务不可用：{e}")
            if source_mode == DOWNLOAD_SOURCE_MODE_PRIMARY:
                raise

    if manifest is None:
        if source_mode == DOWNLOAD_SOURCE_MODE_PRIMARY:
            raise RuntimeError("腾讯云启动器更新服务未返回可用更新清单")
        try:
            manifest = _fetch_launcher_manifest_from_github()
        except Exception as e:
            if primary_err is not None:
                raise RuntimeError(
                    f"启动器国内更新服务不可用({primary_err})，GitHub 回退失败({e})"
                ) from e
            raise

    if manifest is None:
        raise RuntimeError("启动器更新清单字段缺失")
    return manifest


def _resolve_terrain_update_manifest(
    base: Path,
    download_source_mode: str = DOWNLOAD_SOURCE_MODE_AUTO,
    status_cb: Optional[Callable[[str, str, Optional[float], str], None]] = None,
) -> Dict[str, Any]:
    def notify(
        title: str,
        detail: str = "",
        progress: Optional[float] = None,
        level: str = "info",
    ) -> None:
        if status_cb:
            status_cb(title, detail, progress, level)

    source_mode = _effective_download_source_mode(download_source_mode)
    primary_error: Optional[Exception] = None
    if source_mode != DOWNLOAD_SOURCE_MODE_GITHUB and PRIMARY_UPDATE_BASE_URL:
        try:
            result = _attempt_primary_request(
                base,
                "腾讯云地形版本检查",
                "正在检查独立地形数据...",
                _fetch_terrain_manifest_from_primary,
                status_cb=notify,
            )
            if source_mode == DOWNLOAD_SOURCE_MODE_AUTO:
                github_base = _github_terrain_release_base_url()
                bases = tuple(result.get("object_base_urls", ()))
                if github_base not in bases:
                    result["object_base_urls"] = (*bases, github_base)
            return result
        except Exception as exc:
            primary_error = exc
            _log(base, f"腾讯云地形更新服务不可用：{exc}")
            if source_mode == DOWNLOAD_SOURCE_MODE_PRIMARY:
                raise
            notify("国内地形服务暂不可用", "正在切换 GitHub 回退...", None, "warning")

    if source_mode == DOWNLOAD_SOURCE_MODE_PRIMARY:
        raise RuntimeError("腾讯云地形更新服务未返回可用清单")
    try:
        return _fetch_terrain_manifest_from_github()
    except Exception as exc:
        if primary_error is not None:
            raise RuntimeError(
                f"国内地形更新服务不可用({primary_error})，GitHub 回退失败({exc})"
            ) from exc
        raise


def _terrain_store_for_base(base: Path) -> _launcher_terrain_store.TerrainStore:
    return _launcher_terrain_store.TerrainStore(_launcher_data_root(base))


def _terrain_index_summary(pack_dir: Path) -> tuple[int, int]:
    """Read a bounded, file-backed summary for a legacy/source terrain pack."""

    index_path = pack_dir / "index.json"
    try:
        if not index_path.is_file() or not 0 < index_path.stat().st_size <= 2 * 1024 * 1024:
            return 0, 0
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        maps = payload.get("maps") if isinstance(payload, dict) else None
        if not isinstance(maps, list) or not 0 < len(maps) <= 1024:
            return 0, 0
        files: list[Path] = []
        for item in maps:
            filename = str(item.get("file", "")).strip() if isinstance(item, dict) else ""
            candidate = Path(filename)
            if (
                not filename
                or candidate.is_absolute()
                or len(candidate.parts) != 1
                or candidate.name != filename
            ):
                return 0, 0
            file_path = pack_dir / filename
            if not file_path.is_file():
                return 0, 0
            files.append(file_path)
        metadata = [path for path in (index_path, pack_dir / "manifest.json") if path.is_file()]
        total_size = sum(path.stat().st_size for path in [*files, *metadata])
        return len(maps), total_size
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return 0, 0


def _terrain_catalog_selection_projection(
    catalog: _launcher_terrain_store.TerrainCatalog,
    selected_map_ids: Tuple[str, ...],
) -> Dict[str, Any]:
    """Project explicit map desired state without starting a transfer."""

    selected = tuple(sorted({str(map_id).strip() for map_id in selected_map_ids}))
    selected_set = frozenset(selected)
    all_map_ids = frozenset(terrain_map.map_id for terrain_map in catalog.maps)
    unique_objects = _terrain_catalog_selected_objects(catalog, selected_set)
    return {
        "map_count": len(catalog.maps),
        "selected_count": len(selected),
        "selected_map_ids": selected,
        "selected_size_bytes": sum(item.size_bytes for item in unique_objects.values()),
        "all_selected": bool(all_map_ids and selected_set == all_map_ids),
    }


def _terrain_map_row_projection(
    progress: _launcher_terrain_store.TerrainMapProgress | None,
    *,
    selected: bool,
) -> Dict[str, Any]:
    completed = max(0, int(progress.completed_bytes if progress is not None else 0))
    total = max(0, int(progress.total_bytes if progress is not None else 0))
    fraction = min(1.0, completed / total) if total else 0.0
    complete = bool(progress is not None and progress.complete)
    if complete:
        fraction = 1.0
        status_text = "已就绪"
    elif not selected:
        fraction = 0.0
        status_text = "未选择"
    elif completed and total:
        status_text = (
            f"{fraction * 100:.0f}% · "
            f"{_format_size_text(completed)} / {_format_size_text(total)}"
        )
    else:
        status_text = "等待下载"
    return {
        "progress_fraction": fraction,
        "selection_marker": "[x]" if selected else "[ ]",
        "status_text": status_text,
        "background_mode": "progress" if fraction > 0 else "empty",
    }


def _terrain_catalog_selected_objects(
    catalog: _launcher_terrain_store.TerrainCatalog,
    selected_map_ids: Iterable[str],
) -> Dict[str, _launcher_terrain_store.TerrainFile]:
    selected = frozenset(str(map_id).strip() for map_id in selected_map_ids)
    unique_objects: Dict[str, _launcher_terrain_store.TerrainFile] = {
        item.sha256: item for item in catalog.shared_files
    }
    for terrain_map in catalog.maps:
        if terrain_map.map_id not in selected:
            continue
        for item in terrain_map.files:
            unique_objects.setdefault(item.sha256, item)
    return unique_objects


def _terrain_catalog_transfer_projection(
    store: _launcher_terrain_store.TerrainStore,
    catalog: _launcher_terrain_store.TerrainCatalog,
    selected_map_ids: Tuple[str, ...],
) -> tuple[int, int]:
    download_bytes = 0
    reuse_bytes = 0
    for item in _terrain_catalog_selected_objects(catalog, selected_map_ids).values():
        object_path = store.objects_dir / item.sha256
        try:
            valid = (
                object_path.is_file()
                and not object_path.is_symlink()
                and object_path.stat().st_size == item.size_bytes
                and _launcher_terrain_store.sha256_file(object_path) == item.sha256
            )
        except OSError:
            valid = False
        if valid:
            reuse_bytes += item.size_bytes
        else:
            download_bytes += item.size_bytes
    return download_bytes, reuse_bytes


def _terrain_status_copy(
    channel: object,
    *,
    local_state: str,
    local_revision: str = "",
    remote_revision: str = "",
    map_count: int = 0,
    total_size_bytes: int = 0,
    update_available: bool = False,
    download_size: int = 0,
    check_warning: str = "",
    check_blocking: bool = False,
    running: bool = False,
    current_task: str = "",
) -> tuple[str, str, str]:
    """Return the compact badge, detail, and color level for the terrain card."""

    if _normalize_channel(channel) != "Enhanced":
        return "未使用", "Standard / Lite 不安装离线地图包。", "muted"

    revision = str(local_revision or "").strip()
    target_revision = str(remote_revision or "").strip()
    count = max(0, int(map_count or 0))
    total_size = max(0, int(total_size_bytes or 0))
    download_bytes = max(0, int(download_size or 0))

    facts: list[str] = []
    if count:
        facts.append(f"{count} 张地图")
    if total_size:
        facts.append(_format_size_text(total_size))

    if running and current_task == "download" and update_available:
        target = f"rev {target_revision[:12]}" if target_revision else "新版本"
        detail = " · ".join([*facts, f"正在同步到 {target}"])
        return "正在更新", detail or "正在校验并切换离线地图包。", "info"

    if check_blocking:
        detail = str(check_warning or "").strip() or "当前地图包缺失或校验失败。"
        return "需修复", detail, "error"

    if local_state == "invalid":
        if update_available:
            detail = "当前地图包校验失败；点击更新可重新组装已验证版本。"
            if download_bytes:
                detail += f" 需下载 {_format_size_text(download_bytes)}。"
            return "需修复", detail, "error"
        return "需修复", "当前地图包指针或文件完整性校验失败。", "error"

    if local_state == "legacy" and update_available:
        target = f"rev {target_revision[:12]}" if target_revision else "已验证版本"
        detail = " · ".join(
            [*facts, f"可迁移到 {target}", f"需下载 {_format_size_text(download_bytes)}"]
        )
        return "旧包可迁移", detail, "warning"

    if update_available:
        if revision:
            transition = (
                f"rev {revision[:12]} → {target_revision[:12]}"
                if target_revision
                else f"当前 rev {revision[:12]}"
            )
            delta = f"差量 {_format_size_text(download_bytes)}"
            detail = " · ".join([*facts, transition, delta])
            return "可更新", detail, "warning"
        target = f"rev {target_revision[:12]}" if target_revision else "等待下载"
        detail = " · ".join([*facts, target, f"需下载 {_format_size_text(download_bytes)}"])
        return "待安装", detail, "warning"

    if local_state == "ready" and revision:
        current = f"rev {revision[:12]}"
        detail = " · ".join([*facts, current])
        if check_warning:
            return "已安装", f"{detail} · 在线更新检查暂不可用", "warning"
        if target_revision and target_revision == revision:
            return "已是最新", detail, "success"
        return "已安装", detail, "success"

    if local_state == "legacy":
        detail = " · ".join([*facts, "启动器将在更新时迁移并校验"])
        return "旧包可迁移", detail, "warning"

    if local_state == "source":
        detail = " · ".join([*facts, "App 默认离线目录"])
        return "源码数据可用", detail, "success"

    if running and current_task == "check":
        return "正在检查", "本地尚未安装；正在查询可用地图包。", "info"

    return "未安装", "选择超级爆弹版后可单独下载，不会重复下载 App。", "warning"


def _terrain_seed_dirs(base: Path, pack_id: str, channel: object = "Enhanced") -> Tuple[Path, ...]:
    candidates: list[Path] = []
    override = os.environ.get("BOMANA_TERRAIN_DIR", "").strip()
    if override:
        candidates.append(Path(override).expanduser())
    for app_dir in (
        _app_runtime_dir(base, channel),
        _previous_app_dir(base, channel),
    ):
        candidates.append(app_dir / "bomana" / "data" / pack_id)
    candidates.append(Path.home() / ".bomana" / pack_id)
    return _unique_paths(tuple(candidates))


def _download_terrain_update_from_manifest(
    base: Path,
    manifest: Dict[str, Any],
    status_cb: Optional[Callable[[str, str, Optional[float], str], None]] = None,
    cancel_cb: Optional[Callable[[], bool]] = None,
    channel: object = "Enhanced",
    subscriber_artifact_provider: Optional[
        Callable[[str], AuthorizedArtifactRequest]
    ] = None,
) -> _launcher_terrain_store.TerrainSyncResult:
    parsed = _strict_signed_terrain_manifest(
        manifest,
        label="地形更新清单 ",
    )
    raw_bases = manifest.get("object_base_urls")
    if subscriber_artifact_provider is None and not isinstance(raw_bases, (tuple, list)):
        raise RuntimeError("地形更新清单缺少对象下载源")
    object_bases = tuple(
        str(value).strip()
        for value in (raw_bases or ())
        if str(value).strip()
    )
    if subscriber_artifact_provider is None and not object_bases:
        raise RuntimeError("地形更新清单缺少对象下载源")

    source_name = str(manifest.get("source_name", "地形更新服务")).strip() or "地形更新服务"

    def fetch_object(
        item: _launcher_terrain_store.TerrainFile,
        destination: Path,
        progress_cb: Callable[[int, Optional[int]], None],
    ) -> str:
        if subscriber_artifact_provider is not None:
            resource = _subscriber_artifacts.terrain_object_resource(item.asset)
            access = _authorized_subscriber_artifact(
                subscriber_artifact_provider,
                resource,
            )
            _download_to_file(
                access.download_url,
                destination,
                progress_cb=progress_cb,
                cancel_cb=cancel_cb,
                headers={"Accept": "application/octet-stream, */*", **access.headers()},
                max_bytes=item.size_bytes,
                allow_redirects=False,
            )
            if (
                destination.stat().st_size != item.size_bytes
                or _launcher_terrain_store.sha256_file(destination) != item.sha256
            ):
                destination.unlink(missing_ok=True)
                destination.with_name(f"{destination.name}.part").unlink(missing_ok=True)
                raise RuntimeError("SHA256 校验失败")
            return "CheemsPay 订阅制品网关"

        errors: list[str] = []
        for object_base in object_bases:
            object_url = urljoin(
                object_base if object_base.endswith("/") else f"{object_base}/",
                item.asset,
            )
            try:
                _download_to_file(
                    object_url,
                    destination,
                    progress_cb=progress_cb,
                    cancel_cb=cancel_cb,
                    headers={"Accept": "application/octet-stream, */*"},
                    max_bytes=item.size_bytes,
                )
                if (
                    destination.stat().st_size != item.size_bytes
                    or _launcher_terrain_store.sha256_file(destination) != item.sha256
                ):
                    raise RuntimeError("SHA256 校验失败")
                host = str(urlparse(object_url).hostname or "").strip()
                return host or source_name
            except Exception as exc:
                errors.append(f"{object_url}: {exc}")
                destination.unlink(missing_ok=True)
                destination.with_name(f"{destination.name}.part").unlink(missing_ok=True)
                if cancel_cb and cancel_cb():
                    raise RuntimeError("已取消当前操作") from exc
        raise RuntimeError("所有地形对象下载源均失败:\n" + "\n".join(errors))

    return _terrain_store_for_base(base).sync(
        parsed,
        fetch_object=fetch_object,
        seed_dirs=_terrain_seed_dirs(base, parsed.pack_id, channel),
        status_cb=status_cb,
        cancel_cb=cancel_cb,
    )


def _download_terrain_catalog_from_manifest(
    base: Path,
    envelope: Dict[str, Any],
    status_cb: Optional[Callable[[str, str, Optional[float], str], None]] = None,
    map_progress_cb: Optional[
        Callable[[tuple[_launcher_terrain_store.TerrainMapProgress, ...]], None]
    ] = None,
    cancel_cb: Optional[Callable[[], bool]] = None,
    subscriber_artifact_provider: Optional[
        Callable[[str], AuthorizedArtifactRequest]
    ] = None,
    app_host_active: Optional[Callable[[], bool]] = None,
) -> _launcher_terrain_store.TerrainCatalogSyncResult:
    document = _terrain_catalog_document(envelope)
    if document is None:
        raise RuntimeError("地形目录缺少签名文档")
    catalog = _strict_signed_terrain_catalog(document)
    source_name = str(envelope.get("source_name", "地形更新服务")).strip() or "地形更新服务"
    object_base_url = str(envelope.get("object_base_url", "")).strip()
    if subscriber_artifact_provider is None and not object_base_url:
        raise RuntimeError("地形目录缺少对象下载源")

    if status_cb:
        selected_count = len(_terrain_store_for_base(base).selected_map_ids(catalog))
        status_cb(
            "正在维护所选地图",
            f"将校验并同步 {selected_count} 张已选择地图；未选择的地图不会下载。",
            None,
            "info",
        )

    request = _launcher_terrain_transport.urllib_terrain_request
    transport_base_url = object_base_url
    if subscriber_artifact_provider is not None:
        transport_base_url = "https://subscriber-artifacts.invalid/terrain/"

        def authorized_request(
            url: str,
            headers: Dict[str, str],
            timeout: float,
        ) -> Any:
            if cancel_cb and cancel_cb():
                raise RuntimeError("已取消当前操作")
            asset = Path(urlparse(url).path).name
            access = _authorized_subscriber_artifact(
                subscriber_artifact_provider,
                _subscriber_artifacts.terrain_object_resource(asset),
            )
            req = Request(
                access.download_url,
                headers={**dict(headers), **access.headers()},
                method="GET",
            )
            try:
                response = _open_url(req, timeout, allow_redirects=False)
            except HTTPError as exc:
                response = exc
            return _launcher_terrain_transport._UrllibResponse(response)

        request = authorized_request

    transport = _launcher_terrain_transport.TerrainObjectTransport(
        transport_base_url,
        request=request,
        timeout_seconds=NET_TIMEOUT_SEC,
        source_name=source_name,
    )
    result = _terrain_store_for_base(base).sync_catalog(
        catalog,
        fetch_object=transport,
        app_host_active=app_host_active or _APP_HOST_ACTIVE.is_set,
        map_progress_cb=map_progress_cb,
    )
    if status_cb:
        level = "success" if result.status in {"activated", "already_current"} else "warning"
        status_cb(
            "地图维护完成" if level == "success" else "地图维护已暂停",
            result.message,
            1.0 if level == "success" else None,
            level,
        )
    return result


class UpdateService:
    """Coordinates manifest resolution, update checks, and download operations."""

    def __init__(
        self,
        base: Path,
        channel: str,
        identity: Dict[str, str],
        download_source_mode: str = DOWNLOAD_SOURCE_MODE_AUTO,
        status_cb: Optional[Callable[[str, str, Optional[float], str], None]] = None,
        terrain_map_progress_cb: Optional[
            Callable[[tuple[_launcher_terrain_store.TerrainMapProgress, ...]], None]
        ] = None,
        cancel_cb: Optional[Callable[[], bool]] = None,
        subscriber_artifact_provider: Optional[
            Callable[[str], AuthorizedArtifactRequest]
        ] = None,
    ) -> None:
        self.base = base
        self.channel = channel
        self.identity = identity
        self.download_source_mode = _effective_download_source_mode(download_source_mode)
        self.status_cb = status_cb
        self.terrain_map_progress_cb = terrain_map_progress_cb
        self.cancel_cb = cancel_cb
        self.subscriber_artifact_provider = subscriber_artifact_provider

    def notify(
        self,
        title: str,
        detail: str = "",
        progress: Optional[float] = None,
        level: str = "info",
    ) -> None:
        if self.status_cb:
            self.status_cb(title, detail, progress, level)

    def resolve_app_manifest(self) -> Tuple[str, Dict[str, Any]]:
        if _DISTRIBUTION_BUILD_METADATA.isolated_test:
            return (
                install_txn.read_local_app_version(
                    _app_runtime_dir(self.base, self.channel)
                ),
                _fetch_isolated_test_app_manifest(self.channel),
            )
        if (
            _normalize_channel(self.channel) == "Enhanced"
            and not _DISTRIBUTION_BUILD_METADATA.isolated_test
        ):
            if self.subscriber_artifact_provider is None:
                raise RuntimeError("超级爆弹版必须通过 CheemsPay 获取私有清单")
            return (
                install_txn.read_local_app_version(_app_runtime_dir(self.base, self.channel)),
                _fetch_manifest_from_subscriber(self.subscriber_artifact_provider),
            )
        return _resolve_update_manifest(
            self.base,
            self.channel,
            self.identity,
            download_source_mode=self.download_source_mode,
            status_cb=self.notify,
        )

    def resolve_launcher_manifest(self) -> Dict[str, Any]:
        if _DISTRIBUTION_BUILD_METADATA.isolated_test:
            return _fetch_isolated_test_launcher_manifest()
        return _resolve_launcher_update_manifest(
            self.base,
            self.identity,
            download_source_mode=self.download_source_mode,
            status_cb=self.notify,
        )

    def resolve_terrain_manifest(self) -> Dict[str, Any]:
        if _DISTRIBUTION_BUILD_METADATA.isolated_test:
            return _attempt_primary_request(
                self.base,
                "隔离测试地形目录检查",
                "正在检查可选择地图目录...",
                _fetch_terrain_catalog_from_primary,
                status_cb=self.notify,
            )
        if _normalize_channel(self.channel) == "Enhanced":
            if self.subscriber_artifact_provider is None:
                raise RuntimeError("超级爆弹版必须通过 CheemsPay 获取私有地形清单")
            return _fetch_terrain_manifest_from_subscriber(
                self.subscriber_artifact_provider
            )
        return _resolve_terrain_update_manifest(
            self.base,
            download_source_mode=self.download_source_mode,
            status_cb=self.notify,
        )

    def check(self) -> Dict[str, Any]:
        local_version, manifest = self.resolve_app_manifest()
        remote_version = require_minimum_version(
            manifest.get("remote_version"),
            MIN_SUPPORTED_APP_VERSION,
            identity_name="已验证签名清单应用版本",
        )
        min_launcher_version = require_minimum_version(
            manifest.get("min_launcher_version"),
            MIN_SUPPORTED_LAUNCHER_VERSION,
            identity_name="已验证签名清单最低启动器版本",
        )
        package_url = str(manifest.get("package_url", "")).strip()
        package_resource = str(manifest.get("package_resource", "")).strip()
        source_name = str(manifest.get("source_name", "GitHub")).strip() or "GitHub"
        update_available = _version_is_newer(remote_version, local_version)
        app_requires_launcher_update = bool(
            update_available
            and min_launcher_version
            and not _launcher_meets_minimum(min_launcher_version)
        )
        if update_available and not (package_url or package_resource):
            raise RuntimeError("更新清单字段缺失")

        package_size = self._manifest_package_size(manifest)
        if update_available and package_size is None and package_url:
            package_size = _fetch_content_length(package_url, timeout_sec=NET_TIMEOUT_SEC)

        terrain_manifest: Dict[str, Any] = {}
        terrain_local_revision = ""
        terrain_remote_revision = ""
        terrain_source_name = ""
        terrain_update_available = False
        terrain_download_size = 0
        terrain_reuse_size = 0
        terrain_remote_map_count = 0
        terrain_remote_total_size = 0
        terrain_catalog = False
        terrain_catalog_map_count = 0
        terrain_catalog_selected_count = 0
        terrain_catalog_selected_map_ids: Tuple[str, ...] = ()
        terrain_selection_size_bytes = 0
        terrain_check_warning = ""
        terrain_check_blocking = False
        if (
            _normalize_channel(self.channel) == "Enhanced"
            or _DISTRIBUTION_BUILD_METADATA.isolated_test
        ):
            terrain_store = _terrain_store_for_base(self.base)
            try:
                terrain_manifest = self.resolve_terrain_manifest()
                terrain_source_name = (
                    str(terrain_manifest.get("source_name", "地形更新服务")).strip()
                    or "地形更新服务"
                )
                catalog_document = _terrain_catalog_document(terrain_manifest)
                if catalog_document is not None:
                    terrain_catalog = True
                    catalog_model = _strict_signed_terrain_catalog(catalog_document)
                    selected_map_ids = terrain_store.selected_map_ids(catalog_model)
                    projection = _terrain_catalog_selection_projection(
                        catalog_model,
                        selected_map_ids,
                    )
                    current_catalog = terrain_store.current_catalog()
                    current_selection = terrain_store.current_catalog_selection()
                    terrain_local_revision = (
                        current_catalog.revision
                        if current_catalog is not None
                        else terrain_store.current_revision()
                    )
                    terrain_remote_revision = catalog_model.revision
                    terrain_remote_map_count = len(catalog_model.maps)
                    terrain_remote_total_size = int(projection["selected_size_bytes"])
                    terrain_catalog_map_count = len(catalog_model.maps)
                    terrain_catalog_selected_count = int(projection["selected_count"])
                    terrain_catalog_selected_map_ids = tuple(
                        projection["selected_map_ids"]
                    )
                    terrain_selection_size_bytes = int(projection["selected_size_bytes"])
                    terrain_download_size, terrain_reuse_size = (
                        _terrain_catalog_transfer_projection(
                            terrain_store,
                            catalog_model,
                            terrain_catalog_selected_map_ids,
                        )
                    )
                    active_matches = bool(
                        current_catalog is not None
                        and current_catalog.revision == catalog_model.revision
                        and current_selection == terrain_catalog_selected_map_ids
                    )
                    terrain_update_available = bool(
                        (terrain_catalog_selected_map_ids or current_catalog is not None)
                        and not active_matches
                    )
                else:
                    terrain_model = _strict_signed_terrain_manifest(
                        terrain_manifest,
                        label="地形更新清单 ",
                    )
                    terrain_remote_revision = terrain_model.revision
                    terrain_remote_map_count = terrain_model.map_count
                    terrain_remote_total_size = terrain_model.total_size_bytes
                    terrain_plan = terrain_store.plan(
                        terrain_model,
                        seed_dirs=_terrain_seed_dirs(
                            self.base,
                            terrain_model.pack_id,
                            self.channel,
                        ),
                    )
                    terrain_local_revision = terrain_plan.local_revision
                    terrain_update_available = not terrain_plan.current
                    terrain_download_size = terrain_plan.bytes_to_download
                    terrain_reuse_size = terrain_plan.bytes_to_reuse
            except Exception as exc:
                terrain_check_warning = str(exc)
                current_catalog = terrain_store.current_catalog()
                terrain_local_revision = (
                    current_catalog.revision
                    if current_catalog is not None
                    else terrain_store.current_revision()
                )
                terrain_check_blocking = False
                _log(self.base, f"地形数据更新检查失败：{exc}")

        launcher_manifest: Dict[str, Any] = {}
        launcher_remote_version = LAUNCHER_VERSION
        launcher_source_name = ""
        launcher_update_available = False
        launcher_package_size: Optional[int] = None
        launcher_check_warning = ""
        try:
            launcher_manifest = self.resolve_launcher_manifest()
            launcher_remote_version = require_minimum_version(
                launcher_manifest.get("remote_version"),
                MIN_SUPPORTED_LAUNCHER_VERSION,
                identity_name="已验证签名清单启动器版本",
            )
            launcher_source_name = (
                str(launcher_manifest.get("source_name", "GitHub")).strip() or "GitHub"
            )
            launcher_update_available = _version_is_newer(launcher_remote_version, LAUNCHER_VERSION)
            launcher_package_size = self._manifest_package_size(launcher_manifest)
            if launcher_update_available and launcher_package_size is None:
                launcher_package_url = str(launcher_manifest.get("package_url", "")).strip()
                if launcher_package_url:
                    launcher_package_size = _fetch_content_length(
                        launcher_package_url, timeout_sec=NET_TIMEOUT_SEC
                    )
        except Exception as exc:
            launcher_check_warning = str(exc)
            _log(self.base, f"启动器更新检查失败，应用更新检查继续：{exc}")

        return {
            "local_version": local_version,
            "remote_version": remote_version,
            "min_launcher_version": min_launcher_version,
            "source_name": source_name,
            "update_available": update_available,
            "app_requires_launcher_update": app_requires_launcher_update,
            "package_size": package_size,
            "manifest": manifest,
            "terrain_manifest": terrain_manifest,
            "terrain_local_revision": terrain_local_revision,
            "terrain_remote_revision": terrain_remote_revision,
            "terrain_source_name": terrain_source_name,
            "terrain_update_available": terrain_update_available,
            "terrain_download_size": terrain_download_size,
            "terrain_reuse_size": terrain_reuse_size,
            "terrain_remote_map_count": terrain_remote_map_count,
            "terrain_remote_total_size": terrain_remote_total_size,
            "terrain_catalog": terrain_catalog,
            "terrain_catalog_map_count": terrain_catalog_map_count,
            "terrain_catalog_selected_count": terrain_catalog_selected_count,
            "terrain_catalog_selected_map_ids": terrain_catalog_selected_map_ids,
            "terrain_selection_size_bytes": terrain_selection_size_bytes,
            "terrain_check_warning": terrain_check_warning,
            "terrain_check_blocking": terrain_check_blocking,
            "launcher_manifest": launcher_manifest,
            "launcher_remote_version": launcher_remote_version,
            "launcher_source_name": launcher_source_name,
            "launcher_update_available": launcher_update_available,
            "launcher_package_size": launcher_package_size,
            "launcher_check_warning": launcher_check_warning,
        }

    def download_app_update(self, manifest: Dict[str, Any]) -> Tuple[str, str]:
        resolved = dict(manifest)
        download_headers: Optional[Dict[str, str]] = None
        if (
            _normalize_channel(self.channel) == "Enhanced"
            and not _DISTRIBUTION_BUILD_METADATA.isolated_test
        ):
            if self.subscriber_artifact_provider is None:
                raise RuntimeError("超级爆弹版必须通过 CheemsPay 下载私有应用包")
            resource = str(resolved.get("package_resource", "")).strip()
            if not resource:
                raise RuntimeError("订阅应用清单缺少私有包资源")
            access = _authorized_subscriber_artifact(
                self.subscriber_artifact_provider,
                resource,
            )
            resolved["package_url"] = access.download_url
            download_headers = access.headers()
        return _download_update_from_manifest(
            self.base,
            resolved,
            status_cb=self.notify,
            cancel_cb=self.cancel_cb,
            download_headers=download_headers,
            allow_redirects=(_normalize_channel(self.channel) != "Enhanced"),
            channel=self.channel,
        )

    def download_terrain_update(
        self,
        manifest: Dict[str, Any],
    ) -> (
        _launcher_terrain_store.TerrainSyncResult
        | _launcher_terrain_store.TerrainCatalogSyncResult
    ):
        if _terrain_catalog_document(manifest) is not None:
            return _download_terrain_catalog_from_manifest(
                self.base,
                manifest,
                status_cb=self.notify,
                map_progress_cb=self.terrain_map_progress_cb,
                cancel_cb=self.cancel_cb,
                subscriber_artifact_provider=(
                    self.subscriber_artifact_provider
                    if (
                        _normalize_channel(self.channel) == "Enhanced"
                        and not _DISTRIBUTION_BUILD_METADATA.isolated_test
                    )
                    else None
                ),
            )
        return _download_terrain_update_from_manifest(
            self.base,
            manifest,
            status_cb=self.notify,
            cancel_cb=self.cancel_cb,
            channel=self.channel,
            subscriber_artifact_provider=(
                self.subscriber_artifact_provider
                if _normalize_channel(self.channel) == "Enhanced"
                else None
            ),
        )

    def fetch_whats_new(self, manifest: Dict[str, Any]) -> str:
        changelog_url = str(manifest.get("changelog_url", "")).strip()
        request_headers: Dict[str, str] = {
            "Accept": "text/plain, text/markdown, */*"
        }
        if (
            _normalize_channel(self.channel) == "Enhanced"
            and not _DISTRIBUTION_BUILD_METADATA.isolated_test
        ):
            if self.subscriber_artifact_provider is None:
                raise RuntimeError("超级爆弹版必须通过 CheemsPay 下载私有更新日志")
            resource = str(manifest.get("changelog_resource", "")).strip()
            if not resource:
                raise RuntimeError("订阅应用清单缺少私有更新日志资源")
            access = _authorized_subscriber_artifact(
                self.subscriber_artifact_provider,
                resource,
            )
            changelog_url = access.download_url
            request_headers.update(access.headers())
        expected_sha256 = _require_remote_checksum(
            manifest.get("changelog_sha256", ""),
            artifact_label="更新日志清单",
        )
        if not changelog_url:
            raise RuntimeError("更新日志地址缺失")
        # Do not honor cancel_cb here: install already succeeded; aborting notes
        # fetch must not leave the GUI stuck mid-download state.
        content = _fetch_bytes(
            changelog_url,
            headers=request_headers,
            max_bytes=512 * 1024,
            allow_redirects=(_normalize_channel(self.channel) != "Enhanced"),
        )
        if len(content) > 512 * 1024:
            raise RuntimeError("更新日志超过 512 KiB 限制")
        if _sha256_bytes(content) != expected_sha256:
            raise RuntimeError("更新日志 SHA256 校验失败")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise RuntimeError("更新日志不是有效 UTF-8") from exc
        if not text.strip():
            raise RuntimeError("更新日志内容为空")
        return text

    def download_launcher_update(self, manifest: Dict[str, Any]) -> Tuple[str, str]:
        return _download_launcher_update_from_manifest(
            self.base,
            manifest,
            status_cb=self.notify,
            cancel_cb=self.cancel_cb,
        )

    @staticmethod
    def _manifest_package_size(manifest: Dict[str, Any]) -> Optional[int]:
        package_size_raw = manifest.get("package_size", None)
        try:
            if package_size_raw is not None and str(package_size_raw).strip() != "":
                return int(str(package_size_raw).strip())
        except Exception:
            return None
        return None


def _check_for_update(
    base: Path,
    channel: str,
    identity: Dict[str, str],
    download_source_mode: str = DOWNLOAD_SOURCE_MODE_AUTO,
    status_cb: Optional[Callable[[str, str, Optional[float], str], None]] = None,
) -> Dict[str, Any]:
    def notify(
        title: str,
        detail: str = "",
        progress: Optional[float] = None,
        level: str = "info",
    ) -> None:
        if status_cb:
            status_cb(title, detail, progress, level)

    return UpdateService(
        base,
        channel,
        identity,
        download_source_mode=download_source_mode,
        status_cb=notify,
    ).check()


def _download_update_from_manifest(
    base: Path,
    manifest: Dict[str, Any],
    status_cb: Optional[Callable[[str, str, Optional[float], str], None]] = None,
    cancel_cb: Optional[Callable[[], bool]] = None,
    download_headers: Optional[Dict[str, str]] = None,
    allow_redirects: bool = True,
    channel: object | None = None,
) -> Tuple[str, str]:
    def notify(
        title: str,
        detail: str = "",
        progress: Optional[float] = None,
        level: str = "info",
    ) -> None:
        if status_cb:
            status_cb(title, detail, progress, level)

    remote_version = require_minimum_version(
        manifest.get("remote_version"),
        MIN_SUPPORTED_APP_VERSION,
        identity_name="已验证签名清单应用版本",
    )
    min_launcher_version = require_minimum_version(
        manifest.get("min_launcher_version"),
        MIN_SUPPORTED_LAUNCHER_VERSION,
        identity_name="已验证签名清单最低启动器版本",
    )
    package_url = str(manifest.get("package_url", "")).strip()
    package_asset = str(manifest.get("package_asset", "")).strip()
    package_sha256 = _require_remote_checksum(
        manifest.get("package_sha256", ""),
        artifact_label="应用更新清单 ",
    )
    entrypoint = str(manifest.get("entrypoint", DEFAULT_ENTRYPOINT)).strip() or DEFAULT_ENTRYPOINT
    source_name = str(manifest.get("source_name", "GitHub")).strip() or "GitHub"
    if not package_url:
        raise RuntimeError("更新清单字段缺失")
    package_sha256 = _require_remote_checksum(
        package_sha256,
        artifact_label="应用更新清单",
    )
    canonical_channel = install_txn.normalize_app_channel(channel)
    signed_manifest = manifest.get("signed_manifest")
    if canonical_channel is not None:
        if not isinstance(signed_manifest, dict):
            raise RuntimeError("应用更新清单缺少已签名安装身份")
        install_txn.build_signed_installation_identity(
            signed_manifest,
            channel=canonical_channel,
            package_sha256=package_sha256,
            entrypoint=entrypoint,
            expected_version=remote_version,
        )
    if min_launcher_version and not _launcher_meets_minimum(min_launcher_version):
        raise RuntimeError(
            f"此版本要求先更新启动器（当前 v{LAUNCHER_VERSION}，要求 >= v{min_launcher_version}）"
        )
    _assert_app_install_dir_writable(base)

    notify("开始下载", f"正在下载 v{remote_version}（来源：{source_name}）", 0.24, "info")
    last_emit = [0.0]
    speed_state = {
        "time": time.monotonic(),
        "downloaded": 0,
        "bps": 0.0,
    }

    def _fmt_speed_text(bps: float) -> str:
        if bps >= 1048576:
            return f"{bps / 1048576:.2f} MB/s"
        if bps >= 1024:
            return f"{bps / 1024:.1f} KB/s"
        return f"{max(0.0, bps):.0f} B/s"

    def on_progress(downloaded: int, total: Optional[int]) -> None:
        now = time.monotonic()
        if (now - last_emit[0]) < 0.15 and total and downloaded < total:
            return
        last_emit[0] = now

        dt = now - float(speed_state["time"])
        db = downloaded - int(speed_state["downloaded"])
        if dt > 0 and db >= 0:
            inst_bps = db / dt
            prev_bps = float(speed_state["bps"])
            speed_state["bps"] = inst_bps if prev_bps <= 0 else (prev_bps * 0.65 + inst_bps * 0.35)
            speed_state["time"] = now
            speed_state["downloaded"] = downloaded

        speed_text = _fmt_speed_text(float(speed_state["bps"]))

        if total and total > 0:
            percent = downloaded / float(total)
            progress = 0.24 + min(0.56, 0.56 * percent)
            detail = f"正在下载应用包：{downloaded / 1048576:.1f} / {total / 1048576:.1f} MB  |  {speed_text}"
            notify("正在下载更新", detail, progress, "info")
        else:
            detail = f"正在下载应用包：{downloaded / 1048576:.1f} MB  |  {speed_text}"
            notify("正在下载更新", detail, None, "info")

    download_dir = _launcher_download_dir(base)
    package_path = download_dir / _download_cache_filename(
        "Bomana_app",
        remote_version,
        package_asset or package_url,
        package_sha256,
        ".zip",
    )
    keep_downloaded_file = False
    try:
        _download_to_file(
            package_url,
            package_path,
            progress_cb=on_progress,
            cancel_cb=cancel_cb,
            headers=download_headers,
            allow_redirects=allow_redirects,
        )
        if cancel_cb and cancel_cb():
            raise RuntimeError("已取消当前操作")
        actual_sha256 = install_txn.sha256_file(package_path)
        if actual_sha256 != package_sha256:
            try:
                package_path.unlink(missing_ok=True)
                package_path.with_name(f"{package_path.name}.part").unlink(missing_ok=True)
            except Exception:
                pass
            raise RuntimeError("SHA256 校验失败")
        keep_downloaded_file = True
        install_txn.install_zip_package_from_file(
            base,
            package_path,
            package_sha256,
            entrypoint,
            status_cb=notify,
            cancel_cb=cancel_cb,
            expected_version=remote_version,
            channel=channel,
            signed_manifest=signed_manifest if isinstance(signed_manifest, dict) else None,
        )
    finally:
        try:
            if not keep_downloaded_file:
                package_path.unlink(missing_ok=True)
        except Exception:
            pass
    notify(
        "更新完成",
        f"已更新到 v{remote_version}\n下载包保留在：{package_path}",
        1.0,
        "success",
    )
    return remote_version, source_name


def _launch_updater_script(script_path: Path) -> None:
    powershell = _system_windows_powershell_exe()
    creation_flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creation_flags |= subprocess.CREATE_NO_WINDOW
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creation_flags |= subprocess.DETACHED_PROCESS
    subprocess.Popen(
        [
            str(powershell),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        cwd=str(powershell.parent),
        close_fds=True,
        creationflags=creation_flags,
    )


def _assert_launcher_target_dir_writable(target: Path) -> None:
    """Check write and rename permission before downloading a launcher replacement."""
    directory = target.parent
    probe = directory / f".bomana_launcher_write_probe_{os.getpid()}_{time.monotonic_ns()}"
    renamed_probe = probe.with_suffix(".renamed")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        os.replace(probe, renamed_probe)
    except Exception as exc:
        raise RuntimeError(
            "当前启动器目录不可写，无法自动替换启动器："
            f"{directory}。请将启动器放到可写目录，或以管理员权限运行后重试。原始错误：{exc}"
        ) from exc
    finally:
        for path in (probe, renamed_probe):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass


def _assert_app_install_dir_writable(base: Path) -> None:
    """Check install-root write, lock, temp creation, and rename before a large app download."""
    lock_path: Optional[Path] = None
    probe_dir: Optional[Path] = None
    renamed_probe: Optional[Path] = None
    try:
        base.mkdir(parents=True, exist_ok=True)
        lock_path = install_txn.acquire_update_lock(base)
        probe_dir = Path(tempfile.mkdtemp(prefix=".bomana_install_probe_", dir=str(base)))
        renamed_probe = base / f"{probe_dir.name}.renamed"
        os.replace(str(probe_dir), str(renamed_probe))
        probe_dir = None
    except Exception as exc:
        raise RuntimeError(
            "当前启动器目录不可写，无法自动安装应用更新："
            f"{base}。请将启动器整个文件夹移动到可写目录（例如桌面或下载目录下的 Bomana 文件夹），"
            f"或以管理员权限运行后重试。原始错误：{exc}"
        ) from exc
    finally:
        if renamed_probe is not None:
            shutil.rmtree(renamed_probe, ignore_errors=True)
        if probe_dir is not None:
            shutil.rmtree(probe_dir, ignore_errors=True)
        install_txn.release_update_lock(lock_path)


def _stage_launcher_self_update(
    base: Path,
    launcher_bytes: Optional[bytes],
    remote_version: str,
    launcher_source_path: Optional[Path] = None,
    expected_sha256: str = "",
) -> None:
    if not _is_frozen_launcher():
        raise RuntimeError("源码模式不支持启动器自更新")
    if launcher_source_path is None and launcher_bytes is None:
        raise RuntimeError("缺少启动器更新文件")

    running_launcher = Path(sys.executable).resolve()
    target = _launcher_self_update.stable_launcher_path(running_launcher)
    work_dir = Path(tempfile.mkdtemp(prefix=LAUNCHER_SELF_UPDATE_WORKDIR_PREFIX))
    staged = work_dir / f"{target.stem}.update.new{target.suffix}"
    script_path = work_dir / "bomana_update_launcher_apply.ps1"
    result_path = _data_path(base, LAUNCHER_UPDATE_RESULT_FILE_NAME)

    try:
        result_path.unlink(missing_ok=True)
        if launcher_source_path is not None:
            shutil.copyfile(launcher_source_path, staged)
        else:
            staged.write_bytes(launcher_bytes or b"")
        expected_sha256 = (expected_sha256 or install_txn.sha256_file(staged)).strip().lower()
        _log(base, f"已在临时目录准备启动器自更新文件：{staged}")
        script = _launcher_self_update.render_launcher_update_helper(
            target=target,
            running_launcher=running_launcher,
            staged=staged,
            result_path=result_path,
            expected_sha256=expected_sha256,
            old_pid=os.getpid(),
            target_version=remote_version,
        )
        script_path.write_text(script, encoding="utf-8-sig")
        _launch_updater_script(script_path)
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise


def _download_launcher_update_from_manifest(
    base: Path,
    manifest: Dict[str, Any],
    status_cb: Optional[Callable[[str, str, Optional[float], str], None]] = None,
    cancel_cb: Optional[Callable[[], bool]] = None,
) -> Tuple[str, str]:
    def notify(
        title: str,
        detail: str = "",
        progress: Optional[float] = None,
        level: str = "info",
    ) -> None:
        if status_cb:
            status_cb(title, detail, progress, level)

    remote_version = str(manifest.get("remote_version", "")).strip()
    package_url = str(manifest.get("package_url", "")).strip()
    package_asset = str(manifest.get("package_asset", "")).strip()
    package_sha256 = _require_remote_checksum(
        manifest.get("package_sha256", ""),
        artifact_label="启动器更新清单 ",
    )
    source_name = str(manifest.get("source_name", "GitHub")).strip() or "GitHub"
    if not remote_version or not package_url:
        raise RuntimeError("启动器更新清单字段缺失")
    package_sha256 = _require_remote_checksum(
        package_sha256,
        artifact_label="启动器更新清单",
    )

    notify(
        "开始下载启动器",
        f"正在下载新版启动器文件 v{remote_version}（来源：{source_name}）",
        0.18,
        "info",
    )

    if _is_frozen_launcher():
        _assert_launcher_target_dir_writable(
            _launcher_self_update.stable_launcher_path(Path(sys.executable).resolve())
        )

    last_emit = [0.0]

    def on_progress(downloaded: int, total: Optional[int]) -> None:
        now = time.monotonic()
        if (now - last_emit[0]) < 0.15 and total and downloaded < total:
            return
        last_emit[0] = now
        if total and total > 0:
            progress = 0.18 + min(0.62, 0.62 * (downloaded / float(total)))
            detail = (
                f"正在下载新版启动器文件：{downloaded / 1048576:.1f} / {total / 1048576:.1f} MB"
            )
            notify("正在下载启动器", detail, progress, "info")
        else:
            notify(
                "正在下载启动器",
                f"正在下载新版启动器文件：{downloaded / 1048576:.1f} MB",
                None,
                "info",
            )

    download_dir = _launcher_download_dir(base)
    launcher_path = download_dir / _download_cache_filename(
        "Bomana_launcher",
        remote_version,
        package_asset or package_url,
        package_sha256,
        ".exe",
    )
    stage_attempted = False
    keep_downloaded_file = False
    try:
        _download_to_file(package_url, launcher_path, progress_cb=on_progress, cancel_cb=cancel_cb)
        if cancel_cb and cancel_cb():
            raise RuntimeError("已取消当前操作")
        actual_sha256 = install_txn.sha256_file(launcher_path)
        if actual_sha256 != package_sha256:
            try:
                launcher_path.unlink(missing_ok=True)
                launcher_path.with_name(f"{launcher_path.name}.part").unlink(missing_ok=True)
            except Exception:
                pass
            raise RuntimeError("SHA256 校验失败")
        keep_downloaded_file = True
        current_name = _launcher_self_update.stable_launcher_path(
            Path(sys.executable).resolve()
        ).name
        notify(
            "准备替换启动器",
            (
                f"新版启动器文件已下载完成；关闭当前窗口后会替换 {current_name} 并自动重启。\n"
                f"下载文件保留在：{launcher_path}"
            ),
            0.9,
            "info",
        )
        stage_attempted = True
        _stage_launcher_self_update(
            base,
            None,
            remote_version,
            launcher_source_path=launcher_path,
            expected_sha256=package_sha256,
        )
    except Exception:
        keep_downloaded_file = stage_attempted and launcher_path.exists()
        if keep_downloaded_file:
            _log(base, f"启动器更新文件保留在：{launcher_path}")
        raise
    finally:
        try:
            if not keep_downloaded_file:
                launcher_path.unlink(missing_ok=True)
        except Exception:
            pass

    notify(
        "启动器更新已就绪",
        (
            f"已准备好升级到 v{remote_version}；当前窗口即将关闭，随后会自动替换当前 exe 并重启。\n"
            f"下载文件保留在：{launcher_path}"
        ),
        1.0,
        "success",
    )
    return remote_version, source_name


def _source_site_packages(base: Path) -> Tuple[Path, ...]:
    return _launcher_bootstrap.source_site_packages(base)


def _prepare_source_test_runtime(base: Path) -> None:
    return _launcher_bootstrap.prepare_source_test_runtime(base)


def _reset_embedded_app_modules() -> None:
    return _launcher_bootstrap.reset_embedded_app_modules()


def _path_is_within(path: Path, root: Path) -> bool:
    return _launcher_bootstrap.path_is_within(path, root)


def _spec_points_within(spec: Any, root: Path) -> bool:
    return _launcher_bootstrap.spec_points_within(spec, root)


_AppPackageBomanaFinder = _launcher_bootstrap.AppPackageBomanaFinder


def _launch_app(base: Path, channel: str) -> None:
    terrain_dir: Optional[Path] = None
    displayed_recovery_warning = _PENDING_DISPLAYED_RECOVERY_WARNING
    normalized_channel = _normalize_channel(channel)
    if normalized_channel == "Enhanced":
        terrain_store = _terrain_store_for_base(base)
        terrain_dir = terrain_store.current_catalog_pack_dir() or terrain_store.current_pack_dir()
        if terrain_dir is None and not _is_source_test_run(base):
            legacy_bundled = _app_runtime_dir(base, normalized_channel) / "bomana" / "data" / "terrain-v1"
            if legacy_bundled.is_dir():
                terrain_dir = legacy_bundled
            else:
                terrain_notice = _launcher_terrain_store.TERRAIN_ACCURACY_NOTICE
                displayed_recovery_warning = "\n".join(
                    value
                    for value in (displayed_recovery_warning, terrain_notice)
                    if value
                )
    _APP_HOST_ACTIVE.set()
    try:
        entrypoint = _app_entrypoint_for_runtime(base, normalized_channel)
        return _launcher_bootstrap.launch_app(
            base,
            channel,
            recover_incomplete_install=_recover_incomplete_install,
            app_runtime_dir=lambda path: _app_runtime_dir(path, normalized_channel),
            is_local_app_ready=lambda path: _is_local_app_ready(path, normalized_channel),
            is_source_test_run=_is_source_test_run,
            read_app_version=install_txn.read_app_version_identity,
            default_entrypoint=entrypoint,
            web_dashboard_autostart=_PENDING_WEB_DASHBOARD_AUTOSTART,
            web_dashboard_auto_open=_PENDING_WEB_DASHBOARD_AUTO_OPEN,
            web_dashboard_lan_enabled=_PENDING_WEB_DASHBOARD_LAN_ENABLED,
            terrain_dir=terrain_dir,
            displayed_recovery_warning=displayed_recovery_warning,
            recovery_warning_callback=_show_handoff_recovery_warning,
        )
    finally:
        _APP_HOST_ACTIVE.clear()
        with contextlib.suppress(Exception):
            _terrain_store_for_base(base).prune_after_host_exit(
                app_host_active=_APP_HOST_ACTIVE.is_set,
            )


def _friendly_error_text(err: Exception, channel: str) -> str:
    msg = str(err)
    if "已取消" in msg:
        return "已取消当前操作。"
    if "要求先更新启动器" in msg:
        return f"{msg}。请先更新启动器后再安装 {_channel_display_name(channel)}的新版本。"
    if "地形" in msg and ("缺少" in msg or "不可用" in msg or "下载源均失败" in msg):
        return f"{msg} 请在启动器中重新检查并差量更新地形数据。"
    if isinstance(err, (URLError, TimeoutError)):
        return "网络连接失败。请确认网络可用后点击“重试”。"
    if isinstance(err, HTTPError):
        if err.code == 403:
            return "远端访问频率受限（HTTP 403）。请稍后重试。"
        return f"下载服务器返回错误（HTTP {err.code}）。请稍后重试。"
    if "未找到发布清单" in msg:
        return f"当前通道（{channel}）的在线更新文件暂未发布。请点击“打开下载页”。"
    if "国内更新服务不可用" in msg and "GitHub 回退失败" in msg:
        return "国内更新服务与 GitHub 回退均不可用。请检查网络后重试，或点击“打开下载页”手动下载。"
    if "SHA256 校验失败" in msg:
        return "下载文件校验失败，已自动拦截。请点击“重试”。"
    if "缺少 SHA256 校验值" in msg:
        return "更新清单缺少 SHA256 校验值，已拒绝下载或安装。请稍后重试或联系维护者。"
    if "发布清单字段缺失" in msg:
        return "更新清单格式异常。请稍后重试或联系维护者。"
    if "更新清单字段缺失" in msg:
        return "在线更新接口返回异常。请稍后重试。"
    return f"更新失败：{msg}"


def _format_app_launch_error(
    base: Path, err: Exception, final_version: str, channel: str, source_test_mode: bool
) -> str:
    if source_test_mode and isinstance(err, ModuleNotFoundError):
        missing = getattr(err, "name", "") or str(err)
        site_packages = _source_site_packages(base)
        venv_hint = (
            f"已检测到项目虚拟环境：{base / '.venv'}\n"
            "请优先使用 `uv run --python 3.14 python launcher.pyw` 启动；"
            "如果刚升级过解释器，也可重新执行 `uv sync --python 3.14 --extra build`。"
            if site_packages
            else "当前源码模式未检测到可复用的项目虚拟环境。\n请先执行 `uv sync --python 3.14 --extra build`。"
        )
        return (
            "无法启动应用。\n"
            f"名称: {DISPLAY_NAME}\n"
            f"版本: {final_version}\n"
            f"通道: {channel}\n"
            f"错误: 缺少依赖模块 {missing}\n"
            f"当前解释器: {sys.executable}\n"
            "原因: 源码模式会直接用当前 Python 运行 Bomana.pyw。\n"
            f"{venv_hint}\n"
            "详细栈信息请检查 launcher.log。"
        )
    return (
        "无法启动应用。\n"
        f"名称: {DISPLAY_NAME}\n"
        f"版本: {final_version}\n"
        f"通道: {channel}\n"
        f"错误: {err}\n"
        "请检查 launcher.log。"
    )


class LauncherDetailsDialog(tk.Toplevel):
    """Launcher detail/about dialog with content structure similar to main app."""

    def __init__(
        self,
        parent: tk.Tk,
        channel: str,
        local_version: str,
        launcher_version: str,
        install_dir: Path,
        terrain_dir: Optional[Path] = None,
        terrain_revision: str = "",
    ):
        super().__init__(parent)
        self.title("关于 Bomana")
        self.configure(bg=_THEME["BG"])
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()
        _apply_window_icon(self)
        self._images: list = []

        self._build_ui(
            channel,
            local_version,
            launcher_version,
            install_dir,
            terrain_dir,
            terrain_revision,
        )
        self._fit_window_to_parent(parent)
        self._center_on_parent(parent)

    def _build_ui(
        self,
        channel: str,
        local_version: str,
        launcher_version: str,
        install_dir: Path,
        terrain_dir: Optional[Path],
        terrain_revision: str,
    ) -> None:
        wrap_w = 760

        container = tk.Frame(self, bg=_THEME["BG"])
        container.pack(fill="both", expand=True, padx=12, pady=10)

        canvas = tk.Canvas(container, bg=_THEME["BG"], highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        content = tk.Frame(canvas, bg=_THEME["BG"])
        win_id = canvas.create_window((0, 0), window=content, anchor="nw")

        def on_content_configure(_event: tk.Event) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_configure(event: tk.Event) -> None:
            canvas.itemconfig(win_id, width=event.width)

        def on_mousewheel(event: tk.Event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        content.bind("<Configure>", on_content_configure)
        canvas.bind("<Configure>", on_canvas_configure)
        # Bind mousewheel globally to ensure it works over all widgets
        canvas.bind_all("<MouseWheel>", on_mousewheel)

        # Unbind when dialog is closed
        def _cleanup(_e=None) -> None:
            try:
                canvas.unbind_all("<MouseWheel>")
            except Exception:
                pass

        self.bind("<Destroy>", lambda e: _cleanup() if e.widget == self else None, "+")

        title_row = tk.Frame(content, bg=_THEME["BG"])
        title_row.pack(fill="x", pady=(4, 8))

        try:
            from PIL import Image, ImageTk  # type: ignore

            icon_file = _resource_path(BRANDING_ICON_FILE)
            if icon_file.exists():
                img = Image.open(icon_file).convert("RGBA")
                img = img.resize((56, 56), Image.Resampling.LANCZOS)
                icon_img = ImageTk.PhotoImage(img)
                self._images.append(icon_img)
                tk.Label(title_row, image=icon_img, bg=_THEME["BG"]).pack(side="left", padx=(0, 12))
        except Exception:
            pass

        title_text = tk.Frame(title_row, bg=_THEME["BG"])
        title_text.pack(side="left", fill="both", expand=True)
        tk.Label(
            title_text,
            text=f"{DISPLAY_NAME} Launcher v{launcher_version}",
            font=("Segoe UI", 20, "bold"),
            fg=_THEME["TEXT"],
            bg=_THEME["BG"],
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_text,
            text="战雷全真模式收益计时器（绿色启动器）",
            font=("Segoe UI", 12),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["BG"],
            anchor="w",
        ).pack(anchor="w", pady=(4, 0))

        tk.Frame(content, bg=_THEME["BORDER"], height=1).pack(fill="x", pady=10)

        desc = (
            "本启动器用于检查更新、下载应用包并启动 Bomana 主程序。\n"
            "仅在你确认后才会执行下载，支持离线启动本地已安装版本。"
        )
        tk.Label(
            content,
            text=desc,
            font=("Segoe UI", 11),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["BG"],
            justify="left",
            anchor="w",
            wraplength=wrap_w,
        ).pack(anchor="w")

        info_lines = [
            f"当前通道：{channel}",
            f"本地版本：v{local_version}",
            f"安装目录：{install_dir}",
        ]
        if _normalize_channel(channel) == "Enhanced":
            info_lines.append(f"高程数据目录：{terrain_dir or '尚未安装'}")
            if terrain_revision:
                info_lines.append(f"高程数据修订：{terrain_revision[:12]}")
        info_lines.append(f"启动器版本：v{launcher_version}")
        info_text = "\n".join(info_lines)
        tk.Label(
            content,
            text=info_text,
            font=("Segoe UI", 11),
            fg=_THEME["TEXT"],
            bg=_THEME["BG"],
            justify="left",
            anchor="w",
        ).pack(anchor="w", pady=(10, 2))

        link_row = tk.Frame(content, bg=_THEME["BG"])
        link_row.pack(fill="x", pady=(8, 0))
        tk.Label(
            link_row,
            text="项目主页：",
            font=("Segoe UI", 11),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["BG"],
        ).pack(side="left")
        gh = tk.Label(
            link_row,
            text=PROJECT_URL,
            font=("Segoe UI", 11, "underline"),
            fg=_THEME["BLUE"],
            bg=_THEME["BG"],
            cursor="hand2",
        )
        gh.pack(side="left")
        gh.bind("<Button-1>", lambda _e: webbrowser.open(PROJECT_URL))

        rel_row = tk.Frame(content, bg=_THEME["BG"])
        rel_row.pack(fill="x", pady=(4, 0))
        tk.Label(
            rel_row,
            text="最新发布：",
            font=("Segoe UI", 11),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["BG"],
        ).pack(side="left")
        rel = tk.Label(
            rel_row,
            text=RELEASES_URL,
            font=("Segoe UI", 11, "underline"),
            fg=_THEME["BLUE"],
            bg=_THEME["BG"],
            cursor="hand2",
        )
        rel.pack(side="left")
        rel.bind("<Button-1>", lambda _e: webbrowser.open(RELEASES_URL))

        tk.Frame(content, bg=_THEME["BORDER"], height=1).pack(fill="x", pady=12)

        tk.Label(
            content,
            text="支持作者",
            font=("Segoe UI", 14, "bold"),
            fg=_THEME["TEXT"],
            bg=_THEME["BG"],
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            content,
            text="如果这个工具对你有帮助，欢迎请作者喝杯咖啡~",
            font=("Segoe UI", 11),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["BG"],
            anchor="w",
        ).pack(anchor="w", pady=(4, 10))

        sponsor_shown = False
        try:
            from PIL import Image, ImageTk  # type: ignore

            sponsor_file = _resource_path(BRANDING_SPONSOR_FILE)
            if sponsor_file.exists():
                img = Image.open(sponsor_file).convert("RGBA")
                target_w = 360
                ratio = target_w / float(img.width)
                img = img.resize(
                    (target_w, max(1, int(img.height * ratio))),
                    Image.Resampling.LANCZOS,
                )
                sponsor_img = ImageTk.PhotoImage(img)
                self._images.append(sponsor_img)
                tk.Label(content, image=sponsor_img, bg=_THEME["BG"]).pack(anchor="w")
                sponsor_shown = True
        except Exception:
            sponsor_shown = False

        if not sponsor_shown:
            tk.Label(
                content,
                text="赞助二维码资源未找到（可在主程序中查看完整赞助页）。",
                font=("Segoe UI", 10),
                fg=_THEME["TEXT_MUTED"],
                bg=_THEME["BG"],
                anchor="w",
            ).pack(anchor="w")

        tk.Frame(content, bg=_THEME["BORDER"], height=1).pack(fill="x", pady=12)

        # Privacy notice
        privacy_frame = tk.Frame(content, bg=_THEME["BG"])
        privacy_frame.pack(fill="x", pady=(0, 8))

        tk.Label(
            privacy_frame,
            text="隐私说明：",
            font=("Segoe UI", 10, "bold"),
            fg=_THEME["BLUE"],
            bg=_THEME["BG"],
            anchor="w",
        ).pack(anchor="w")

        tk.Label(
            privacy_frame,
            text="本应用收集匿名DAU数据（设备ID、版本号等）用于统计分析，不涉及个人隐私。",
            font=("Segoe UI", 9),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["BG"],
            anchor="w",
            wraplength=580,
            justify="left",
        ).pack(anchor="w", pady=(2, 0))

        privacy_link = tk.Label(
            privacy_frame,
            text="查看详细隐私政策 →",
            font=("Segoe UI", 9, "underline"),
            fg=_THEME["BLUE"],
            bg=_THEME["BG"],
            cursor="hand2",
            anchor="w",
        )
        privacy_link.pack(anchor="w", pady=(2, 0))
        privacy_link.bind(
            "<Button-1>",
            lambda _: webbrowser.open(f"{PROJECT_URL}/blob/main/docs/PRIVACY.md"),
        )

        tk.Frame(content, bg=_THEME["BORDER"], height=1).pack(fill="x", pady=12)

        tk.Label(
            content,
            text="MIT License  |  Copyright © 2024-2026 Thankyou-Cheems",
            font=("Segoe UI", 10),
            fg=_THEME["TEXT_MUTED"],
            bg=_THEME["BG"],
            anchor="w",
        ).pack(anchor="w")

        tk.Button(
            content,
            text="关闭",
            command=self.destroy,
            bg="#2b3542",
            fg=_THEME["TEXT"],
            activebackground="#3b4654",
            activeforeground=_THEME["TEXT"],
            relief="flat",
            bd=1,
            highlightthickness=1,
            highlightbackground="#4c5a6b",
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
            padx=20,
            pady=6,
        ).pack(pady=(16, 4), anchor="center")

    def _fit_window_to_parent(self, parent: tk.Tk) -> None:
        self.update_idletasks()
        req_w = self.winfo_reqwidth()
        req_h = self.winfo_reqheight()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        parent_w = max(760, parent.winfo_width())
        parent_h = max(560, parent.winfo_height())

        # Keep the dialog large enough so sponsor image area is visible by default.
        w = min(max(req_w, int(parent_w * 0.9), 780), screen_w - 70)
        h = min(max(req_h, int(parent_h * 0.9), 640), screen_h - 70)
        self.geometry(f"{int(w)}x{int(h)}")
        self.minsize(720, 560)

    def _center_on_parent(self, parent: tk.Tk) -> None:
        self.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_x()
        py = parent.winfo_y()
        w = self.winfo_width()
        h = self.winfo_height()
        x = max(0, px + (pw - w) // 2)
        y = max(0, py + (ph - h) // 2)
        self.geometry(f"+{x}+{y}")


class WhatsNewDialog(tk.Toplevel):
    """Verified release notes shown after a successful App update."""

    def __init__(self, parent: tk.Tk, version: str, source_name: str, content: str):
        super().__init__(parent)
        self.title("What's New")
        self.configure(bg=_THEME["BG"])
        self.transient(parent)
        self.geometry("720x560")
        self.minsize(560, 420)
        _apply_window_icon(self)
        self.protocol("WM_DELETE_WINDOW", self._close)
        body = str(content or "").strip()
        if not body:
            body = "本次更新未提供可读的更新说明，但安装已完成。"

        tk.Label(
            self,
            text=f"Bomana v{version} · What's New",
            bg=_THEME["BG"],
            fg=_THEME["TEXT"],
            font=("Segoe UI", 16, "bold"),
            anchor="w",
        ).pack(fill="x", padx=18, pady=(16, 4))
        tk.Label(
            self,
            text=f"已从 {source_name or '当前更新渠道'} 获取并通过 SHA256 校验",
            bg=_THEME["BG"],
            fg=_THEME["TEXT_DIM"],
            anchor="w",
        ).pack(fill="x", padx=18, pady=(0, 10))
        frame = tk.Frame(self, bg=_THEME["BORDER"])
        frame.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")
        text = tk.Text(
            frame,
            wrap="word",
            bg=_THEME["CARD"],
            fg=_THEME["TEXT"],
            insertbackground=_THEME["TEXT"],
            relief="flat",
            padx=12,
            pady=10,
            yscrollcommand=scrollbar.set,
        )
        text.pack(fill="both", expand=True, padx=1, pady=1)
        scrollbar.config(command=text.yview)
        text.insert("1.0", body)
        text.config(state="disabled")
        close_btn = tk.Button(self, text="知道了", command=self._close, takefocus=False)
        style_action_button(close_btn, "primary")
        close_btn.pack(side="right", padx=18, pady=(0, 16))
        self.grab_set()
        self.focus_set()
        try:
            self.wait_window(self)
        finally:
            with contextlib.suppress(tk.TclError):
                self.grab_release()

    def _close(self) -> None:
        with contextlib.suppress(tk.TclError):
            self.grab_release()
        with contextlib.suppress(tk.TclError):
            self.destroy()


class LauncherWindow:
    """Simple, user-friendly GUI for launcher status and recovery actions."""

    def __init__(
        self,
        base: Path,
        channel: str,
        recovery_warning: str = "",
        launcher_update_notice: str = "",
    ):
        self.base = base
        self.recovery_warning = str(recovery_warning or "").strip()[:1000]
        self.launcher_update_notice = str(launcher_update_notice or "").strip()[:500]
        self.source_test_mode = _is_source_test_run(base)
        self.saved_state = _read_state(base)
        self.detected_channel = _normalize_channel(channel) or PUBLIC_FALLBACK_CHANNEL
        self.channel = (
            _normalize_channel(self.saved_state.get("channel", ""))
            or self.detected_channel
        )
        self._channel_menu_refreshing = False
        self.download_source_mode = _effective_download_source_mode(
            self.saved_state.get("download_source_mode", "")
        )
        raw_proxy = self.saved_state.get("use_system_proxy", True)
        if isinstance(raw_proxy, str):
            self.use_system_proxy = raw_proxy.strip().lower() in (
                "1",
                "true",
                "yes",
                "on",
            )
        else:
            self.use_system_proxy = bool(raw_proxy)
        self.web_dashboard_autostart = _strict_saved_bool(
            self.saved_state,
            "web_dashboard_autostart",
            DEFAULT_WEB_DASHBOARD_AUTOSTART,
        )
        self.web_dashboard_auto_open = _strict_saved_bool(
            self.saved_state,
            "web_dashboard_auto_open",
            DEFAULT_WEB_DASHBOARD_AUTO_OPEN,
        )
        self.web_dashboard_lan_enabled = _strict_saved_bool(
            self.saved_state,
            "web_dashboard_lan_enabled",
            DEFAULT_WEB_DASHBOARD_LAN_ENABLED,
        )
        if not self.web_dashboard_autostart:
            self.web_dashboard_lan_enabled = False
        _set_use_system_proxy(self.use_system_proxy)
        self.client_identity = _build_client_identity(base)
        self.subscription_workflow: Optional[SubscriptionWorkflow] = None
        self.subscription_setup_error = ""
        self.subscription_decision = SubscriptionAccessDecision(
            allowed=False,
            reason=SubscriptionAccessReason.MISSING_RECEIPT,
        )
        if (
            not self.source_test_mode
            and not _DISTRIBUTION_BUILD_METADATA.isolated_test
            and self.channel == "Enhanced"
        ):
            self._refresh_cached_subscription_access()
        if (
            not self.source_test_mode
            and not _DISTRIBUTION_BUILD_METADATA.isolated_test
            and not self.subscription_decision.allowed
        ):
            if self.channel == "Enhanced":
                self.channel = PUBLIC_FALLBACK_CHANNEL
            if self.detected_channel == "Enhanced":
                self.detected_channel = PUBLIC_FALLBACK_CHANNEL
        self.local_version = install_txn.read_local_app_version(_app_runtime_dir(base, self.channel))
        self.previous_version = install_txn.read_local_app_version(
            _previous_app_dir(base, self.channel)
        )
        self.events: "queue.Queue[Tuple[str, Dict[str, Any]]]" = queue.Queue()
        self.running = False
        self.has_attempted_update = False
        self.indeterminate = True
        self.anim_phase = 0
        self.progress_value = 0.0
        self.current_task = ""
        self.latest_manifest: Optional[Dict[str, Any]] = None
        self.latest_remote_version = self.local_version
        self.latest_min_launcher_version = ""
        self.latest_source_name = ""
        self.latest_package_size: Optional[int] = None
        self.update_available = False
        self.app_requires_launcher_update = False
        self.latest_terrain_manifest: Optional[Dict[str, Any]] = None
        self.terrain_local_state = "missing"
        self.terrain_local_revision = ""
        self.terrain_local_map_count = 0
        self.terrain_local_total_size = 0
        self.terrain_remote_revision = ""
        self.terrain_remote_map_count = 0
        self.terrain_remote_total_size = 0
        self.terrain_catalog_available = False
        self.terrain_catalog_map_count = 0
        self.terrain_catalog_selected_count = 0
        self.terrain_catalog_selected_map_ids: Tuple[str, ...] = ()
        self.terrain_selection_size_bytes = 0
        self.terrain_source_name = ""
        self.terrain_update_available = False
        self.terrain_download_size = 0
        self.terrain_reuse_size = 0
        self.terrain_check_warning = ""
        self.terrain_check_blocking = False
        self.terrain_map_progress: Dict[
            str, _launcher_terrain_store.TerrainMapProgress
        ] = {}
        self._terrain_map_row_renderers: Dict[str, Callable[[], None]] = {}
        self._terrain_map_dialog: Optional[tk.Toplevel] = None
        self.latest_launcher_manifest: Optional[Dict[str, Any]] = None
        self.latest_launcher_version = LAUNCHER_VERSION
        self.latest_launcher_source_name = ""
        self.latest_launcher_package_size: Optional[int] = None
        self.latest_launcher_check_warning = ""
        self.launcher_update_available = False
        self.last_check_ok = False
        self.last_check_error = ""
        self.install_dir = _app_runtime_dir(self.base, self.channel)
        self.last_download_success = False
        self.decision = LaunchDecision(action="exit", final_version=self.local_version)
        self._worker: Optional[threading.Thread] = None
        self._cancel_requested = threading.Event()
        self._exit_after_task = False
        self._recheck_requested = False
        self._spin = _LAUNCHER_SPINNER_FRAMES
        self.status_title = "正在准备"
        self.status_level = "info"
        self.dpi_scale = 1.0
        self.scale = 1.0
        self.font_family = "Segoe UI"
        self.progress_width = 520
        self.progress_height = 12
        self._button_styles: Dict[str, Dict[str, str]] = {}
        self._layout_after_id: Optional[str] = None
        self._base_min_w = self._px(880)
        self._base_min_h = self._px(600)
        self._max_w = self._base_min_w
        self._max_h = self._base_min_h
        self._min_w = self._base_min_w
        self._min_h = self._base_min_h
        self._refresh_local_terrain_snapshot()

        self.root = tk.Tk()
        self.root.title(DISPLAY_NAME)
        _apply_window_icon(self.root)
        self._init_window_scale_context()
        self.root.geometry(f"{self._px(880)}x{self._px(600)}")
        self.root.resizable(True, True)
        self.root.configure(bg=_THEME["BG"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_exit)
        self.channel_var = tk.StringVar(
            master=self.root,
            value=_channel_display_name(self.channel),
        )
        self.proxy_var = tk.BooleanVar(master=self.root, value=self.use_system_proxy)
        self.web_dashboard_autostart_var = tk.BooleanVar(
            master=self.root,
            value=self.web_dashboard_autostart,
        )
        self.web_dashboard_auto_open_var = tk.BooleanVar(
            master=self.root,
            value=self.web_dashboard_auto_open,
        )
        self.web_dashboard_lan_enabled_var = tk.BooleanVar(
            master=self.root,
            value=self.web_dashboard_lan_enabled,
        )
        self.download_source_var = tk.StringVar(
            master=self.root,
            value=_download_source_label(self.download_source_mode),
        )

        self._build_ui()
        self._fit_window_to_screen()
        self.root.bind("<Configure>", self._on_window_configure, add="+")
        self.root.bind("<Control-Return>", self._on_launch_shortcut, add="+")
        self._refresh_wraplengths()
        self._schedule_layout_reflow()
        if self.recovery_warning:
            self._set_status(
                "安装恢复已安全停止",
                self._with_recovery_warning("有效的本地 App 仍可启动；请先处理上述安装槽问题。"),
                0.0,
                "warning",
            )
        elif self.launcher_update_notice:
            self._set_status("启动器更新完成", self.launcher_update_notice, 1.0, "success")
        elif self.source_test_mode:
            self._set_status(
                "源码测试模式",
                "检测到同目录 Bomana.pyw，已跳过自动在线更新检查，将直接启动本地源码。",
                0.0,
                "info",
            )
        else:
            self._set_status(
                "准备就绪", "启动后将自动检查更新，并展示可下载包总大小。", 0.0, "info"
            )
        self._set_running(False)
        self._save_launcher_state()
        _log(
            self.base,
            f"Launcher start, channel={self.channel}, version={LAUNCHER_VERSION}, source_test_mode={self.source_test_mode}",
        )
        if not self.source_test_mode:
            threading.Thread(
                target=_report_primary_event,
                args=(
                    self.base,
                    self.client_identity,
                    "launcher_start",
                    self.channel,
                    self.local_version,
                ),
                daemon=True,
            ).start()
        self.root.after(80, self._poll_events)
        self.root.after(100, self._animate)
        if not self.source_test_mode:
            self.root.after(120, lambda: self._begin_check(automatic=True))

    def _px(self, value: int) -> int:
        # Avoid DPI double-scaling: tk scaling handles DPI globally.
        return max(1, int(round(float(value))))

    def _font(self, size: int, weight: str = "normal") -> Tuple[str, int, str]:
        return (self.font_family, max(8, self._px(size)), weight)

    def _refresh_local_terrain_snapshot(self) -> None:
        self.terrain_local_revision = ""
        self.terrain_local_map_count = 0
        self.terrain_local_total_size = 0
        if not self._terrain_features_visible():
            self.terrain_local_state = "not_applicable"
            return

        store = _terrain_store_for_base(self.base)
        catalog = store.current_catalog()
        if catalog is not None:
            selected_map_ids = store.current_catalog_selection()
            projection = _terrain_catalog_selection_projection(catalog, selected_map_ids)
            self.terrain_local_state = "ready"
            self.terrain_local_revision = catalog.revision
            self.terrain_local_map_count = int(projection["selected_count"])
            self.terrain_local_total_size = int(projection["selected_size_bytes"])
            return
        manifest = store.current_manifest()
        if manifest is not None:
            self.terrain_local_state = "ready"
            self.terrain_local_revision = manifest.revision
            self.terrain_local_map_count = manifest.map_count
            self.terrain_local_total_size = manifest.total_size_bytes
            return
        if store.current_path.exists():
            self.terrain_local_state = "invalid"
            return

        candidates: list[tuple[str, Path]] = []
        if self.source_test_mode:
            override = os.environ.get("BOMANA_TERRAIN_DIR", "").strip()
            if override:
                candidates.append(("source", Path(override).expanduser()))
            candidates.append(("source", Path.home() / ".bomana" / "terrain-v1"))
        else:
            candidates.extend(
                (
                    (
                        "legacy",
                        _app_runtime_dir(self.base, self.channel)
                        / "bomana"
                        / "data"
                        / "terrain-v1",
                    ),
                    ("legacy", Path.home() / ".bomana" / "terrain-v1"),
                )
            )
        for state, pack_dir in candidates:
            map_count, total_size = _terrain_index_summary(pack_dir)
            if map_count:
                self.terrain_local_state = state
                self.terrain_local_map_count = map_count
                self.terrain_local_total_size = total_size
                return
        self.terrain_local_state = "missing"

    def _render_terrain_status(self) -> None:
        if (
            not hasattr(self, "terrain_status_lbl")
            or not self._terrain_features_visible()
        ):
            return
        catalog_available = bool(getattr(self, "terrain_catalog_available", False))
        selected_count = int(getattr(self, "terrain_catalog_selected_count", 0) or 0)
        catalog_map_count = int(getattr(self, "terrain_catalog_map_count", 0) or 0)
        use_remote = bool(
            catalog_available
            or (self.terrain_update_available and self.terrain_remote_map_count)
        )
        map_count = (
            selected_count
            if catalog_available
            else (self.terrain_remote_map_count if use_remote else self.terrain_local_map_count)
        )
        total_size = (
            self.terrain_selection_size_bytes
            if catalog_available
            else (self.terrain_remote_total_size if use_remote else self.terrain_local_total_size)
        )
        badge, detail, level = _terrain_status_copy(
            "Enhanced" if _DISTRIBUTION_BUILD_METADATA.isolated_test else self.channel,
            local_state=self.terrain_local_state,
            local_revision=self.terrain_local_revision,
            remote_revision=self.terrain_remote_revision,
            map_count=map_count,
            total_size_bytes=total_size,
            update_available=self.terrain_update_available,
            download_size=self.terrain_download_size,
            check_warning=self.terrain_check_warning,
            check_blocking=self.terrain_check_blocking,
            running=self.running,
            current_task=self.current_task,
        )
        if catalog_available:
            if selected_count == 0:
                badge = "未选择"
                detail = (
                    f"目录共 {catalog_map_count} 张地图；不会自动下载。"
                    "点击“选择地图”后再维护所需数据。"
                )
                level = "warning"
            else:
                selection = (
                    f"已选 {selected_count}/{catalog_map_count} 张"
                    f" · {_format_size_text(self.terrain_selection_size_bytes)}"
                )
                detail = f"{selection} · {detail}" if detail else selection
        colors = {
            "success": _THEME["GREEN"],
            "warning": _THEME["YELLOW"],
            "error": _THEME["RED"],
            "info": _THEME["BLUE"],
            "muted": _THEME["TEXT_MUTED"],
        }
        self.terrain_status_lbl.config(text=badge, fg=colors.get(level, _THEME["TEXT_DIM"]))
        self.terrain_detail_lbl.config(text=detail)
        if hasattr(self, "terrain_select_btn"):
            self.terrain_select_btn.config(
                text=(
                    f"选择地图 ({selected_count}/{catalog_map_count})"
                    if catalog_available
                    else "选择地图"
                ),
                state=(
                    "normal"
                    if catalog_available
                    and (not self.running or self.current_task == "download")
                    else "disabled"
                ),
            )

    def _on_select_terrain_maps(self) -> None:
        if self.running and self.current_task != "download":
            return
        if self._terrain_map_dialog is not None:
            with contextlib.suppress(tk.TclError):
                self._terrain_map_dialog.lift()
                self._terrain_map_dialog.focus_set()
                return
        envelope = dict(self.latest_terrain_manifest or {})
        document = _terrain_catalog_document(envelope)
        if document is None:
            messagebox.showinfo(
                DISPLAY_NAME,
                "请先完成一次更新检查，取得已签名的地图目录。",
                parent=self.root,
            )
            return
        try:
            catalog = _strict_signed_terrain_catalog(document)
        except Exception as exc:
            messagebox.showwarning(
                DISPLAY_NAME,
                f"地图目录校验失败：{exc}",
                parent=self.root,
            )
            return

        store = _terrain_store_for_base(self.base)
        map_ids = tuple(terrain_map.map_id for terrain_map in catalog.maps)
        catalog_display_names = {
            terrain_map.map_id: terrain_map.display_name_zh
            for terrain_map in catalog.maps
        }
        categories = _launcher_terrain_presentation.group_terrain_maps(map_ids)
        selection_initialized = store.has_map_selection(catalog)
        selected_state = set(
            _launcher_terrain_presentation.initial_terrain_map_selection(
                categories,
                store.selected_map_ids(catalog),
                selection_initialized=selection_initialized,
            )
        )
        recommended_category_ids = (
            set(
                _launcher_terrain_presentation.recommended_terrain_category_ids(categories)
            )
            if not selection_initialized
            else set()
        )
        for progress in store.catalog_map_progress(catalog, selected_state):
            self.terrain_map_progress[progress.map_id] = progress
        read_only = bool(self.running)
        dialog = tk.Toplevel(self.root)
        self._terrain_map_dialog = dialog
        dialog.title(f"{DISPLAY_NAME} · 选择地图")
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.configure(bg=_THEME["BG"])
        _apply_window_icon(dialog)
        _place_child_dialog(
            dialog,
            self.root,
            width=self._px(760),
            height=self._px(720),
            min_width=self._px(680),
            min_height=self._px(560),
        )

        def close_dialog() -> None:
            self._terrain_map_row_renderers.clear()
            self._terrain_map_dialog = None
            with contextlib.suppress(tk.TclError):
                dialog.grab_release()
                dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)

        tk.Label(
            dialog,
            text=(
                "下载进行中；每张地图整行的背景就是实时进度。"
                if read_only
                else (
                    "首次使用（全真/空战推荐）优先选择“空战地图”和“空地联合”；"
                    "推荐只会预选，点击“保存”后才会维护下载。"
                    if not selection_initialized
                    else "点击分类可整组选中；地图整行背景显示该地图的下载进度。"
                )
            ),
            font=self._font(10),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["BG"],
            anchor="w",
        ).pack(fill="x", padx=self._px(14), pady=(self._px(14), self._px(8)))

        list_frame = tk.Frame(dialog, bg=_THEME["CARD"])
        list_frame.pack(fill="both", expand=True, padx=self._px(14))
        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        map_canvas = tk.Canvas(
            list_frame,
            yscrollcommand=scrollbar.set,
            bg=_THEME["CARD"],
            bd=0,
            highlightthickness=1,
            highlightbackground=_THEME["BORDER"],
        )
        rows_frame = tk.Frame(map_canvas, bg=_THEME["CARD"])
        rows_window = map_canvas.create_window((0, 0), window=rows_frame, anchor="nw")
        scrollbar.config(command=map_canvas.yview)
        scrollbar.pack(side="right", fill="y")
        map_canvas.pack(side="left", fill="both", expand=True)

        def resize_rows(event: tk.Event) -> None:
            map_canvas.itemconfigure(rows_window, width=max(1, int(event.width)))

        def resize_scroll_region(_event: object = None) -> None:
            map_canvas.configure(scrollregion=map_canvas.bbox("all"))

        def scroll_rows(event: tk.Event) -> str:
            delta = int(getattr(event, "delta", 0) or 0)
            if delta:
                map_canvas.yview_scroll(-1 if delta > 0 else 1, "units")
            return "break"

        map_canvas.bind("<Configure>", resize_rows)
        rows_frame.bind("<Configure>", resize_scroll_region)
        dialog.bind("<MouseWheel>", scroll_rows)

        summary = tk.Label(
            dialog,
            text="",
            font=self._font(9),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["BG"],
            anchor="w",
        )
        summary.pack(fill="x", padx=self._px(14), pady=(self._px(8), self._px(4)))

        category_buttons: Dict[str, tk.Button] = {}

        def update_summary() -> None:
            projection = _terrain_catalog_selection_projection(
                catalog,
                tuple(selected_state),
            )
            summary.config(
                text=(
                    f"已选 {projection['selected_count']}/{projection['map_count']} 张 · "
                    f"所选完整数据 {_format_size_text(projection['selected_size_bytes'])}"
                )
            )

        def refresh_selection() -> None:
            projected = _launcher_terrain_presentation.project_category_selection(
                categories,
                selected_state,
            )
            marker_by_state = {"all": "[x]", "partial": "[-]", "none": "[ ]"}
            for category in projected:
                button = category_buttons[category.category_id]
                button.config(
                    text=(
                        f"{marker_by_state[category.selection_state]} {category.label}"
                        f"{' · 首次推荐' if category.category_id in recommended_category_ids else ''}  "
                        f"({category.selected_count}/{len(category.map_ids)})"
                    )
                )
            update_summary()
            self._refresh_terrain_map_rows()

        def toggle_map(map_id: str) -> None:
            if read_only:
                return
            if map_id in selected_state:
                selected_state.remove(map_id)
            else:
                selected_state.add(map_id)
            refresh_selection()

        def toggle_category(category_id: str) -> None:
            if read_only:
                return
            category = next(
                value for value in categories if value.category_id == category_id
            )
            chosen = _launcher_terrain_presentation.toggle_category_selection(
                selected_state,
                category.map_ids,
            )
            selected_state.clear()
            selected_state.update(chosen)
            refresh_selection()

        row_height = self._px(34)
        for category in categories:
            category_button = tk.Button(
                rows_frame,
                text="",
                command=lambda category_id=category.category_id: toggle_category(category_id),
                cursor="arrow" if read_only else "hand2",
                font=self._font(10, "bold"),
                anchor="w",
                padx=self._px(9),
                pady=self._px(5),
                state="disabled" if read_only else "normal",
            )
            category_button.pack(
                fill="x",
                padx=self._px(5),
                pady=(self._px(8), self._px(3)),
            )
            self._style_action_button(category_button, "secondary")
            category_buttons[category.category_id] = category_button

            for map_id in category.map_ids:
                row = tk.Canvas(
                    rows_frame,
                    height=row_height,
                    bg=_THEME["CARD"],
                    bd=0,
                    highlightthickness=0,
                    cursor="arrow" if read_only else "hand2",
                )
                row.pack(fill="x", padx=self._px(5), pady=(0, self._px(1)))
                progress_bar = row.create_rectangle(
                    0,
                    0,
                    0,
                    row_height,
                    fill="#285378",
                    outline="",
                )
                label_item = row.create_text(
                    self._px(10),
                    row_height // 2,
                    anchor="w",
                    fill=_THEME["TEXT"],
                    font=self._font(10),
                )
                status_item = row.create_text(
                    self._px(10),
                    row_height // 2,
                    anchor="e",
                    fill=_THEME["TEXT_DIM"],
                    font=self._font(9),
                )

                def make_renderer(
                    map_id_value: str,
                    row_value: tk.Canvas,
                    progress_item: int,
                    label_value: int,
                    status_value: int,
                ) -> Callable[[], None]:
                    def render() -> None:
                        selected = map_id_value in selected_state
                        projection = _terrain_map_row_projection(
                            self.terrain_map_progress.get(map_id_value),
                            selected=selected,
                        )
                        width = max(1, int(row_value.winfo_width()))
                        fill_width = int(width * float(projection["progress_fraction"]))
                        row_value.configure(
                            bg=_THEME["CARD_SOFT"] if selected else _THEME["CARD"]
                        )
                        row_value.coords(
                            progress_item,
                            0,
                            0,
                            fill_width,
                            row_height,
                        )
                        row_value.coords(status_value, width - self._px(10), row_height // 2)
                        row_value.itemconfigure(
                            label_value,
                            text=(
                                f"{projection['selection_marker']} "
                                f"{_launcher_terrain_presentation.terrain_map_localized_display_name(map_id_value, catalog_display_names.get(map_id_value, ''))}"
                            ),
                        )
                        row_value.itemconfigure(
                            status_value,
                            text=str(projection["status_text"]),
                        )

                    return render

                renderer = make_renderer(
                    map_id,
                    row,
                    progress_bar,
                    label_item,
                    status_item,
                )
                self._terrain_map_row_renderers[map_id] = renderer
                row.bind("<Configure>", lambda _event, render=renderer: render())
                row.bind(
                    "<Button-1>",
                    lambda _event, map_id_value=map_id: toggle_map(map_id_value),
                )

        def save_selection() -> None:
            chosen = tuple(sorted(selected_state))
            store.set_map_selection(catalog, chosen)
            projection = _terrain_catalog_selection_projection(catalog, chosen)
            self.terrain_catalog_selected_map_ids = tuple(projection["selected_map_ids"])
            self.terrain_catalog_selected_count = int(projection["selected_count"])
            self.terrain_selection_size_bytes = int(projection["selected_size_bytes"])
            close_dialog()
            self._render_terrain_status()
            self._begin_check(automatic=True)

        refresh_selection()
        button_row = tk.Frame(dialog, bg=_THEME["BG"])
        button_row.pack(fill="x", padx=self._px(14), pady=(self._px(6), self._px(14)))
        actions = (
            (("关闭", close_dialog),)
            if read_only
            else (
                ("全选", lambda: (selected_state.update(map_ids), refresh_selection())),
                ("清空", lambda: (selected_state.clear(), refresh_selection())),
                ("保存", save_selection),
            )
        )
        for text, command in actions:
            button = tk.Button(
                button_row,
                text=text,
                command=command,
                cursor="hand2",
                font=self._font(9, "bold"),
                padx=self._px(8),
                pady=self._px(4),
            )
            button.pack(side="left", fill="x", expand=True, padx=self._px(3))
            self._style_action_button(button, "primary" if text == "保存" else "secondary")
        dialog.grab_set()
        map_canvas.focus_set()

    def _super_bomb_access_allowed(self) -> bool:
        """Return the one entitlement result used by all Super Bomb UI gates."""

        if self.source_test_mode:
            return True
        decision = getattr(self, "subscription_decision", None)
        return bool(decision is not None and decision.allowed)

    def _super_bomb_features_visible(self) -> bool:
        return (
            _normalize_channel(getattr(self, "channel", "")) == "Enhanced"
            and self._super_bomb_access_allowed()
        )

    def _terrain_features_visible(self) -> bool:
        return _DISTRIBUTION_BUILD_METADATA.isolated_test or self._super_bomb_features_visible()

    def _available_channel_ids(self) -> tuple[str, ...]:
        public_channels = tuple(
            channel for channel in CHANNEL_DETAILS if channel != "Enhanced"
        )
        if self._super_bomb_access_allowed():
            return ("Enhanced", *public_channels)
        return public_channels

    def _set_channel_var_silently(self, channel: str) -> None:
        if not hasattr(self, "channel_var"):
            return
        self._channel_menu_refreshing = True
        try:
            self.channel_var.set(_channel_display_name(channel))
        finally:
            self._channel_menu_refreshing = False

    def _refresh_channel_menu(self) -> bool:
        if not hasattr(self, "channel_menu"):
            return False
        available = self._available_channel_ids()
        changed = False
        if self.channel not in available:
            self.channel = PUBLIC_FALLBACK_CHANNEL
            self._set_channel_var_silently(self.channel)
            changed = True
        menu = self.channel_menu["menu"]
        menu.delete(0, "end")
        for channel in available:
            menu.add_command(
                label=CHANNEL_DISPLAY_NAMES[channel],
                command=tk._setit(
                    self.channel_var,
                    CHANNEL_DISPLAY_NAMES[channel],
                ),
            )
        return changed

    def _set_optional_card_visible(
        self,
        widget: tk.Widget,
        visible: bool,
        *,
        before: tk.Widget | None = None,
        pady: tuple[int, int] = (0, 0),
    ) -> None:
        if visible:
            if widget.winfo_manager():
                return
            options: dict[str, Any] = {
                "fill": "x",
                "padx": self._px(12),
                "pady": pady,
            }
            if before is not None:
                options["before"] = before
            widget.pack(**options)
        else:
            widget.pack_forget()

    def _refresh_feature_visibility(self) -> None:
        visible = self._super_bomb_features_visible()
        terrain_visible = self._terrain_features_visible()
        if hasattr(self, "web_card"):
            self._set_optional_card_visible(
                self.web_card,
                visible,
                before=getattr(self, "selection_summary_lbl", None),
                pady=(0, self._px(10)),
            )
        if hasattr(self, "terrain_card"):
            self._set_optional_card_visible(
                self.terrain_card,
                terrain_visible,
                before=getattr(self, "rollback_card", None),
                pady=(0, self._px(10)),
            )
        if terrain_visible:
            self._render_terrain_status()

    def _style_action_button(self, btn: tk.Button, variant: str) -> None:
        style_action_button(btn, variant, palette=_THEME, bd=1)

    def _init_window_scale_context(self) -> None:
        self.dpi_scale = 1.0
        self.scale = 1.0
        try:
            self.root.update_idletasks()
            internal_id = self.root.winfo_id()
            hwnd = internal_id
            if os.name == "nt":
                try:
                    hwnd = ctypes.windll.user32.GetParent(internal_id) or int(internal_id)
                except Exception:
                    hwnd = int(internal_id)
            dpi_scale = Win32.get_dpi_scale(int(hwnd))
            self.dpi_scale = max(1.0, min(2.0, float(dpi_scale)))
        except Exception:
            self.dpi_scale = 1.0

        try:
            self.root.tk.call("tk", "scaling", float(self.dpi_scale))
        except Exception:
            pass

        fam = select_ui_font_family(self.root)
        if fam:
            self.font_family = fam
        self.root.option_add("*Font", self._font(10))
        self.root.option_add("*Menu.font", self._font(10))
        self.root.option_add("*Menubutton.font", self._font(10))

    def _fit_window_to_screen(self) -> None:
        self.root.update_idletasks()
        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        min_w = max(self._base_min_w, int(req_w * 0.9))
        min_h = max(self._base_min_h, int(req_h * 0.9))
        max_w = max(min_w, screen_w - self._px(80))
        max_h = max(min_h, screen_h - self._px(80))

        init_w = min(max(req_w, min_w), max_w)
        init_h = min(max(req_h, min_h), max_h)
        self.root.geometry(f"{int(init_w)}x{int(init_h)}")
        self.root.minsize(int(min_w), int(min_h))
        self.root.maxsize(int(max_w), int(max_h))
        self._base_min_w = int(min_w)
        self._base_min_h = int(min_h)
        self._min_w = int(min_w)
        self._min_h = int(min_h)
        self._max_w = int(max_w)
        self._max_h = int(max_h)

    def _on_window_configure(self, event: tk.Event) -> None:
        if event.widget is not self.root:
            return
        self._refresh_wraplengths()
        self._schedule_layout_reflow()

    def _refresh_wraplengths(self) -> None:
        try:
            win_w = self.root.winfo_width()
            if win_w <= 1:
                win_w = max(self._base_min_w, self.root.winfo_reqwidth())
            left_w = (
                self.controls_card.winfo_width()
                if hasattr(self, "controls_card")
                else int(win_w * 0.4)
            )
            if left_w <= 1:
                left_w = max(self._px(290), int(win_w * 0.4))
            right_w = (
                self.status_card.winfo_width()
                if hasattr(self, "status_card")
                else int(win_w * 0.6)
            )
            if right_w <= 1:
                right_w = max(self._px(360), int(win_w * 0.6))
            left_wrap = max(self._px(190), left_w - self._px(48))
            content_w = max(self._px(280), right_w - self._px(34))
            if hasattr(self, "selection_summary_lbl"):
                self.selection_summary_lbl.config(wraplength=left_wrap)
            if hasattr(self, "rollback_status_lbl"):
                self.rollback_status_lbl.config(wraplength=left_wrap)
            if hasattr(self, "terrain_detail_lbl"):
                self.terrain_detail_lbl.config(wraplength=left_wrap)
            for name in (
                "web_dashboard_autostart_chk",
                "web_dashboard_auto_open_chk",
                "web_dashboard_lan_enabled_chk",
            ):
                widget = getattr(self, name, None)
                if widget is not None:
                    widget.config(wraplength=left_wrap)
            if hasattr(self, "detail_lbl"):
                self.detail_lbl.config(wraplength=content_w)
            if hasattr(self, "hint_lbl"):
                self.hint_lbl.config(wraplength=content_w)
            self.progress_width = max(self._px(320), content_w)
            self.progress_height = self._px(12)
            if hasattr(self, "progress_canvas"):
                self.progress_canvas.config(width=self.progress_width, height=self.progress_height)
                if self.indeterminate:
                    block = max(self._px(70), int(self.progress_width * 0.2))
                    x = (self.anim_phase * self._px(14)) % (self.progress_width + block) - block
                    x0 = max(0, x)
                    x1 = min(self.progress_width, x + block)
                    self.progress_canvas.coords(self.progress_bar, x0, 0, x1, self.progress_height)
                else:
                    width = int(self.progress_width * self.progress_value)
                    self.progress_canvas.coords(
                        self.progress_bar, 0, 0, width, self.progress_height
                    )
        except Exception:
            pass

    def _schedule_layout_reflow(self) -> None:
        if self._layout_after_id:
            try:
                self.root.after_cancel(self._layout_after_id)
            except Exception:
                pass
        self._layout_after_id = self.root.after(80, self._reflow_window_layout)

    def _reflow_window_layout(self) -> None:
        self._layout_after_id = None
        try:
            self.root.update_idletasks()
            req_h = self.root.winfo_reqheight() + self._px(6)
            target_min_h = max(self._base_min_h, min(req_h, self._max_h))
            if target_min_h != self._min_h:
                self._min_h = int(target_min_h)
                self.root.minsize(self._min_w, self._min_h)

            cur_w = self.root.winfo_width()
            cur_h = self.root.winfo_height()
            if cur_h < self._min_h:
                x = self.root.winfo_x()
                y = self.root.winfo_y()
                grow_h = min(self._min_h, self._max_h)
                self.root.geometry(f"{cur_w}x{grow_h}+{x}+{y}")
        except Exception:
            pass

    def _build_ui(self) -> None:
        shell = tk.Frame(
            self.root,
            bg=_THEME["SEPARATOR"],
            bd=0,
            highlightthickness=0,
        )
        shell.pack(fill="both", expand=True, padx=self._px(16), pady=self._px(16))

        top = tk.Frame(shell, bg=_THEME["BG"])
        top.pack(fill="both", expand=True, padx=self._px(1), pady=self._px(1))

        brand_strip = tk.Frame(top, bg=_THEME["CARD_SOFT"], height=self._px(4))
        brand_strip.pack(fill="x")

        title_row = tk.Frame(top, bg=_THEME["BG"])
        title_row.pack(fill="x", padx=self._px(18), pady=(self._px(14), self._px(10)))

        title_stack = tk.Frame(title_row, bg=_THEME["BG"])
        title_stack.pack(side="left", fill="x", expand=True)

        self.eyebrow_lbl = tk.Label(
            title_stack,
            text="BOMANA DESKTOP + WEB",
            font=self._font(8, "bold"),
            fg=_THEME["BLUE"],
            bg=_THEME["BG"],
            anchor="w",
        )
        self.eyebrow_lbl.pack(anchor="w", pady=(0, self._px(2)))

        self.title_lbl = tk.Label(
            title_stack,
            text=DISPLAY_NAME,
            font=self._font(20, "bold"),
            fg=_THEME["TEXT"],
            bg=_THEME["BG"],
            anchor="w",
        )
        self.title_lbl.pack(anchor="w")

        self.meta_lbl = tk.Label(
            title_stack,
            text=(
                f"Launcher {LAUNCHER_VERSION}  ·  App {MIN_SUPPORTED_APP_VERSION}+  ·  普通权限运行"
            ),
            font=self._font(10),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["BG"],
            anchor="w",
        )
        self.meta_lbl.pack(anchor="w", pady=(self._px(3), 0))

        self.details_btn = tk.Button(
            title_row,
            text="关于 / 支持作者",
            width=14,
            command=self._open_details,
            cursor="hand2",
            font=self._font(10),
            padx=self._px(8),
            pady=self._px(4),
        )
        self.details_btn.pack(side="right", padx=(self._px(8), 0))
        self._style_action_button(self.details_btn, "secondary")

        self.site_btn = tk.Button(
            title_row,
            text="官网预览",
            width=10,
            command=self._open_official_site,
            cursor="hand2",
            font=self._font(10),
            padx=self._px(8),
            pady=self._px(4),
        )
        self.site_btn.pack(side="right", padx=(self._px(8), 0))
        self._style_action_button(self.site_btn, "primary")

        self.sub_lbl = tk.Label(
            top,
            text=self._subline_text(),
            font=self._font(10),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["BG"],
            anchor="w",
        )
        self.sub_lbl.pack(fill="x", padx=self._px(18), pady=(0, self._px(12)))

        self.content_row = tk.Frame(top, bg=_THEME["BG"])
        self.content_row.pack(
            fill="both",
            expand=True,
            padx=self._px(18),
            pady=(0, self._px(12)),
        )
        self.content_row.grid_columnconfigure(
            0,
            weight=4,
            minsize=self._px(290),
        )
        self.content_row.grid_columnconfigure(
            1,
            weight=6,
            minsize=self._px(360),
        )
        self.content_row.grid_rowconfigure(0, weight=1)

        self.controls_card = tk.Frame(
            self.content_row,
            bg=_THEME["CARD_ALT"],
            highlightthickness=1,
            highlightbackground=_THEME["BORDER"],
        )
        self.controls_card.grid(row=0, column=0, sticky="nsew", padx=(0, self._px(12)))

        controls_head = tk.Frame(self.controls_card, bg=_THEME["CARD_ALT"])
        controls_head.pack(fill="x", padx=self._px(12), pady=(self._px(12), self._px(8)))
        tk.Label(
            controls_head,
            text="启动与版本",
            font=self._font(10, "bold"),
            fg=_THEME["TEXT"],
            bg=_THEME["CARD_ALT"],
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            controls_head,
            text="选择应用版本与启动选项",
            font=self._font(8),
            fg=_THEME["TEXT_MUTED"],
            bg=_THEME["CARD_ALT"],
            anchor="w",
        ).pack(anchor="w", pady=(self._px(2), 0))

        picker_row = tk.Frame(self.controls_card, bg=_THEME["CARD_ALT"])
        picker_row.pack(fill="x", padx=self._px(12), pady=(0, self._px(10)))
        picker_row.grid_columnconfigure(0, weight=2)
        picker_row.grid_columnconfigure(1, weight=3)

        channel_cluster = tk.Frame(picker_row, bg=_THEME["CARD_ALT"])
        channel_cluster.grid(row=0, column=0, sticky="ew", padx=(0, self._px(5)))
        tk.Label(
            channel_cluster,
            text="通道",
            font=self._font(9, "bold"),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["CARD_ALT"],
        ).pack(anchor="w")

        self.channel_menu = tk.OptionMenu(
            channel_cluster,
            self.channel_var,
            *(
                CHANNEL_DISPLAY_NAMES[channel]
                for channel in self._available_channel_ids()
            ),
        )
        self.channel_menu.config(
            bg=_THEME["CARD"],
            fg=_THEME["TEXT"],
            activebackground=_THEME["BORDER"],
            activeforeground=_THEME["TEXT"],
            highlightthickness=1,
            highlightbackground=_THEME["BORDER"],
            bd=0,
            width=18,
            anchor="w",
            cursor="hand2",
            font=self._font(10),
        )
        self.channel_menu["menu"].config(
            bg=_THEME["CARD"],
            fg=_THEME["TEXT"],
            activebackground=_THEME["BORDER"],
            activeforeground=_THEME["TEXT"],
            bd=0,
            font=self._font(10),
        )
        self.channel_menu.pack(fill="x", anchor="w", pady=(self._px(5), 0))

        source_cluster = tk.Frame(picker_row, bg=_THEME["CARD_ALT"])
        source_cluster.grid(row=0, column=1, sticky="ew", padx=(self._px(5), 0))
        tk.Label(
            source_cluster,
            text="来源",
            font=self._font(9, "bold"),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["CARD_ALT"],
        ).pack(anchor="w")

        source_choices = [
            label
            for mode, label in DOWNLOAD_SOURCE_CHOICES
            if _DISTRIBUTION_BUILD_METADATA.github_fallback_allowed
            or mode == DOWNLOAD_SOURCE_MODE_PRIMARY
        ]
        self.download_source_menu = tk.OptionMenu(
            source_cluster,
            self.download_source_var,
            source_choices[0],
            *source_choices[1:],
            command=self._on_download_source_changed,
        )
        self.download_source_menu.config(
            bg=_THEME["CARD"],
            fg=_THEME["TEXT"],
            activebackground=_THEME["BORDER"],
            activeforeground=_THEME["TEXT"],
            highlightthickness=1,
            highlightbackground=_THEME["BORDER"],
            bd=0,
            width=13,
            anchor="w",
            cursor="hand2",
            font=self._font(9),
        )
        self.download_source_menu["menu"].config(
            bg=_THEME["CARD"],
            fg=_THEME["TEXT"],
            activebackground=_THEME["BORDER"],
            activeforeground=_THEME["TEXT"],
            bd=0,
            font=self._font(9),
        )
        self.download_source_menu.pack(fill="x", anchor="w", pady=(self._px(5), 0))
        if not _DISTRIBUTION_BUILD_METADATA.github_fallback_allowed:
            self.download_source_menu.config(state="disabled", cursor="arrow")

        self.proxy_chk = tk.Checkbutton(
            picker_row,
            text="优先使用系统代理（失败时直连重试）",
            variable=self.proxy_var,
            command=self._on_proxy_changed,
            bg=_THEME["CARD_ALT"],
            fg=_THEME["TEXT_DIM"],
            activebackground=_THEME["CARD_ALT"],
            activeforeground=_THEME["TEXT"],
            selectcolor=_THEME["CARD"],
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            font=self._font(9),
        )
        self.proxy_chk.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(self._px(8), self._px(2)),
        )

        self.subscription_card = tk.Frame(
            self.controls_card,
            bg=_THEME["CARD"],
            highlightthickness=1,
            highlightbackground=_THEME["SEPARATOR"],
        )
        self.subscription_card.pack(
            fill="x",
            padx=self._px(12),
            pady=(0, self._px(10)),
        )
        subscription_copy = tk.Frame(self.subscription_card, bg=_THEME["CARD"])
        subscription_copy.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(self._px(10), self._px(6)),
            pady=self._px(7),
        )
        tk.Label(
            subscription_copy,
            text="超级爆弹版功能预览",
            font=self._font(9, "bold"),
            fg=_THEME["TEXT"],
            bg=_THEME["CARD"],
            anchor="w",
        ).pack(fill="x")
        self.subscription_status_lbl = tk.Label(
            subscription_copy,
            text="",
            font=self._font(8),
            fg=_THEME["TEXT_MUTED"],
            bg=_THEME["CARD"],
            anchor="w",
        )
        self.subscription_status_lbl.pack(fill="x", pady=(self._px(2), 0))
        self.subscription_action_frame = tk.Frame(
            self.subscription_card,
            bg=_THEME["CARD"],
        )
        self.subscription_action_frame.pack(
            side="right",
            padx=(self._px(4), self._px(10)),
            pady=self._px(7),
        )
        self.subscription_store_btn = tk.Button(
            self.subscription_action_frame,
            text="购买 / 试用",
            command=self._open_subscription_store,
            cursor="hand2",
            font=self._font(9, "bold"),
            padx=self._px(7),
            pady=self._px(3),
        )
        self.subscription_store_btn.pack(fill="x", pady=(0, self._px(3)))
        self._style_action_button(self.subscription_store_btn, "secondary")
        self.subscription_login_btn = tk.Button(
            self.subscription_action_frame,
            text="登录 / 授权",
            command=self._begin_subscription_login,
            cursor="hand2",
            font=self._font(9, "bold"),
            padx=self._px(7),
            pady=self._px(3),
        )
        self.subscription_login_btn.pack(fill="x")
        self._style_action_button(self.subscription_login_btn, "primary")
        self._refresh_subscription_ui()

        self.web_card = tk.Frame(
            self.controls_card,
            bg=_THEME["CARD"],
            highlightthickness=1,
            highlightbackground=_THEME["SEPARATOR"],
        )
        self.web_card.pack(fill="x", padx=self._px(12), pady=(0, self._px(10)))
        tk.Label(
            self.web_card,
            text="Web 控制台 · 端口与配对由 App 管理",
            font=self._font(9, "bold"),
            fg=_THEME["TEXT"],
            bg=_THEME["CARD"],
            anchor="w",
        ).pack(fill="x", padx=self._px(10), pady=(self._px(7), self._px(4)))

        web_check_style = {
            "bg": _THEME["CARD"],
            "fg": _THEME["TEXT_DIM"],
            "activebackground": _THEME["CARD"],
            "activeforeground": _THEME["TEXT"],
            "selectcolor": _THEME["CARD_ALT"],
            "bd": 0,
            "highlightthickness": 0,
            "cursor": "hand2",
            "font": self._font(9),
            "anchor": "w",
        }
        self.web_dashboard_autostart_chk = tk.Checkbutton(
            self.web_card,
            text="随 App 启动本机 Web 服务",
            variable=self.web_dashboard_autostart_var,
            command=self._on_web_preferences_changed,
            **web_check_style,
        )
        self.web_dashboard_autostart_chk.pack(fill="x", padx=self._px(10), pady=(0, self._px(1)))
        self.web_dashboard_auto_open_chk = tk.Checkbutton(
            self.web_card,
            text="启动成功后自动打开本机页面",
            variable=self.web_dashboard_auto_open_var,
            command=self._on_web_preferences_changed,
            **web_check_style,
        )
        self.web_dashboard_auto_open_chk.pack(fill="x", padx=self._px(10), pady=(0, self._px(1)))
        self.web_dashboard_lan_enabled_chk = tk.Checkbutton(
            self.web_card,
            text="启动时开启局域网访问与控制（自动识别专用网络）",
            variable=self.web_dashboard_lan_enabled_var,
            command=self._on_web_preferences_changed,
            **web_check_style,
        )
        self.web_dashboard_lan_enabled_chk.pack(fill="x", padx=self._px(10), pady=(0, self._px(6)))

        self.selection_summary_lbl = tk.Label(
            self.controls_card,
            text="",
            font=self._font(9),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["CARD_ALT"],
            anchor="w",
            justify="left",
            wraplength=self._px(540),
        )
        self.selection_summary_lbl.pack(
            fill="x",
            padx=self._px(12),
            pady=(self._px(2), self._px(10)),
        )

        self.terrain_card = tk.Frame(
            self.controls_card,
            bg=_THEME["CARD"],
            highlightthickness=1,
            highlightbackground=_THEME["SEPARATOR"],
        )
        self.terrain_card.pack(
            fill="x",
            padx=self._px(12),
            pady=(0, self._px(10)),
        )
        terrain_head = tk.Frame(self.terrain_card, bg=_THEME["CARD"])
        terrain_head.pack(
            fill="x",
            padx=self._px(10),
            pady=(self._px(8), self._px(2)),
        )
        tk.Label(
            terrain_head,
            text="离线地图包",
            font=self._font(10, "bold"),
            fg=_THEME["TEXT"],
            bg=_THEME["CARD"],
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        self.terrain_status_lbl = tk.Label(
            terrain_head,
            text="正在检查",
            font=self._font(9, "bold"),
            fg=_THEME["BLUE"],
            bg=_THEME["CARD"],
            anchor="e",
        )
        self.terrain_status_lbl.pack(side="right", padx=(self._px(8), 0))
        self.terrain_detail_lbl = tk.Label(
            self.terrain_card,
            text="",
            font=self._font(8),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["CARD"],
            anchor="w",
            justify="left",
            wraplength=self._px(260),
        )
        self.terrain_detail_lbl.pack(
            fill="x",
            padx=self._px(10),
            pady=(0, self._px(6)),
        )
        self.terrain_select_btn = tk.Button(
            self.terrain_card,
            text="选择地图",
            command=self._on_select_terrain_maps,
            cursor="hand2",
            font=self._font(9, "bold"),
            padx=self._px(6),
            pady=self._px(3),
        )
        self.terrain_select_btn.pack(
            fill="x",
            padx=self._px(10),
            pady=(0, self._px(9)),
        )
        self._style_action_button(self.terrain_select_btn, "secondary")

        self.rollback_card = tk.Frame(
            self.controls_card,
            bg=_THEME["CARD"],
            highlightthickness=1,
            highlightbackground=_THEME["SEPARATOR"],
        )
        self.rollback_card.pack(
            fill="x",
            padx=self._px(12),
            pady=(0, self._px(12)),
        )
        tk.Label(
            self.rollback_card,
            text="版本回退",
            font=self._font(10, "bold"),
            fg=_THEME["TEXT"],
            bg=_THEME["CARD"],
            anchor="w",
        ).pack(fill="x", padx=self._px(10), pady=(self._px(9), self._px(2)))

        self.rollback_status_lbl = tk.Label(
            self.rollback_card,
            text="",
            font=self._font(8),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["CARD"],
            anchor="w",
            justify="left",
            wraplength=self._px(210),
        )
        self.rollback_status_lbl.pack(fill="x", padx=self._px(10), pady=(0, self._px(8)))

        self.rollback_btn = tk.Button(
            self.rollback_card,
            text="无回退版本",
            width=18,
            command=self._on_rollback,
            cursor="hand2",
            font=self._font(10, "bold"),
            padx=self._px(6),
            pady=self._px(3),
        )
        self.rollback_btn.pack(
            fill="x",
            padx=self._px(10),
            pady=(0, self._px(10)),
        )
        self._style_action_button(self.rollback_btn, "secondary")

        self.channel_var.trace_add("write", self._on_channel_changed)
        self._refresh_channel_menu()
        self._refresh_feature_visibility()
        self._refresh_channel_details()
        self._refresh_download_source_details()

        self.status_card = tk.Frame(
            self.content_row,
            bg=_THEME["CARD"],
            highlightthickness=1,
            highlightbackground=_THEME["BORDER"],
        )
        self.status_card.grid(row=0, column=1, sticky="nsew")

        status_header = tk.Frame(self.status_card, bg=_THEME["CARD"])
        status_header.pack(
            fill="x", padx=(self._px(16), self._px(6)), pady=(self._px(12), self._px(6))
        )

        self.status_lbl = tk.Label(
            status_header,
            text="| 正在准备",
            font=self._font(12, "bold"),
            fg=_THEME["BLUE"],
            bg=_THEME["CARD"],
            anchor="w",
        )
        self.status_lbl.pack(side="left", fill="x", expand=True)

        self.launch_btn = tk.Button(
            status_header,
            text="启动本地应用",
            width=16,
            command=self._on_launch,
            cursor="hand2",
            font=self._font(11, "bold"),
            padx=self._px(12),
            pady=self._px(5),
        )
        self.launch_btn.pack(side="right", padx=(self._px(4), 0))
        self._style_action_button(self.launch_btn, "secondary")

        self.detail_lbl = tk.Label(
            self.status_card,
            text="",
            font=self._font(10),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["CARD"],
            anchor="w",
            justify="left",
            wraplength=self._px(520),
        )
        self.detail_lbl.pack(fill="x", padx=self._px(16))

        self.progress_canvas = tk.Canvas(
            self.status_card,
            width=self.progress_width,
            height=self.progress_height,
            bg=_THEME["CARD"],
            bd=0,
            highlightthickness=0,
        )
        self.progress_canvas.pack(padx=self._px(16), pady=(self._px(14), self._px(6)))
        self.progress_bar = self.progress_canvas.create_rectangle(
            0, 0, 0, self.progress_height, fill=_THEME["BLUE"], width=0
        )

        self.hint_lbl = tk.Label(
            self.status_card,
            text="首次使用请先安装应用包；每次更新会保留一个可验证的上一版本。",
            font=self._font(9),
            fg=_THEME["TEXT_MUTED"],
            bg=_THEME["CARD"],
            anchor="w",
            justify="left",
            wraplength=self._px(520),
        )
        self.hint_lbl.pack(fill="x", padx=self._px(16), pady=(self._px(2), self._px(10)))

        btn_shell = tk.Frame(
            top,
            bg=_THEME["CARD_ALT"],
            highlightthickness=1,
            highlightbackground=_THEME["BORDER"],
        )
        btn_shell.pack(fill="x", padx=self._px(18), pady=(0, self._px(16)))

        btn_row = tk.Frame(btn_shell, bg=_THEME["CARD_ALT"])
        btn_row.pack(fill="x", padx=self._px(12), pady=self._px(10))

        self.start_btn = tk.Button(
            btn_row,
            text="下载更新",
            width=12,
            command=self._on_start,
            cursor="hand2",
            font=self._font(10, "bold"),
            padx=self._px(6),
            pady=self._px(3),
        )
        self.start_btn.pack(side="left")
        self._style_action_button(self.start_btn, "primary")

        self.launcher_btn = tk.Button(
            btn_row,
            text="更新启动器",
            width=12,
            command=self._on_update_launcher,
            cursor="hand2",
            font=self._font(10),
            padx=self._px(6),
            pady=self._px(3),
        )
        self.launcher_btn.pack(side="left", padx=(self._px(8), 0))
        self._style_action_button(self.launcher_btn, "secondary")

        self.retry_btn = tk.Button(
            btn_row,
            text="重新检查",
            width=10,
            command=self._on_retry,
            cursor="hand2",
            font=self._font(10),
            padx=self._px(6),
            pady=self._px(3),
        )
        self.retry_btn.pack(side="left")
        self._style_action_button(self.retry_btn, "secondary")

        self.release_btn = tk.Button(
            btn_row,
            text="打开下载页",
            width=12,
            command=self._open_releases,
            cursor="hand2",
            font=self._font(10),
            padx=self._px(6),
            pady=self._px(3),
        )
        self.release_btn.pack(side="right")
        self._style_action_button(self.release_btn, "secondary")

        self.exit_btn = tk.Button(
            btn_row,
            text="退出",
            width=10,
            command=self._on_exit,
            cursor="hand2",
            font=self._font(10),
            padx=self._px(6),
            pady=self._px(3),
        )
        self.exit_btn.pack(side="right", padx=(0, self._px(8)))
        self._style_action_button(self.exit_btn, "secondary")

    def _ensure_subscription_workflow(self) -> bool:
        """Initialize subscriber access only for an explicit Enhanced path."""

        if self.source_test_mode:
            return False
        if self.subscription_workflow is not None:
            return True
        try:
            if not CHEEMSPAY_LICENSE_PUBLIC_KEYS:
                raise RuntimeError("启动器未内置 CheemsPay 订阅验签公钥")
            self.subscription_workflow = SubscriptionWorkflow(
                authority=CheemsPaySubscriptionAuthority(),
                verifier=ReceiptVerifier(),
                store=create_default_subscription_store(),
            )
        except Exception as exc:
            self.subscription_setup_error = str(exc) or "CheemsPay 订阅组件初始化失败"
            return False
        return True

    def _refresh_cached_subscription_access(self) -> SubscriptionAccessDecision:
        """Read a local receipt only while entering the Enhanced path."""

        if not self._ensure_subscription_workflow():
            return self.subscription_decision
        try:
            self.subscription_decision = self.subscription_workflow.cached_access()
        except Exception as exc:
            self.subscription_setup_error = str(exc) or "CheemsPay 订阅组件初始化失败"
            self.subscription_decision = SubscriptionAccessDecision(
                allowed=False,
                reason=SubscriptionAccessReason.MISSING_RECEIPT,
            )
        return self.subscription_decision

    def _refresh_subscription_ui(self) -> None:
        if not hasattr(self, "subscription_status_lbl"):
            return
        action_frame = getattr(self, "subscription_action_frame", None)
        if self.source_test_mode:
            self.subscription_status_lbl.config(
                text="源码测试模式；超级爆弹版功能由对应应用包提供。",
                fg=_THEME["TEXT_MUTED"],
            )
            if action_frame is not None:
                action_frame.pack_forget()
            return
        if _DISTRIBUTION_BUILD_METADATA.isolated_test:
            self.subscription_status_lbl.config(
                text="隔离测试构建；不读取或验证生产 CheemsPay 收据。",
                fg=_THEME["YELLOW"],
            )
            if action_frame is not None:
                action_frame.pack_forget()
        elif not self._super_bomb_access_allowed():
            self.subscription_status_lbl.config(
                text=(
                    "超级爆弹版提供高级弹道推演、离线地形与网页驾驶舱；"
                    "可购买/试用后点击“登录 / 授权”，再切换到 Enhanced。"
                ),
                fg=_THEME["TEXT_DIM"],
            )
            if action_frame is not None:
                if not action_frame.winfo_manager():
                    action_frame.pack(
                        side="right",
                        padx=(self._px(4), self._px(10)),
                        pady=self._px(7),
                    )
                self.subscription_store_btn.config(text="购买 / 试用")
                self.subscription_login_btn.config(text="登录 / 授权")
        else:
            self.subscription_status_lbl.config(
                text=_subscription_access_copy(self.subscription_decision),
                fg=_THEME["GREEN"],
            )
            if action_frame is not None:
                if not action_frame.winfo_manager():
                    action_frame.pack(
                        side="right",
                        padx=(self._px(4), self._px(10)),
                        pady=self._px(7),
                    )
                self.subscription_store_btn.config(text="打开商品页")
                self.subscription_login_btn.config(text="刷新授权")
        if action_frame is not None:
            action_state = "disabled" if self.running else "normal"
            self.subscription_store_btn.config(state=action_state)
            self.subscription_login_btn.config(state=action_state)
        changed = self._refresh_channel_menu()
        if changed:
            self._save_launcher_state()
            self._refresh_installed_versions()
            self._refresh_local_terrain_snapshot()
            if hasattr(self, "selection_summary_lbl"):
                self._refresh_channel_details()
        self._refresh_feature_visibility()

    def _open_subscription_store(self) -> None:
        if self.running:
            return
        try:
            opened = webbrowser.open(CHEEMSPAY_STORE_URL, new=2)
        except Exception as exc:
            messagebox.showwarning(
                DISPLAY_NAME,
                f"无法打开 CheemsPay 商品页：{exc}",
                parent=self.root,
            )
            return
        if not opened:
            messagebox.showwarning(
                DISPLAY_NAME,
                "无法打开 CheemsPay 商品页，请手动访问 pay.ruikang.wang。",
                parent=self.root,
            )

    def _begin_subscription_login(self) -> None:
        if self.running:
            return
        if not self._ensure_subscription_workflow():
            messagebox.showwarning(
                DISPLAY_NAME,
                self.subscription_setup_error or "CheemsPay 订阅组件不可用",
                parent=self.root,
            )
            return
        self.current_task = "subscription_login"
        self._set_status(
            "准备 CheemsPay 登录",
            "正在申请一次性设备授权码...",
            None,
            "info",
        )
        self._set_running(True)
        self._start_worker("subscription_login")

    def _require_subscription_access(self) -> SubscriptionAccessDecision:
        if (
            _normalize_channel(self.channel) != "Enhanced"
            or self.source_test_mode
            or _DISTRIBUTION_BUILD_METADATA.isolated_test
        ):
            return SubscriptionAccessDecision(
                allowed=True,
                reason=SubscriptionAccessReason.ALLOWED,
            )
        if self.subscription_workflow is None:
            raise RuntimeError(
                self.subscription_setup_error or "CheemsPay 订阅组件不可用"
            )
        decision = self.subscription_workflow.cached_access()
        if not decision.allowed:
            decision = self.subscription_workflow.refresh_cached_receipt()
        self.events.put(
            (
                "subscription_state",
                {"allowed": decision.allowed, "reason": decision.reason.value},
            )
        )
        if not decision.allowed:
            raise RuntimeError(_subscription_access_copy(decision))
        return decision

    def _start_worker(self, task: str) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._cancel_requested.clear()
        self._exit_after_task = False
        self._worker = threading.Thread(target=self._worker_main, args=(task,), daemon=True)
        self._worker.start()

    def _begin_check(self, automatic: bool) -> None:
        if self.running:
            return
        if self.source_test_mode:
            self.has_attempted_update = False
            self.last_check_ok = False
            self.last_check_error = ""
            self.latest_manifest = None
            self.latest_min_launcher_version = ""
            self.latest_launcher_manifest = None
            self.update_available = False
            self.app_requires_launcher_update = False
            self.latest_terrain_manifest = None
            self.terrain_remote_revision = ""
            self.terrain_remote_map_count = 0
            self.terrain_remote_total_size = 0
            self.terrain_catalog_available = False
            self.terrain_catalog_map_count = 0
            self.terrain_catalog_selected_count = 0
            self.terrain_catalog_selected_map_ids = ()
            self.terrain_selection_size_bytes = 0
            self.terrain_update_available = False
            self.terrain_check_warning = ""
            self.terrain_check_blocking = False
            self.launcher_update_available = False
            self._set_status(
                "源码测试模式",
                "当前由 launcher.pyw 直接驱动同目录源码，已禁用在线更新检查。",
                0.0,
                "info",
            )
            self._set_running(False)
            return
        self.has_attempted_update = True
        self._recheck_requested = False
        self.current_task = "check"
        self.latest_manifest = None
        self.latest_min_launcher_version = ""
        self.latest_package_size = None
        self.update_available = False
        self.app_requires_launcher_update = False
        self.latest_terrain_manifest = None
        self.terrain_remote_revision = ""
        self.terrain_remote_map_count = 0
        self.terrain_remote_total_size = 0
        self.terrain_catalog_available = False
        self.terrain_catalog_map_count = 0
        self.terrain_catalog_selected_count = 0
        self.terrain_catalog_selected_map_ids = ()
        self.terrain_selection_size_bytes = 0
        self.terrain_source_name = ""
        self.terrain_update_available = False
        self.terrain_download_size = 0
        self.terrain_reuse_size = 0
        self.terrain_check_warning = ""
        self.terrain_check_blocking = False
        self.latest_launcher_manifest = None
        self.latest_launcher_package_size = None
        self.latest_launcher_check_warning = ""
        self.launcher_update_available = False
        self.last_check_ok = False
        self.last_check_error = ""
        self.channel = _normalize_channel(self.channel_var.get()) or self.detected_channel
        self._refresh_installed_versions()
        if automatic:
            self._set_status(
                "自动检查更新",
                f"正在检查 {_channel_display_name(self.channel)}，并同步检查启动器版本...",
                None,
                "info",
            )
        else:
            self._set_status(
                "正在检查更新",
                f"正在重新检查 {_channel_display_name(self.channel)}...",
                None,
                "info",
            )
        self._set_running(True)
        self._start_worker("check")

    def _worker_main(self, task: str) -> None:
        subscriber_artifact_provider = None
        if (
            _normalize_channel(self.channel) == "Enhanced"
            and not self.source_test_mode
            and not _DISTRIBUTION_BUILD_METADATA.isolated_test
            and self.subscription_workflow is not None
        ):
            subscriber_artifact_provider = self.subscription_workflow.authorize_artifact
        service = UpdateService(
            self.base,
            self.channel,
            self.client_identity,
            download_source_mode=self.download_source_mode,
            status_cb=self._emit_status,
            terrain_map_progress_cb=self._emit_terrain_map_progress,
            cancel_cb=lambda: self._cancel_requested.is_set(),
            subscriber_artifact_provider=subscriber_artifact_provider,
        )
        if task == "subscription_login":
            try:
                if self.subscription_workflow is None:
                    raise RuntimeError("CheemsPay 订阅组件不可用")
                authorization = self.subscription_workflow.begin_device_authorization()
                self.events.put(
                    (
                        "subscription_browser",
                        {
                            "url": authorization.verification_uri_complete,
                            "user_code": authorization.user_code,
                        },
                    )
                )
                interval = authorization.interval_seconds
                while datetime.now(timezone.utc) < authorization.expires_at:
                    if self._cancel_requested.is_set():
                        raise RuntimeError("已取消 CheemsPay 登录")
                    poll = self.subscription_workflow.poll_device_authorization(
                        authorization.device_code
                    )
                    if poll.state is DeviceAuthorizationState.APPROVED:
                        decision = self.subscription_workflow.activate_authorized_session(
                            poll.access_token,
                            device_name=(socket.gethostname() or "Windows PC")[:80],
                        )
                        if not decision.allowed:
                            raise RuntimeError(_subscription_access_copy(decision))
                        self.events.put(
                            (
                                "subscription_done",
                                {
                                    "ok": True,
                                    "detail": _subscription_access_copy(decision),
                                },
                            )
                        )
                        return
                    if poll.state is DeviceAuthorizationState.DENIED:
                        raise RuntimeError("你已在 CheemsPay 页面拒绝本次设备授权")
                    if poll.state is DeviceAuthorizationState.EXPIRED:
                        raise RuntimeError("CheemsPay 设备授权码已过期，请重试")
                    if poll.state is DeviceAuthorizationState.SLOW_DOWN:
                        interval += max(5, poll.retry_after_seconds)
                    self._emit_status(
                        "等待 CheemsPay 授权",
                        f"请在浏览器确认设备码 {authorization.user_code}",
                        None,
                        "info",
                    )
                    deadline = time.monotonic() + interval
                    while time.monotonic() < deadline:
                        if self._cancel_requested.is_set():
                            raise RuntimeError("已取消 CheemsPay 登录")
                        time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
                raise RuntimeError("CheemsPay 设备授权码已过期，请重试")
            except Exception as exc:
                _log(self.base, f"CheemsPay 订阅登录失败：{exc}")
                self.events.put(
                    (
                        "subscription_done",
                        {"ok": False, "detail": str(exc) or "CheemsPay 登录失败"},
                    )
                )
            return
        if task == "check":
            try:
                self._require_subscription_access()
                info = service.check()
                self.events.put(("check_done", {"ok": True, **info}))
            except Exception as e:
                msg = _friendly_error_text(e, self.channel)
                _log(self.base, f"更新检查失败：{e}")
                self.events.put(("check_done", {"ok": False, "error": msg}))
            return
        if task == "launcher_download":
            launcher_version = LAUNCHER_VERSION
            update_ok = False
            update_source = ""
            update_error = ""
            manifest = dict(self.latest_launcher_manifest or {})
            try:
                if not manifest:
                    raise RuntimeError("请先完成启动器更新检查")
                launcher_version, update_source = service.download_launcher_update(manifest)
                update_ok = True
            except Exception as e:
                update_error = _friendly_error_text(e, self.channel)
                _log(self.base, f"下载启动器更新失败：{e}")

            _report_primary_event(
                self.base,
                self.client_identity,
                "launcher_update_result",
                self.channel,
                self.local_version,
                extra={
                    "local_version": LAUNCHER_VERSION,
                    "update_ok": update_ok,
                    "update_source": update_source,
                    "update_error": update_error,
                },
            )

            self.events.put(
                (
                    "launcher_done",
                    {
                        "update_ok": update_ok,
                        "final_version": launcher_version,
                        "status": ("启动器更新已准备好" if update_ok else "启动器更新失败"),
                        "detail": (
                            "已准备好下载并接管新版启动器；当前窗口即将关闭，随后会自动替换当前 exe 并重启。"
                            if update_ok
                            else update_error
                        ),
                        "level": ("success" if update_ok else "warning"),
                    },
                )
            )
            return
        if task == "rollback":
            final_version = install_txn.read_local_app_version(
                _app_runtime_dir(self.base, self.channel)
            )
            preserved_version = install_txn.read_local_app_version(
                _previous_app_dir(self.base, self.channel)
            )
            update_ok = False
            detail = ""
            try:
                final_version, preserved_version = install_txn.rollback_to_previous_app(
                    self.base,
                    status_cb=self._emit_status,
                    channel=self.channel,
                )
                update_ok = True
                detail = f"已回退到 v{final_version}。当前保留的上一版本为 v{preserved_version}。"
            except Exception as e:
                detail = str(e) or "回退失败"
                _log(self.base, f"回退上一版本失败：{e}")

            self.events.put(
                (
                    "rollback_done",
                    {
                        "update_ok": update_ok,
                        "final_version": final_version,
                        "status": ("回退完成" if update_ok else "回退失败"),
                        "detail": detail,
                        "level": ("success" if update_ok else "warning"),
                    },
                )
            )
            return
        if task == "import_zip":
            final_version = install_txn.read_local_app_version(
                _app_runtime_dir(self.base, self.channel)
            )
            update_ok = False
            update_error = ""
            package_path = str(getattr(self, "pending_import_zip_path", "")).strip()
            try:
                if not package_path:
                    raise RuntimeError("未选择 ZIP 包")
                zip_file = Path(package_path)
                if not zip_file.exists():
                    raise RuntimeError("ZIP 包不存在")
                self._emit_status("开始安装", f"正在导入本地包：{zip_file.name}", 0.2, "info")
                install_txn.install_zip_package_from_file(
                    self.base,
                    zip_file,
                    expected_sha256="",
                    entrypoint=DEFAULT_ENTRYPOINT,
                    status_cb=self._emit_status,
                    cancel_cb=lambda: self._cancel_requested.is_set(),
                    channel=self.channel,
                )
                final_version = install_txn.read_local_app_version(
                    _app_runtime_dir(self.base, self.channel)
                )
                update_ok = True
            except Exception as e:
                update_error = str(e)
                _log(self.base, f"导入本地 ZIP 失败：{e}")

            if update_ok:
                self.events.put(
                    (
                        "download_done",
                        {
                            "update_ok": True,
                            "final_version": final_version,
                            "warning": "",
                            "status": "安装完成",
                            "detail": (
                                f"已导入本地应用包，当前版本 v{final_version}"
                                + (
                                    f"；已保留上一版本 v{install_txn.read_local_app_version(_previous_app_dir(self.base, self.channel))}"
                                    if _is_previous_app_ready(self.base, self.channel)
                                    else ""
                                )
                            ),
                            "level": "success",
                        },
                    )
                )
            else:
                self.events.put(
                    (
                        "download_done",
                        {
                            "update_ok": False,
                            "final_version": final_version,
                            "warning": "",
                            "status": "导入失败",
                            "detail": (
                                _friendly_error_text(RuntimeError(update_error), self.channel)
                                if update_error
                                else "导入失败"
                            ),
                            "level": "warning",
                        },
                    )
                )
            return

        final_version = install_txn.read_local_app_version(
            _app_runtime_dir(self.base, self.channel)
        )
        update_ok = False
        update_source = ""
        update_error = ""
        whats_new = ""
        whats_new_warning = ""
        local_ready = _is_local_app_ready(self.base, self.channel)
        manifest = dict(self.latest_manifest or {})
        terrain_manifest = dict(self.latest_terrain_manifest or {})
        app_update_needed = bool(self.update_available)
        terrain_update_needed = bool(self.terrain_update_available)
        terrain_result: Optional[
            _launcher_terrain_store.TerrainSyncResult
            | _launcher_terrain_store.TerrainCatalogSyncResult
        ] = None
        try:
            self._require_subscription_access()
            if not (app_update_needed or terrain_update_needed):
                raise RuntimeError("当前没有需要下载的更新")
            update_sources: list[str] = []
            if terrain_update_needed:
                if not terrain_manifest:
                    raise RuntimeError("缺少已验证的地形更新清单")
                terrain_result = service.download_terrain_update(terrain_manifest)
                if getattr(terrain_result, "status", "") in {
                    "paused_app_host",
                    "paused_insufficient_disk",
                }:
                    raise RuntimeError(str(getattr(terrain_result, "message", "地形维护已暂停")))
                terrain_source = (
                    "、".join(terrain_result.source_names)
                    or str(terrain_manifest.get("source_name", "本地复用"))
                )
                update_sources.append(f"地形：{terrain_source}")
            if app_update_needed:
                if not manifest:
                    raise RuntimeError("请先完成应用更新检查")
                final_version, app_source = service.download_app_update(manifest)
                update_sources.append(f"应用：{app_source}")
                try:
                    whats_new = service.fetch_whats_new(manifest)
                except Exception as exc:
                    whats_new_warning = f"更新日志获取失败：{exc}"
                    _log(self.base, whats_new_warning)
            update_source = "；".join(update_sources)
            update_ok = True
            local_ready = _is_local_app_ready(self.base, self.channel)
        except Exception as e:
            update_error = _friendly_error_text(e, self.channel)
            _log(self.base, f"下载更新失败：{e}")

        _report_primary_event(
            self.base,
            self.client_identity,
            "update_result",
            self.channel,
            final_version,
            extra={
                "update_ok": update_ok,
                "update_source": update_source,
                "update_error": update_error,
                "terrain_revision": (
                    terrain_result.revision if terrain_result is not None else ""
                ),
                "terrain_downloaded_bytes": (
                    terrain_result.downloaded_bytes if terrain_result is not None else 0
                ),
            },
        )

        self._save_launcher_state(
            {
                "display_name": DISPLAY_NAME,
                "last_check_utc": _now_utc_iso(),
                "app_version": final_version,
                "update_ok": update_ok,
                "update_source": update_source,
                "update_error": update_error,
                "terrain_revision": (
                    terrain_result.revision if terrain_result is not None else ""
                ),
                "device_id": self.client_identity.get("device_id", ""),
                "install_id": self.client_identity.get("install_id", ""),
            }
        )

        if update_ok:
            completed_lines: list[str] = []
            if app_update_needed:
                completed_lines.append(f"应用已更新到 v{final_version}。")
            if terrain_result is not None:
                if bool(getattr(terrain_result, "already_current", False)) or (
                    getattr(terrain_result, "status", "") == "already_current"
                ):
                    completed_lines.append("地形数据经校验已是最新，未发生下载。")
                else:
                    completed_lines.append(
                        (
                            f"地形数据已切换到 {terrain_result.revision[:12]}，"
                            f"下载 {_format_size_text(terrain_result.downloaded_bytes)}，"
                            f"复用 {terrain_result.reused_objects} 个未变化对象。"
                        )
                    )
            completed_lines.append(f"安装位置：{self.install_dir}")
            if _normalize_channel(self.channel) == "Enhanced":
                terrain_store = _terrain_store_for_base(self.base)
                terrain_dir = (
                    terrain_store.current_catalog_pack_dir()
                    or terrain_store.current_pack_dir()
                )
                if terrain_dir is not None:
                    completed_lines.append(f"地形位置：{terrain_dir}")
            if app_update_needed and _is_previous_app_ready(self.base, self.channel):
                completed_lines.append(
                    (
                        f"已保留上一版本 "
                        f"v{install_txn.read_local_app_version(_previous_app_dir(self.base, self.channel))}，"
                        "可随时回退。"
                    )
                )
            self.events.put(
                (
                    "download_done",
                    {
                        "update_ok": True,
                        "final_version": final_version,
                        "warning": "",
                        "whats_new": whats_new,
                        "whats_new_warning": whats_new_warning,
                        "source_name": update_source,
                        "terrain_revision": (
                            terrain_result.revision if terrain_result is not None else ""
                        ),
                        "status": "更新完成",
                        "detail": "\n".join(completed_lines),
                        "level": "success",
                    },
                )
            )
        else:
            if local_ready:
                detail = f"{update_error}\n可点击“启动应用”使用本地版本 v{final_version}。"
                level = "warning"
                status = "更新失败"
            else:
                detail = update_error or "当前没有本地可用版本，请先联网完成首次下载。"
                level = "error"
                status = "无法启动"
            self.events.put(
                (
                    "download_done",
                    {
                        "update_ok": False,
                        "final_version": final_version,
                        "warning": detail,
                        "status": status,
                        "detail": detail,
                        "level": level,
                    },
                )
            )

    def _emit_status(self, title: str, detail: str, progress: Optional[float], level: str) -> None:
        self.events.put(
            (
                "status",
                {
                    "title": title,
                    "detail": detail,
                    "progress": progress,
                    "level": level,
                },
            )
        )

    def _emit_terrain_map_progress(
        self,
        snapshot: tuple[_launcher_terrain_store.TerrainMapProgress, ...],
    ) -> None:
        self.events.put(("terrain_map_progress", {"items": snapshot}))

    def _refresh_terrain_map_rows(self) -> None:
        for render in tuple(self._terrain_map_row_renderers.values()):
            with contextlib.suppress(tk.TclError):
                render()

    def _poll_events(self) -> None:
        try:
            while True:
                typ, payload = self.events.get_nowait()
                if typ == "status":
                    self._set_status(
                        payload.get("title", ""),
                        payload.get("detail", ""),
                        payload.get("progress", None),
                        payload.get("level", "info"),
                    )
                elif typ == "terrain_map_progress":
                    for item in tuple(payload.get("items", ()) or ()):
                        if isinstance(item, _launcher_terrain_store.TerrainMapProgress):
                            self.terrain_map_progress[item.map_id] = item
                    self._refresh_terrain_map_rows()
                elif typ == "subscription_browser":
                    user_code = str(payload.get("user_code", "")).strip()
                    url = str(payload.get("url", "")).strip()
                    self._set_status(
                        "等待 CheemsPay 授权",
                        f"已打开浏览器，请登录并确认设备码 {user_code}",
                        None,
                        "info",
                    )
                    if url:
                        with contextlib.suppress(Exception):
                            webbrowser.open(url)
                elif typ == "subscription_state":
                    self._refresh_subscription_ui()
                elif typ == "subscription_done":
                    ok = bool(payload.get("ok", False))
                    detail = str(payload.get("detail", "")).strip()
                    self.current_task = ""
                    self._set_running(False)
                    if ok:
                        # The worker has persisted the receipt before emitting
                        # this event. Re-read it on the UI thread so the same
                        # session immediately exposes Enhanced; otherwise the
                        # menu keeps the pre-login missing-receipt decision
                        # until the next Launcher restart.
                        self._refresh_cached_subscription_access()
                    self._refresh_subscription_ui()
                    self._set_status(
                        "订阅授权完成" if ok else "订阅授权失败",
                        detail,
                        1.0 if ok else 0.0,
                        "success" if ok else "warning",
                    )
                    if ok:
                        self.root.after(200, lambda: self._begin_check(automatic=False))
                elif typ == "check_done":
                    ok = bool(payload.get("ok", False))
                    self.last_download_success = False
                    if ok:
                        self.last_check_ok = True
                        self.last_check_error = ""
                        self.latest_manifest = payload.get("manifest", None)
                        self.latest_remote_version = str(
                            payload.get("remote_version", self.local_version)
                        )
                        self.latest_min_launcher_version = str(
                            payload.get("min_launcher_version", "")
                        ).strip()
                        self.latest_source_name = str(payload.get("source_name", "GitHub"))
                        self.latest_package_size = payload.get("package_size", None)
                        self.update_available = bool(payload.get("update_available", False))
                        self.app_requires_launcher_update = bool(
                            payload.get("app_requires_launcher_update", False)
                        )
                        self.latest_terrain_manifest = payload.get("terrain_manifest", None)
                        reported_local_revision = str(
                            payload.get("terrain_local_revision", "")
                        ).strip()
                        self.terrain_local_revision = reported_local_revision
                        self.terrain_remote_revision = str(
                            payload.get("terrain_remote_revision", "")
                        ).strip()
                        self.terrain_remote_map_count = int(
                            payload.get("terrain_remote_map_count", 0) or 0
                        )
                        self.terrain_remote_total_size = int(
                            payload.get("terrain_remote_total_size", 0) or 0
                        )
                        self.terrain_catalog_available = bool(
                            payload.get("terrain_catalog", False)
                        )
                        self.terrain_catalog_map_count = int(
                            payload.get("terrain_catalog_map_count", 0) or 0
                        )
                        self.terrain_catalog_selected_count = int(
                            payload.get("terrain_catalog_selected_count", 0) or 0
                        )
                        self.terrain_catalog_selected_map_ids = tuple(
                            payload.get("terrain_catalog_selected_map_ids", ()) or ()
                        )
                        self.terrain_selection_size_bytes = int(
                            payload.get("terrain_selection_size_bytes", 0) or 0
                        )
                        self.terrain_source_name = str(
                            payload.get("terrain_source_name", "")
                        ).strip()
                        self.terrain_update_available = bool(
                            payload.get("terrain_update_available", False)
                        )
                        self.terrain_download_size = int(
                            payload.get("terrain_download_size", 0) or 0
                        )
                        self.terrain_reuse_size = int(
                            payload.get("terrain_reuse_size", 0) or 0
                        )
                        self.terrain_check_warning = str(
                            payload.get("terrain_check_warning", "")
                        ).strip()
                        self.terrain_check_blocking = bool(
                            payload.get("terrain_check_blocking", False)
                        )
                        if reported_local_revision:
                            self.terrain_local_state = "ready"
                            if reported_local_revision == self.terrain_remote_revision:
                                self.terrain_local_map_count = self.terrain_remote_map_count
                                self.terrain_local_total_size = (
                                    self.terrain_remote_total_size
                                )
                        elif self.terrain_check_blocking:
                            store = _terrain_store_for_base(self.base)
                            self.terrain_local_state = (
                                "invalid" if store.current_path.exists() else "missing"
                            )
                        self.latest_launcher_manifest = payload.get("launcher_manifest", None)
                        self.latest_launcher_version = str(
                            payload.get("launcher_remote_version", LAUNCHER_VERSION)
                        )
                        self.latest_launcher_source_name = str(
                            payload.get("launcher_source_name", "GitHub")
                        )
                        self.latest_launcher_package_size = payload.get(
                            "launcher_package_size", None
                        )
                        self.latest_launcher_check_warning = str(
                            payload.get("launcher_check_warning", "")
                        ).strip()
                        self.launcher_update_available = bool(
                            payload.get("launcher_update_available", False)
                        )

                        if self.app_requires_launcher_update:
                            detail = self._compose_check_detail()
                            self._set_status("需要先更新启动器", detail, 0.0, "warning")
                        elif self.update_available:
                            detail = self._compose_check_detail()
                            self._set_status("发现新版本", detail, 0.0, "success")
                        elif self.terrain_update_available:
                            detail = self._compose_check_detail()
                            self._set_status("发现地形数据更新", detail, 0.0, "success")
                        elif self.launcher_update_available:
                            detail = self._compose_check_detail()
                            self._set_status("检测到启动器更新", detail, 0.0, "success")
                        elif (
                            self.terrain_catalog_available
                            and self.terrain_catalog_selected_count == 0
                        ):
                            detail = self._compose_check_detail()
                            self._set_status("请选择地图", detail, 0.0, "info")
                        else:
                            detail = self._compose_check_detail()
                            self._set_status("已是最新版本", detail, 0.0, "success")
                    else:
                        self.last_check_ok = False
                        self.update_available = False
                        self.app_requires_launcher_update = False
                        self.latest_manifest = None
                        self.latest_min_launcher_version = ""
                        self.latest_package_size = None
                        self.latest_source_name = ""
                        self.latest_terrain_manifest = None
                        self.terrain_remote_revision = ""
                        self.terrain_remote_map_count = 0
                        self.terrain_remote_total_size = 0
                        self.terrain_catalog_available = False
                        self.terrain_catalog_map_count = 0
                        self.terrain_catalog_selected_count = 0
                        self.terrain_catalog_selected_map_ids = ()
                        self.terrain_selection_size_bytes = 0
                        self.terrain_source_name = ""
                        self.terrain_update_available = False
                        self.terrain_download_size = 0
                        self.terrain_reuse_size = 0
                        self.terrain_check_warning = ""
                        self.terrain_check_blocking = False
                        self.latest_launcher_manifest = None
                        self.latest_launcher_package_size = None
                        self.latest_launcher_source_name = ""
                        self.latest_launcher_check_warning = ""
                        self.launcher_update_available = False
                        self.last_check_error = str(payload.get("error", "检查失败"))
                        self._set_status(
                            "检查失败",
                            self._with_recovery_warning(self.last_check_error),
                            0.0,
                            "warning",
                        )
                    self._refresh_installed_versions()
                    self.current_task = ""
                    self._set_running(False)
                    if self._exit_after_task:
                        self._finalize_exit()
                        continue
                    if self._recheck_requested:
                        self._recheck_requested = False
                        self._begin_check(automatic=False)
                        continue
                    if not ok:
                        self._show_error_actions()
                elif typ == "download_done":
                    final_version = str(payload.get("final_version", self.local_version))
                    warning = str(payload.get("warning", ""))
                    update_ok = bool(payload.get("update_ok", False))
                    # Keep a launchable decision after successful install; only
                    # preserve exit when the window was already closing.
                    if not self._exit_after_task:
                        self.decision = LaunchDecision(
                            action="idle" if update_ok else "exit",
                            final_version=final_version,
                            warning=warning,
                        )
                    self.current_task = ""
                    try:
                        # Always leave the download-running state before any modal UI.
                        self._set_status(
                            str(payload.get("status", "")),
                            str(payload.get("detail", "")),
                            1.0 if update_ok else self.progress_value,
                            str(payload.get("level", "info")),
                        )
                        self._refresh_installed_versions()
                        if update_ok:
                            self.update_available = False
                            self.app_requires_launcher_update = False
                            terrain_revision = str(payload.get("terrain_revision", "")).strip()
                            if terrain_revision:
                                self.terrain_local_revision = terrain_revision
                                self.terrain_remote_revision = terrain_revision
                            self.terrain_update_available = False
                            self.terrain_download_size = 0
                            self.terrain_reuse_size = 0
                            self.terrain_check_warning = ""
                            self.terrain_check_blocking = False
                            self.latest_min_launcher_version = ""
                            self.latest_package_size = None
                            self.last_check_ok = True
                            self.last_download_success = True
                            self._refresh_local_terrain_snapshot()
                        else:
                            self.last_download_success = False
                    finally:
                        self._set_running(False)

                    if update_ok:
                        whats_new = str(payload.get("whats_new", "")).strip()
                        whats_new_warning = str(payload.get("whats_new_warning", "")).strip()
                        try:
                            if whats_new:
                                WhatsNewDialog(
                                    self.root,
                                    final_version,
                                    str(payload.get("source_name", "")),
                                    whats_new,
                                )
                            elif whats_new_warning:
                                messagebox.showwarning(
                                    "What's New",
                                    whats_new_warning,
                                    parent=self.root,
                                )
                        except Exception as exc:
                            _log(self.base, f"What's New 显示失败：{exc}")
                            with contextlib.suppress(tk.TclError):
                                messagebox.showwarning(
                                    "What's New",
                                    f"更新说明窗口显示失败，但应用已安装完成。\n{exc}",
                                    parent=self.root,
                                )
                    if self._exit_after_task:
                        self._finalize_exit()
                        continue
                    if not update_ok:
                        self._show_error_actions()
                elif typ == "rollback_done":
                    ok = bool(payload.get("update_ok", False))
                    self._set_status(
                        str(payload.get("status", "")),
                        str(payload.get("detail", "")),
                        self.progress_value,
                        str(payload.get("level", "info")),
                    )
                    self.last_download_success = False
                    self.current_task = ""
                    self._refresh_installed_versions()
                    self._set_running(False)
                    if not ok:
                        self._show_error_actions()
                elif typ == "launcher_done":
                    ok = bool(payload.get("update_ok", False))
                    self._set_status(
                        str(payload.get("status", "")),
                        str(payload.get("detail", "")),
                        1.0 if ok else self.progress_value,
                        str(payload.get("level", "info")),
                    )
                    self.current_task = ""
                    self._set_running(False)
                    if ok:
                        self.launcher_update_available = False
                        self.latest_launcher_manifest = None
                        self.root.after(400, self._finalize_exit)
                    else:
                        self._show_error_actions()
        except queue.Empty:
            pass
        finally:
            self.root.after(80, self._poll_events)

    def _animate(self) -> None:
        if self.running:
            self.anim_phase += 1
            self._render_status_text()
            if self.indeterminate:
                width = self.progress_width
                block = max(self._px(70), int(width * 0.2))
                x = (self.anim_phase * self._px(14)) % (width + block) - block
                x0 = max(0, x)
                x1 = min(width, x + block)
                self.progress_canvas.coords(self.progress_bar, x0, 0, x1, self.progress_height)
        self.root.after(100, self._animate)

    def _status_color(self, level: str) -> str:
        color = _THEME["BLUE"]
        if level == "success":
            color = _THEME["GREEN"]
        elif level == "warning":
            color = _THEME["YELLOW"]
        elif level == "error":
            color = _THEME["RED"]
        return color

    def _render_status_text(self) -> None:
        title = self.status_title or ""
        if self.running:
            symbol = self._spin[self.anim_phase % len(self._spin)]
        else:
            symbol_map = {
                "success": "✓",
                "warning": "!",
                "error": "×",
                "info": "•",
            }
            symbol = symbol_map.get(self.status_level, "•")
        text = f"{symbol} {title}" if title else symbol
        self.status_lbl.config(text=text, fg=self._status_color(self.status_level))

    def _refresh_progress_visibility(self) -> None:
        if not hasattr(self, "progress_canvas"):
            return
        should_show = bool(self.running)
        manager = self.progress_canvas.winfo_manager()
        if should_show and manager != "pack":
            self.progress_canvas.pack(padx=self._px(16), pady=(self._px(14), self._px(6)))
        elif (not should_show) and manager == "pack":
            self.progress_canvas.pack_forget()

    def _set_status(self, title: str, detail: str, progress: Optional[float], level: str) -> None:
        if title:
            self.status_title = title
        self.status_level = level
        self._render_status_text()
        self.detail_lbl.config(text=detail or "")

        if progress is None:
            self.indeterminate = True
        else:
            self.indeterminate = False
            self.progress_value = max(0.0, min(1.0, progress))
            width = int(self.progress_width * self.progress_value)
            self.progress_canvas.coords(self.progress_bar, 0, 0, width, self.progress_height)
        self._refresh_progress_visibility()
        self._schedule_layout_reflow()

    def _compose_check_detail(self) -> str:
        lines = []
        if self.recovery_warning:
            lines.append(f"安装恢复已安全停止：{self.recovery_warning}")
        if self.last_check_ok and self.update_available:
            size_text = _format_size_text(self.latest_package_size)
            if self.app_requires_launcher_update and self.latest_min_launcher_version:
                lines.append(
                    f"应用 v{self.latest_remote_version} 需要 {_format_min_launcher_requirement(self.latest_min_launcher_version)}"
                )
                lines.append(
                    f"当前启动器版本：v{LAUNCHER_VERSION}；应用来源：{self.latest_source_name}；包大小：{size_text}"
                )
            else:
                lines.append(
                    f"应用 v{self.local_version} -> v{self.latest_remote_version}（来源：{self.latest_source_name}，大小：{size_text}）"
                )
        elif self.last_check_ok:
            lines.append(
                f"应用当前版本 v{self.local_version}（来源：{self.latest_source_name or '本地/腾讯云'}）"
            )
        if _normalize_channel(self.channel) == "Enhanced":
            if self.terrain_update_available:
                lines.append(
                    (
                        f"地形数据 -> {self.terrain_remote_revision[:12]} "
                        f"（来源：{self.terrain_source_name or '地形更新服务'}，"
                        f"差量下载：{_format_size_text(self.terrain_download_size)}，"
                        f"本地复用：{_format_size_text(self.terrain_reuse_size)}）"
                    )
                )
            elif self.terrain_local_revision:
                lines.append(f"地形数据当前版本 {self.terrain_local_revision[:12]}（无需下载）")
            if self.terrain_check_warning:
                prefix = "地形数据不可用" if self.terrain_check_blocking else "地形更新检查暂不可用"
                lines.append(f"{prefix}：{self.terrain_check_warning}")
        if self.launcher_update_available:
            launcher_size_text = _format_size_text(self.latest_launcher_package_size)
            lines.append(
                f"启动器 v{LAUNCHER_VERSION} -> v{self.latest_launcher_version}（来源：{self.latest_launcher_source_name}，大小：{launcher_size_text}）"
            )
        elif self.latest_launcher_check_warning:
            lines.append(f"启动器更新检查暂不可用：{self.latest_launcher_check_warning}")
        return "\n".join(line for line in lines if line)

    def _with_recovery_warning(self, detail: str) -> str:
        lines = []
        if self.recovery_warning:
            lines.append(f"安装恢复已安全停止：{self.recovery_warning}")
        if detail:
            lines.append(detail)
        return "\n".join(lines)

    def _subline_text(self) -> str:
        base = (
            f"通道：{_channel_display_name(self.channel)}"
            f"  |  本地版本：v{self.local_version}"
        )
        if self.previous_version != "0.0.0":
            if not _is_previous_app_ready(self.base, self.channel):
                return f"{base}  |  上一版不兼容：v{self.previous_version}"
            return f"{base}  |  可回退：v{self.previous_version}"
        return base

    def _rollback_status_text(self) -> str:
        if self.source_test_mode:
            return "源码模式不写入安装槽，因此不提供回退。"
        if self.previous_version != "0.0.0":
            if not _is_previous_app_ready(self.base, self.channel):
                return f"上一版 v{self.previous_version} 与 Launcher 3 不兼容，无法回退。"
            return f"上一版 v{self.previous_version}；回退后仍保留当前 v{self.local_version}。"
        return "成功更新或导入后，会自动保留一个上一版本。"

    def _refresh_installed_versions(self) -> None:
        self.install_dir = _app_runtime_dir(self.base, self.channel)
        self.local_version = install_txn.read_local_app_version(
            _app_runtime_dir(self.base, self.channel)
        )
        self.previous_version = install_txn.read_local_app_version(
            _previous_app_dir(self.base, self.channel)
        )
        self.sub_lbl.config(text=self._subline_text())
        if hasattr(self, "rollback_status_lbl"):
            self.rollback_status_lbl.config(text=self._rollback_status_text())

    def _queue_recheck_after_check(self, reason: str) -> None:
        self._recheck_requested = True
        detail = str(reason or "").strip() or "当前检查结束后将自动重新检查。"
        self._set_status("已记录新的检查条件", detail, None, "info")

    def _update_launch_button_label(self) -> None:
        if self.source_test_mode:
            self.launch_btn.config(text="启动源码应用")
            self._style_action_button(self.launch_btn, "primary")
            return
        if self.last_download_success:
            self.launch_btn.config(text="启动（已下载更新）")
            self._style_action_button(self.launch_btn, "success")
            return
        if self.last_check_ok and not (
            self.update_available or self.terrain_update_available
        ):
            self.launch_btn.config(text="启动应用")
            self._style_action_button(self.launch_btn, "primary")
            return
        if self.last_check_ok and (
            self.update_available or self.terrain_update_available
        ):
            self.launch_btn.config(text="启动本地（跳过更新）")
            self._style_action_button(self.launch_btn, "secondary")
            return
        self.launch_btn.config(text="启动应用（本地）")
        self._style_action_button(self.launch_btn, "primary")

    def _update_download_button_state(self) -> None:
        if self.source_test_mode:
            self.start_btn.config(text="源码模式不下载")
            self._style_action_button(self.start_btn, "secondary")
            return
        if self.last_check_ok and self.update_available and self.app_requires_launcher_update:
            self.start_btn.config(text="需先更新启动器")
            self._style_action_button(self.start_btn, "secondary")
            return
        if self.terrain_update_available and not self.update_available:
            self.start_btn.config(text="更新地形数据")
        else:
            self.start_btn.config(text="下载更新")
        self._style_action_button(
            self.start_btn,
            (
                "primary"
                if (
                    self.last_check_ok
                    and (self.update_available or self.terrain_update_available)
                )
                else "secondary"
            ),
        )

    def _update_launcher_button_state(self) -> None:
        if self.source_test_mode:
            self.launcher_btn.config(text="源码模式不更新", state="disabled")
            self._style_action_button(self.launcher_btn, "secondary")
            return
        if self.launcher_update_available:
            self.launcher_btn.config(text="更新启动器", state="normal")
            self._style_action_button(self.launcher_btn, "primary")
            return
        self.launcher_btn.config(text="启动器已最新", state="disabled")
        self._style_action_button(self.launcher_btn, "secondary")

    def _update_rollback_button_state(self) -> None:
        if self.source_test_mode:
            self.rollback_btn.config(text="源码模式不回退", state="disabled")
            if hasattr(self, "rollback_status_lbl"):
                self.rollback_status_lbl.config(text=self._rollback_status_text())
            self._style_action_button(self.rollback_btn, "secondary")
            return
        if self.previous_version != "0.0.0" and _is_previous_app_ready(
            self.base, self.channel
        ):
            self.rollback_btn.config(text=f"回退 v{self.previous_version}", state="normal")
            if hasattr(self, "rollback_status_lbl"):
                self.rollback_status_lbl.config(text=self._rollback_status_text())
            self._style_action_button(self.rollback_btn, "warning")
            return
        self.rollback_btn.config(text="无回退版本", state="disabled")
        if hasattr(self, "rollback_status_lbl"):
            self.rollback_status_lbl.config(text=self._rollback_status_text())
        self._style_action_button(self.rollback_btn, "secondary")

    def _set_running(self, running: bool) -> None:
        self.running = running
        self._render_status_text()
        self._refresh_progress_visibility()
        self._update_download_button_state()
        self._update_launch_button_label()
        self._update_launcher_button_state()
        self._update_rollback_button_state()
        state = "disabled" if running else "normal"
        update_controls_state = "disabled" if self.source_test_mode else state
        self.start_btn.config(state=update_controls_state)
        self.launcher_btn.config(state=("disabled" if running else self.launcher_btn.cget("state")))
        self.retry_btn.config(state=update_controls_state)
        if running and self.current_task == "check" and _is_local_app_ready(
            self.base, self.channel
        ):
            # Allow launching local app immediately while background check continues.
            self.launch_btn.config(state="normal")
        else:
            self.launch_btn.config(state=state)
        self.release_btn.config(state="normal")
        if hasattr(self, "import_btn"):
            self.import_btn.config(
                state=("disabled" if self.source_test_mode else "normal")
            )
        if hasattr(self, "download_dir_btn"):
            self.download_dir_btn.config(state="normal")
        self.details_btn.config(state="normal")
        self.exit_btn.config(state="normal")
        self.rollback_btn.config(state=("disabled" if running else self.rollback_btn.cget("state")))
        self.channel_menu.config(
            state=("normal" if running and self.current_task == "check" else state)
        )
        self.download_source_menu.config(
            state=(
                "disabled"
                if not _DISTRIBUTION_BUILD_METADATA.github_fallback_allowed
                else ("normal" if (not running or self.current_task == "check") else "disabled")
            )
        )
        if hasattr(self, "proxy_chk"):
            self.proxy_chk.config(
                state=("normal" if running and self.current_task == "check" else state)
            )
        if hasattr(self, "web_dashboard_autostart_chk"):
            self.web_dashboard_autostart_chk.config(state="normal")
        if hasattr(self, "web_dashboard_auto_open_chk"):
            self.web_dashboard_auto_open_chk.config(state="normal")
        if hasattr(self, "web_dashboard_lan_enabled_chk"):
            self.web_dashboard_lan_enabled_chk.config(state="normal")
        if hasattr(self, "terrain_select_btn"):
            self.terrain_select_btn.config(
                state=(
                    "normal"
                    if self.terrain_catalog_available
                    and (not running or self.current_task == "download")
                    else "disabled"
                )
            )
        self._refresh_subscription_ui()

        if running:
            self.retry_btn.pack_forget()
            if self.current_task == "check":
                self.hint_lbl.config(
                    text="正在后台检查应用与启动器更新；此时可继续切换通道/下载来源，当前检查结束后会自动按新条件重查。"
                )
            elif self.current_task == "launcher_download":
                self.hint_lbl.config(
                    text="正在下载临时新版启动器文件，并准备替换当前 exe；请不要强制结束进程。"
                )
            elif self.current_task == "subscription_login":
                self.hint_lbl.config(
                    text="正在等待浏览器中的 CheemsPay 设备授权；可随时取消。"
                )
            else:
                self.hint_lbl.config(text="正在下载并安装更新，请稍候...")
        else:
            if self.has_attempted_update and (not self.source_test_mode):
                self.retry_btn.pack(side="left", padx=(8, 0))
            else:
                self.retry_btn.pack_forget()
            if (
                (not self.source_test_mode)
                and self.last_check_ok
                and (self.update_available or self.terrain_update_available)
                and (not self.app_requires_launcher_update)
            ):
                self.start_btn.config(state="normal")
            else:
                self.start_btn.config(state="disabled")
            if _is_local_app_ready(self.base, self.channel):
                self.launch_btn.config(state="normal")
            else:
                self.launch_btn.config(state="disabled")
            if self.source_test_mode:
                self.hint_lbl.config(
                    text=(
                        "当前处于源码测试模式：launcher.pyw 将从同目录启动 Bomana.pyw，"
                        "不会自动检查或覆盖安装线上版本。"
                    )
                )
            elif self.last_check_ok and self.update_available and self.app_requires_launcher_update:
                if self.launcher_update_available:
                    self.hint_lbl.config(
                        text=(
                            f"应用 v{self.latest_remote_version} 要求 {_format_min_launcher_requirement(self.latest_min_launcher_version)}。\n"
                            f"请先点击“更新启动器”，再安装新应用包。"
                        )
                    )
                else:
                    self.hint_lbl.config(
                        text=(
                            f"应用 v{self.latest_remote_version} 要求 {_format_min_launcher_requirement(self.latest_min_launcher_version)}，"
                            "当前启动器过旧。\n请先获取最新版启动器，再安装这次更新。"
                        )
                    )
            elif self.last_check_ok and self.update_available:
                total_bytes = int(self.latest_package_size or 0)
                if self.terrain_update_available:
                    total_bytes += self.terrain_download_size
                size_text = _format_size_text(total_bytes)
                self.hint_lbl.config(
                    text=(
                        f"可下载 v{self.latest_remote_version}（本次实际下载：{size_text}）。点击“下载更新”会再次确认。\n"
                        f"安装位置：{self.install_dir}"
                    )
                )
                if self.terrain_update_available:
                    self.hint_lbl.config(
                        text=(
                            f"{self.hint_lbl.cget('text')}\n"
                            f"地形只下载变化对象 {_format_size_text(self.terrain_download_size)}，"
                            f"复用 {_format_size_text(self.terrain_reuse_size)}。"
                        )
                    )
                if self.launcher_update_available:
                    self.hint_lbl.config(
                        text=(
                            f"{self.hint_lbl.cget('text')}\n"
                            f"同时检测到启动器 v{self.latest_launcher_version} 可更新，可单独点击“更新启动器”。"
                        )
                    )
            elif self.last_check_ok and self.terrain_update_available:
                self.hint_lbl.config(
                    text=(
                        f"应用当前已是最新版本；地形数据有差量更新 "
                        f"{_format_size_text(self.terrain_download_size)}，"
                        f"将复用 {_format_size_text(self.terrain_reuse_size)}。\n"
                        "点击“更新地形数据”只维护独立资源，不会重复下载或替换 App。"
                    )
                )
            elif self.last_check_ok and self.launcher_update_available:
                launcher_size_text = _format_size_text(self.latest_launcher_package_size)
                self.hint_lbl.config(
                    text=(
                        f"应用当前已是最新版本；启动器可升级到 v{self.latest_launcher_version}（总大小：{launcher_size_text}）。\n"
                        "点击“更新启动器”后会先下载一个临时的新启动器文件，再自动替换当前 exe 并重启。"
                    )
                )
            elif self.last_check_ok and not (
                self.update_available or self.terrain_update_available
            ):
                if _is_local_app_ready(self.base, self.channel):
                    self.hint_lbl.config(
                        text=f"当前已是最新版本，可直接点击“启动应用”。\n安装位置：{self.install_dir}"
                    )
                else:
                    self.hint_lbl.config(text="当前设备没有本地版本，请等待在线更新可用后下载。")
            elif self.last_check_error:
                if _is_local_app_ready(self.base, self.channel):
                    self.hint_lbl.config(
                        text="自动检查失败，可点击“重新检查”，或先点击“启动应用”使用本地版本。"
                    )
                else:
                    self.hint_lbl.config(
                        text="自动检查失败，且当前没有本地版本。请点击“重新检查”或“打开下载页”。"
                    )
            else:
                self.hint_lbl.config(text="启动后会自动检查更新。")
            if (not self.source_test_mode) and _is_previous_app_ready(
                self.base, self.channel
            ):
                self.hint_lbl.config(
                    text=f"{self.hint_lbl.cget('text')}\n可通过“回退 v{self.previous_version}”快速切回上一版。"
                )
        self._render_terrain_status()
        self._schedule_layout_reflow()

    def _show_error_actions(self) -> None:
        if _is_local_app_ready(self.base, self.channel):
            text = "可点击“重新检查”或“打开下载页”，也可直接点击“启动应用”。"
            if _is_previous_app_ready(self.base, self.channel):
                text += f"\n如果新版异常，也可以点击“回退 v{self.previous_version}”。"
            self.hint_lbl.config(text=text)
        else:
            self.hint_lbl.config(
                text="可点击“重新检查”或“打开下载页”。首次使用请先完成下载。"
            )
        self._schedule_layout_reflow()

    def _save_launcher_state(self, extra: Optional[Dict[str, Any]] = None) -> None:
        state = _read_state(self.base)
        state.update(
            {
                "launcher_version": LAUNCHER_VERSION,
                "channel": self.channel,
                "use_system_proxy": bool(self.use_system_proxy),
                "state_updated_utc": _now_utc_iso(),
            }
        )
        if self.download_source_mode:
            state["download_source_mode"] = self.download_source_mode
        else:
            state.pop("download_source_mode", None)
        if extra:
            state.update(extra)
        for key in tuple(state):
            if isinstance(key, str) and key.startswith("web_dashboard_"):
                state.pop(key, None)
        state.update(
            {
                "web_dashboard_autostart": bool(self.web_dashboard_autostart),
                "web_dashboard_auto_open": bool(self.web_dashboard_auto_open),
                "web_dashboard_lan_enabled": bool(self.web_dashboard_lan_enabled),
            }
        )
        _write_state(self.base, state)

    def _on_proxy_changed(self) -> None:
        if self.running and self.current_task != "check":
            self.proxy_var.set(bool(self.use_system_proxy))
            return
        self.use_system_proxy = bool(self.proxy_var.get())
        _set_use_system_proxy(self.use_system_proxy)
        self._save_launcher_state()
        mode = (
            "系统代理优先（国内服务失败后自动直连重试）"
            if self.use_system_proxy
            else "直连优先（国内服务失败后自动尝试系统代理）"
        )
        if self.running and self.current_task == "check":
            self._queue_recheck_after_check(
                f"当前使用：{mode}。本次检查结束后会按新的网络设置自动重查。"
            )
            return
        self._set_status(
            "网络设置已更新",
            f"当前使用：{mode}。后续检查/下载将按此设置进行。",
            self.progress_value,
            "info",
        )

    def _on_web_preferences_changed(self) -> None:
        autostart = bool(self.web_dashboard_autostart_var.get())
        auto_open = bool(self.web_dashboard_auto_open_var.get())
        lan_enabled = bool(self.web_dashboard_lan_enabled_var.get())
        if lan_enabled and not self.web_dashboard_lan_enabled:
            autostart = True
        elif not autostart:
            lan_enabled = False
        self.web_dashboard_autostart = autostart
        self.web_dashboard_auto_open = auto_open
        self.web_dashboard_lan_enabled = lan_enabled
        self.web_dashboard_autostart_var.set(autostart)
        self.web_dashboard_lan_enabled_var.set(lan_enabled)
        self._save_launcher_state()
        effective_autostart, effective_auto_open, effective_lan, _degraded = (
            _effective_web_preferences_for_channel(
                self.channel,
                self.web_dashboard_autostart,
                self.web_dashboard_auto_open,
                self.web_dashboard_lan_enabled,
            )
        )
        _set_pending_web_preferences(
            effective_autostart,
            effective_auto_open,
            effective_lan,
        )
        # Standard/Lite intentionally keep subscriber-only preferences in the
        # saved state but silently disable them for the public app package.
        # Selecting or launching a public channel must never interrupt startup
        # with a Super Bomb-only configuration warning.

    def _on_download_source_changed(self, *_args) -> None:
        new_mode = _DOWNLOAD_SOURCE_LABEL_TO_MODE.get(
            self.download_source_var.get(),
            DOWNLOAD_SOURCE_MODE_AUTO,
        )
        if self.running and self.current_task != "check":
            self.download_source_var.set(_download_source_label(self.download_source_mode))
            return
        new_mode = _effective_download_source_mode(new_mode)
        if new_mode == self.download_source_mode:
            self._refresh_download_source_details()
            return
        self.download_source_mode = new_mode
        self._save_launcher_state()
        self._refresh_download_source_details()
        if self.running and self.current_task == "check":
            self._queue_recheck_after_check(
                DOWNLOAD_SOURCE_DETAILS.get(
                    self.download_source_mode,
                    DOWNLOAD_SOURCE_DETAILS[DOWNLOAD_SOURCE_MODE_AUTO],
                )
            )
            return
        self._set_status(
            "下载来源已更新",
            DOWNLOAD_SOURCE_DETAILS.get(
                self.download_source_mode,
                DOWNLOAD_SOURCE_DETAILS[DOWNLOAD_SOURCE_MODE_AUTO],
            ),
            self.progress_value,
            "info",
        )
        self._begin_check(automatic=True)

    def _on_start(self) -> None:
        if self.running:
            return
        if self.source_test_mode:
            messagebox.showinfo(
                DISPLAY_NAME,
                "当前处于源码测试模式，已禁用在线下载更新。\n如需验证发布包，请使用打包后的启动器或发布产物目录。",
            )
            return
        if not self.last_check_ok:
            messagebox.showwarning(DISPLAY_NAME, "尚未完成更新检查，请稍候或点击“重新检查”。")
            return
        if self.app_requires_launcher_update:
            required_text = _format_min_launcher_requirement(self.latest_min_launcher_version)
            if self.launcher_update_available:
                messagebox.showwarning(
                    DISPLAY_NAME,
                    (
                        f"应用 v{self.latest_remote_version} 要求 {required_text}。\n"
                        "请先点击“更新启动器”，更新完成后再下载应用更新。"
                    ),
                )
            else:
                messagebox.showwarning(
                    DISPLAY_NAME,
                    (
                        f"应用 v{self.latest_remote_version} 要求 {required_text}，"
                        f"当前启动器是 v{LAUNCHER_VERSION}。\n"
                        "请先下载最新版启动器，再安装这次更新。"
                    ),
                )
            return
        if not (self.update_available or self.terrain_update_available):
            messagebox.showinfo(DISPLAY_NAME, "当前已是最新版本，无需下载。")
            return
        if self.update_available and not self.latest_manifest:
            messagebox.showwarning(DISPLAY_NAME, "缺少下载清单，请先点击“重新检查”。")
            return
        if self.terrain_update_available and not self.latest_terrain_manifest:
            messagebox.showwarning(DISPLAY_NAME, "缺少地形下载清单，请先点击“重新检查”。")
            return
        app_bytes = int(self.latest_package_size or 0) if self.update_available else 0
        total_bytes = app_bytes + (
            self.terrain_download_size if self.terrain_update_available else 0
        )
        size_text = _format_size_text(total_bytes)
        action_text = (
            f"下载并安装应用 v{self.latest_remote_version}，同时维护独立地形数据"
            if self.update_available and _normalize_channel(self.channel) == "Enhanced"
            else (
                f"下载并安装应用 v{self.latest_remote_version}"
                if self.update_available
                else "差量更新独立地形数据"
            )
        )
        terrain_detail = (
            f"其中地形差量：{_format_size_text(self.terrain_download_size)}；"
            f"复用：{_format_size_text(self.terrain_reuse_size)}\n"
            if self.terrain_update_available
            else ""
        )
        ok = messagebox.askyesno(
            DISPLAY_NAME,
            (
                f"将{action_text}。\n"
                f"本次实际下载总大小：{size_text}\n"
                f"{terrain_detail}"
                f"安装位置：{self.install_dir}\n"
                "是否现在开始下载？"
            ),
        )
        if not ok:
            return
        self.last_download_success = False
        self.current_task = "download"
        self.has_attempted_update = True
        self._set_status(
            "准备下载",
            f"{action_text}，实际下载：{size_text}\n安装位置：{self.install_dir}",
            0.0,
            "info",
        )
        self._set_running(True)
        self._start_worker("download")

    def _on_update_launcher(self) -> None:
        if self.running:
            return
        if self.source_test_mode:
            messagebox.showinfo(
                DISPLAY_NAME,
                "当前处于源码测试模式，已禁用启动器自更新。\n如需验证启动器升级流程，请使用发布后的 exe。",
            )
            return
        if not self.last_check_ok:
            messagebox.showwarning(DISPLAY_NAME, "尚未完成更新检查，请稍候或点击“重新检查”。")
            return
        if not self.launcher_update_available:
            messagebox.showinfo(DISPLAY_NAME, "当前启动器已是最新版本。")
            return
        if not self.latest_launcher_manifest:
            messagebox.showwarning(DISPLAY_NAME, "缺少启动器下载清单，请先点击“重新检查”。")
            return
        if not _is_frozen_launcher():
            messagebox.showinfo(
                DISPLAY_NAME,
                "当前是源码运行模式，无法直接替换启动器可执行文件。\n将为你打开发布页手动获取新版启动器。",
            )
            self._open_releases()
            return
        size_text = _format_size_text(self.latest_launcher_package_size)
        ok = messagebox.askyesno(
            DISPLAY_NAME,
            (
                f"将下载并升级启动器到 v{self.latest_launcher_version}。\n"
                f"下载总大小：{size_text}\n"
                "升级时会先下载一个临时的新版启动器文件，不需要你手动双击它。\n"
                f"当前窗口关闭后，它会自动替换当前启动器 exe（{Path(sys.executable).name}）并重启。\n"
                "是否现在开始？"
            ),
        )
        if not ok:
            return
        self.current_task = "launcher_download"
        self.has_attempted_update = True
        self._set_status(
            "准备更新启动器",
            f"即将下载新版启动器文件 v{self.latest_launcher_version}，总大小：{size_text}",
            0.0,
            "info",
        )
        self._set_running(True)
        self._start_worker("launcher_download")

    def _on_rollback(self) -> None:
        if self.running:
            return
        if self.source_test_mode:
            messagebox.showinfo(
                DISPLAY_NAME,
                "当前处于源码测试模式，不使用应用包安装目录，因此不提供版本回退。",
            )
            return
        if self.previous_version == "0.0.0" or not _is_previous_app_ready(
            self.base, self.channel
        ):
            messagebox.showinfo(DISPLAY_NAME, "当前没有兼容 Launcher 3 的可回退版本。")
            return
        ok = messagebox.askyesno(
            DISPLAY_NAME,
            (
                f"将把当前应用 v{self.local_version} 与上一版本 v{self.previous_version} 对调。\n"
                "回退完成后会立即保留当前版本作为新的“上一版本”，方便再次切回。\n"
                "是否继续？"
            ),
        )
        if not ok:
            return
        self.current_task = "rollback"
        self._set_status(
            "准备回退",
            f"即将从 v{self.local_version} 回退到 v{self.previous_version}。",
            0.0,
            "warning",
        )
        self._set_running(True)
        self._start_worker("rollback")

    def _on_retry(self) -> None:
        if self.source_test_mode:
            messagebox.showinfo(
                DISPLAY_NAME,
                "当前处于源码测试模式，默认不执行在线更新检查。\n如需联机验证，请改用发布目录中的启动器。",
            )
            return
        self._begin_check(automatic=False)

    def _on_import_zip(self) -> None:
        if self.running:
            return
        if self.source_test_mode:
            messagebox.showinfo(
                DISPLAY_NAME,
                "当前处于源码测试模式，已禁用本地 ZIP 安装，避免把发布包写入源码目录。",
            )
            return
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="选择本地应用包 ZIP",
            filetypes=[("Zip files", "*.zip"), ("All files", "*.*")],
        )
        if not selected:
            return
        path = Path(selected)
        ok = messagebox.askyesno(
            DISPLAY_NAME,
            (
                f"将导入并安装本地包：\n{path}\n\n"
                f"安装位置：{self.install_dir}\n"
                "这会覆盖当前本地应用。是否继续？"
            ),
        )
        if not ok:
            return
        self.pending_import_zip_path = str(path)
        self.last_download_success = False
        self.current_task = "import_zip"
        self.has_attempted_update = True
        self._set_status("准备导入", f"即将导入：{path.name}", 0.0, "info")
        self._set_running(True)
        self._start_worker("import_zip")

    def _on_channel_changed(self, *_args) -> None:
        if getattr(self, "_channel_menu_refreshing", False):
            return
        if self.running and self.current_task != "check":
            self.channel_var.set(_channel_display_name(self.channel))
            return
        requested_channel = (
            _normalize_channel(self.channel_var.get()) or self.detected_channel
        )
        if requested_channel == "Enhanced" and not self._super_bomb_access_allowed():
            self.channel = PUBLIC_FALLBACK_CHANNEL
            self._set_channel_var_silently(self.channel)
            self._save_launcher_state()
            self._refresh_installed_versions()
            self._refresh_local_terrain_snapshot()
            self._refresh_channel_details()
            self._refresh_subscription_ui()
            self._refresh_feature_visibility()
            self._set_status(
                "超级爆弹版未解锁",
                "当前仅显示 Lite / Standard 公共版；登录 Super Bomb 后可恢复高级配置。",
                0.0,
                "info",
            )
            return
        self.channel = requested_channel
        self._save_launcher_state()
        self._refresh_installed_versions()
        self._refresh_local_terrain_snapshot()
        self._refresh_channel_details()
        self._refresh_subscription_ui()
        self._refresh_feature_visibility()
        if self.running and self.current_task == "check":
            self._queue_recheck_after_check(
                f"通道已切换到 {_channel_display_name(self.channel)}，"
                "当前检查结束后将自动重查。"
            )
            return
        self._begin_check(automatic=True)

    def _refresh_channel_details(self) -> None:
        ch = _normalize_channel(self.channel_var.get()) or self.detected_channel
        info = CHANNEL_DETAILS.get(ch, CHANNEL_DETAILS["Standard"])
        label = _download_source_label(self.download_source_mode)
        source_detail = DOWNLOAD_SOURCE_DETAILS.get(
            self.download_source_mode,
            DOWNLOAD_SOURCE_DETAILS[DOWNLOAD_SOURCE_MODE_AUTO],
        )
        self.selection_summary_lbl.config(
            text=(
                f"{info['title']}  |  推荐：{_channel_display_name(self.detected_channel)}"
                f"  |  来源：{label}\n"
                f"{info['desc']} {source_detail}"
            )
        )
        self._render_terrain_status()
        self._refresh_wraplengths()

    def _refresh_download_source_details(self) -> None:
        self._refresh_channel_details()

    def _local_app_launch_version(self) -> str | None:
        if not _is_local_app_ready(self.base, self.channel):
            detail = (
                "同目录源码入口缺失，请确认 Bomana.pyw 存在。"
                if self.source_test_mode
                else "本地没有可用应用包，请先点击“下载更新”。"
            )
            self._set_status("无法启动", detail, None, "error")
            return None
        try:
            version = install_txn.require_compatible_app_version(
                _app_runtime_dir(self.base, self.channel),
                identity_name="启动应用版本",
            )
        except Exception as exc:
            self._set_status("无法启动", str(exc), None, "error")
            return None
        selected_channel = _normalize_channel(self.channel)
        installed_channel = _installed_app_channel(self.base, self.channel)
        if (
            selected_channel in ("Lite", "Standard")
            and installed_channel
            and installed_channel != selected_channel
        ):
            self._set_status(
                "本地文件需要修复",
                "本地安装通道与当前选择不匹配；请重新下载该公共通道。",
                None,
                "warning",
            )
            return None
        return version

    def _prepare_ordinary_launch(self, final_version: str) -> None:
        self.decision = LaunchDecision(action="launch", final_version=final_version, warning="")
        self._set_status(
            "准备启动",
            f"将以普通权限启动本地版本 v{final_version}",
            1.0,
            "success",
        )
        self.root.after(300, self._commit_launch)

    def _on_launch(self) -> None:
        needs_super_bomb_access = _normalize_channel(self.channel) == "Enhanced"
        if (
            needs_super_bomb_access
            and not self.source_test_mode
            and not _DISTRIBUTION_BUILD_METADATA.isolated_test
        ):
            if self.subscription_workflow is None:
                messagebox.showwarning(
                    DISPLAY_NAME,
                    self.subscription_setup_error or "CheemsPay 订阅组件不可用",
                    parent=self.root,
                )
                return
            self.subscription_decision = self.subscription_workflow.cached_access()
            self._refresh_subscription_ui()
            if not self.subscription_decision.allowed:
                should_login = messagebox.askyesno(
                    DISPLAY_NAME,
                    f"{_subscription_access_copy(self.subscription_decision)}。\n\n现在登录或刷新 CheemsPay 吗？",
                    parent=self.root,
                )
                if should_login:
                    self._begin_subscription_login()
                return
        final_version = self._local_app_launch_version()
        if final_version is None:
            return
        self._prepare_ordinary_launch(final_version)

    def _on_launch_shortcut(self, _event=None) -> str:
        if str(self.launch_btn.cget("state")) != "disabled":
            self._on_launch()
        return "break"

    def _open_releases(self) -> None:
        try:
            webbrowser.open(RELEASES_URL)
        except Exception:
            pass

    def _open_official_site(self) -> None:
        try:
            webbrowser.open(OFFICIAL_SITE_URL)
        except Exception:
            pass

    def _open_download_dir(self) -> None:
        try:
            _open_folder(_launcher_download_dir(self.base))
        except Exception as e:
            _log(self.base, f"打开下载目录失败：{e}")
            messagebox.showwarning(DISPLAY_NAME, f"无法打开下载目录：{e}")

    def _open_details(self) -> None:
        try:
            terrain_dir: Optional[Path] = None
            terrain_revision = ""
            if _normalize_channel(self.channel) == "Enhanced":
                terrain_store = _terrain_store_for_base(self.base)
                terrain_dir = (
                    terrain_store.current_catalog_pack_dir()
                    or terrain_store.current_pack_dir()
                )
                current_catalog = terrain_store.current_catalog()
                terrain_revision = (
                    current_catalog.revision
                    if current_catalog is not None
                    else terrain_store.current_revision()
                )
            LauncherDetailsDialog(
                self.root,
                channel=self.channel,
                local_version=self.local_version,
                launcher_version=LAUNCHER_VERSION,
                install_dir=self.install_dir,
                terrain_dir=terrain_dir,
                terrain_revision=terrain_revision,
            )
        except Exception as e:
            _log(self.base, f"打开详情弹窗失败：{e}")

    def _commit_launch(self) -> None:
        if self.decision.action == "launch":
            autostart, auto_open, lan_enabled, _degraded = _effective_web_preferences_for_channel(
                self.channel,
                self.web_dashboard_autostart,
                self.web_dashboard_auto_open,
                self.web_dashboard_lan_enabled,
            )
            _set_pending_web_preferences(autostart, auto_open, lan_enabled)
            self.root.destroy()

    def _finalize_exit(self) -> None:
        self._exit_after_task = False
        self.decision = LaunchDecision(
            action="exit",
            final_version=install_txn.read_local_app_version(
                _app_runtime_dir(self.base, self.channel)
            ),
            warning=self.decision.warning,
        )
        self.root.destroy()

    def _on_exit(self) -> None:
        if self.running:
            ok = messagebox.askyesno(
                DISPLAY_NAME,
                "当前任务正在进行中。\n取消当前任务并退出可能导致本次更新无效。\n是否继续退出？",
                parent=self.root,
            )
            if not ok:
                return
            self._cancel_requested.set()
            self._exit_after_task = True
            self._set_status(
                "正在取消",
                "正在取消当前任务并等待清理完成，请稍候...",
                None,
                "warning",
            )
            return

        self._finalize_exit()

    def run(self) -> LaunchDecision:
        self.root.mainloop()
        return self.decision


def main() -> None:
    base = _base_dir()
    recovery_warning = _recover_incomplete_install(base)
    _set_pending_recovery_warning(recovery_warning)
    _cleanup_temp_files_on_launcher_upgrade(base)
    _cleanup_stale_launcher_self_update_temp(base)
    _cleanup_legacy_launcher_self_update_files(base)
    launcher_update_notice = _consume_launcher_update_result(base)
    Win32.enable_dpi()
    detected_channel = _detect_channel()

    window_kwargs: Dict[str, str] = {"recovery_warning": recovery_warning}
    if launcher_update_notice:
        window_kwargs["launcher_update_notice"] = launcher_update_notice
    try:
        gui = LauncherWindow(base, detected_channel, **window_kwargs)
    except TypeError as exc:
        if "unexpected keyword argument 'launcher_update_notice'" not in str(exc):
            raise
        gui = LauncherWindow(
            base,
            detected_channel,
            recovery_warning=recovery_warning,
        )
    decision = gui.run()
    if decision.action != "launch":
        return

    selected_channel = gui.channel

    with contextlib.suppress(Exception):
        _launcher_telemetry.start_daily_active_report(channel=selected_channel)

    try:
        _launch_app(base, selected_channel)
    except Exception as e:
        _log(base, f"App launch failed: {e}")
        _show_error(
            f"{DISPLAY_NAME} 启动失败",
            _format_app_launch_error(
                base,
                e,
                decision.final_version,
                selected_channel,
                gui.source_test_mode,
            ),
        )


if __name__ == "__main__":
    main()
