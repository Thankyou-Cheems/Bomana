# -*- coding: utf-8 -*-
"""Bomana portable launcher with user-friendly GUI update flow."""

import ctypes
import hashlib
import importlib
import ipaddress
import json
import os
import queue
import re
import runpy
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
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import (
    HTTPHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from bomana import launcher_install as _launcher_install
from bomana.launcher_core import (
    DOWNLOAD_SOURCE_CHOICES,
    DOWNLOAD_SOURCE_DETAILS,
    DOWNLOAD_SOURCE_LABEL_TO_MODE as _DOWNLOAD_SOURCE_LABEL_TO_MODE,
    DOWNLOAD_SOURCE_MODE_AUTO,
    DOWNLOAD_SOURCE_MODE_GITHUB,
    DOWNLOAD_SOURCE_MODE_PRIMARY,
    DOWNLOAD_SOURCE_MODE_TO_LABEL as _DOWNLOAD_SOURCE_MODE_TO_LABEL,
    LAUNCHER_ASSET_PREFIX,
    LaunchDecision,
    download_source_label as _download_source_label,
    find_asset as _find_asset,
    find_launcher_asset as _find_launcher_asset,
    format_min_launcher_requirement as _format_min_launcher_requirement,
    format_size_text as _format_size_text,
    join_base_url_path as _join_base_url_path,
    normalize_download_source_mode as _normalize_download_source_mode,
    parse_launcher_version_from_asset_name as _parse_launcher_version_from_asset_name,
    require_remote_checksum as _require_remote_checksum,
    sha256_bytes as _sha256_bytes,
    version_is_newer as _version_is_newer,
    version_is_older as _version_is_older,
)
from bomana.ui.tk_style import style_action_button
from bomana.utils.system import Win32, select_ui_font_family

try:
    import certifi

    _ssl_context = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _ssl_context = ssl.create_default_context()

# Launcher metadata
LAUNCHER_VERSION = "1.7.0"
MIN_SUPPORTED_APP_VERSION = "6.7.0"
DISPLAY_NAME = "Bomana香焦"
REPO_OWNER = "Thankyou-Cheems"
REPO_NAME = "Bomana"
PROJECT_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"
DEFAULT_CHANNEL = "Enhanced"
APP_DIR_NAME = _launcher_install.APP_DIR_NAME
APP_PREVIOUS_DIR_NAME = _launcher_install.APP_PREVIOUS_DIR_NAME
APP_BACKUP_DIR_NAME = _launcher_install.APP_BACKUP_DIR_NAME
STATE_FILE_NAME = "launcher_state.json"
LOG_FILE_NAME = "launcher.log"
INSTALL_ID_FILE_NAME = ".bomana_install_id"
UPDATE_LOCK_FILE_NAME = _launcher_install.UPDATE_LOCK_FILE_NAME
UPDATE_LOCK_STALE_SEC = _launcher_install.UPDATE_LOCK_STALE_SEC
TEMP_META_FILE_NAME = ".bomana_temp_meta.json"
LAUNCHER_UPDATE_RESULT_FILE_NAME = ".bomana_launcher_update_result.json"
LAUNCHER_SELF_UPDATE_WORKDIR_PREFIX = "bomana_launcher_update_"
LAUNCHER_SELF_UPDATE_TEMP_STALE_SEC = 3 * 24 * 60 * 60
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
PRIMARY_UPDATE_BASE_URL = (
    os.environ.get("BOMANA_UPDATE_BASE_URL", "https://bomanaupdate.ruikang.wang")
    .strip()
    .rstrip("/")
)
PRIMARY_VERSION_API_PATH = "/api/v1/version"
PRIMARY_LAUNCHER_API_PATH = "/api/v1/launcher"
PRIMARY_EVENT_API_PATH = "/api/v1/event"
# 默认优先使用国内服务分发下载包；只有显式关闭时才回退为“仅版本检查”。
PRIMARY_ALLOW_PACKAGE_DOWNLOAD = os.environ.get(
    "BOMANA_PRIMARY_ALLOW_PACKAGE_DOWNLOAD", "1"
).strip().lower() not in ("0", "false", "no", "off")
BRANDING_ICON_FILE = "bomana/assets/branding/app.ico"
BRANDING_SPONSOR_FILE = "bomana/assets/branding/sponsor_wechat.png"

RELEASES_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/latest"
InstallTransaction = _launcher_install.InstallTransaction
_acquire_update_lock = _launcher_install.acquire_update_lock
_install_zip_package = _launcher_install.install_zip_package
_read_local_app_version = _launcher_install.read_local_app_version
_release_update_lock = _launcher_install.release_update_lock
_rollback_to_previous_app = _launcher_install.rollback_to_previous_app

_USE_SYSTEM_PROXY = True
_URL_OPENERS: Dict[str, Any] = {}
_FAKE_IP_NETWORKS = (
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("100.64.0.0/10"),
)

_CHANNEL_MAP = {
    "enhanced": "Enhanced",
    "standard": "Standard",
    "lite": "Lite",
}

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
    "Enhanced": {
        "title": "增强版 (推荐大多数玩家)",
        "desc": "包含计时器 + 战区/机场导航 + 燃油管理 + CCRP投弹预测。",
        "who": "适合：轰炸、导航、编队协同等完整玩法。",
    },
    "Standard": {
        "title": "标准版 (稳定轻量)",
        "desc": "包含计时器 + 战区/机场导航 + 燃油管理，不含CCRP投弹预测。",
        "who": "适合：不需要投弹预测，但需要导航和油量信息。",
    },
    "Lite": {
        "title": "精简版 (极简模式)",
        "desc": "仅保留核心复活计时器，资源占用最低。",
        "who": "适合：只想看计时、追求最小干扰和最低开销。",
    },
}


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


def _is_source_test_run(base: Path) -> bool:
    if _is_frozen_launcher():
        return False
    return (base / DEFAULT_ENTRYPOINT).exists() and (base / "bomana" / "config.py").exists()


def _app_runtime_dir(base: Path) -> Path:
    if _is_source_test_run(base):
        return base
    return base / APP_DIR_NAME


def _previous_app_dir(base: Path) -> Path:
    return base / APP_PREVIOUS_DIR_NAME


def _apply_window_icon(window: tk.Misc) -> None:
    icon_path = _resource_path(BRANDING_ICON_FILE)
    if not icon_path.exists():
        return
    try:
        window.iconbitmap(default=str(icon_path))
    except Exception:
        pass


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(base: Path, msg: str) -> None:
    try:
        with (base / LOG_FILE_NAME).open("a", encoding="utf-8") as f:
            f.write(f"[{_now_utc_iso()}] {msg}\n")
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


def _set_use_system_proxy(enabled: bool) -> None:
    global _USE_SYSTEM_PROXY
    _USE_SYSTEM_PROXY = bool(enabled)


def _get_url_opener() -> Any:
    key = "proxy" if _USE_SYSTEM_PROXY else "direct"
    opener = _URL_OPENERS.get(key)
    if opener is not None:
        return opener

    handlers = [HTTPHandler(), HTTPSHandler(context=_ssl_context)]
    if _USE_SYSTEM_PROXY:
        handlers.append(ProxyHandler())
    else:
        handlers.append(ProxyHandler({}))
    opener = build_opener(*handlers)
    _URL_OPENERS[key] = opener
    return opener


def _open_url(req: Request, timeout: float):
    opener = _get_url_opener()
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
) -> bytes:
    req_headers = {
        "User-Agent": UA,
        "Accept": "application/json, application/vnd.github+json, */*",
    }
    if headers:
        req_headers.update(headers)

    req = Request(
        url,
        headers=req_headers,
    )
    with _open_url(
        req, timeout=(timeout_sec if timeout_sec is not None else NET_TIMEOUT_SEC)
    ) as resp:
        total: Optional[int] = None
        try:
            header = resp.headers.get("Content-Length")
            total = int(header) if header else None
        except Exception:
            total = None

        chunks = []
        downloaded = 0
        while True:
            if cancel_cb and cancel_cb():
                raise RuntimeError("已取消当前操作")
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            downloaded += len(chunk)
            if progress_cb:
                progress_cb(downloaded, total)
            if cancel_cb and cancel_cb():
                raise RuntimeError("已取消当前操作")

        if progress_cb:
            progress_cb(downloaded, total)
        return b"".join(chunks)


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


def _is_local_app_ready(base: Path) -> bool:
    return (_app_runtime_dir(base) / DEFAULT_ENTRYPOINT).exists()


def _is_previous_app_ready(base: Path) -> bool:
    return (_previous_app_dir(base) / DEFAULT_ENTRYPOINT).exists()


def _recover_incomplete_install(base: Path) -> None:
    steps = InstallTransaction.recover_incomplete(base, log_cb=_log)
    if steps:
        _log(base, f"检测到上次安装未完成，已恢复：{', '.join(steps)}")


def _write_state(base: Path, state: Dict[str, Any]) -> None:
    path = base / STATE_FILE_NAME
    try:
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _read_state(base: Path) -> Dict[str, Any]:
    path = base / STATE_FILE_NAME
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _read_temp_meta(base: Path) -> Dict[str, Any]:
    path = base / TEMP_META_FILE_NAME
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _write_temp_meta(base: Path, data: Dict[str, Any]) -> None:
    path = base / TEMP_META_FILE_NAME
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
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


def _consume_launcher_update_result(base: Path) -> None:
    path = base / LAUNCHER_UPDATE_RESULT_FILE_NAME
    if not path.exists():
        return

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        _log(base, f"读取启动器自更新结果失败：{e}")
        try:
            path.unlink()
        except Exception:
            pass
        return

    try:
        status = str(payload.get("status", "")).strip().lower()
        version = str(payload.get("target_version", "")).strip()
        message = str(payload.get("message", "")).strip()
        if status == "success":
            _log(base, f"启动器自更新成功：v{version or LAUNCHER_VERSION} {message}".strip())
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


def _load_or_create_install_id(base: Path) -> str:
    path = base / INSTALL_ID_FILE_NAME
    try:
        if path.exists():
            text = path.read_text(encoding="utf-8").strip().lower()
            if re.fullmatch(r"[0-9a-f]{32}", text):
                return text
    except Exception:
        pass

    install_id = uuid.uuid4().hex
    try:
        path.write_text(install_id, encoding="utf-8")
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
            _set_use_system_proxy(use_proxy)
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
        _set_use_system_proxy(original_proxy_mode)


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
    remote_version = str(manifest.get("app_version", "")).strip()
    min_launcher_version = str(manifest.get("min_launcher_version", "")).strip()
    package_asset = str(manifest.get("package_asset", "")).strip()
    package_sha256 = _require_remote_checksum(
        manifest.get("package_sha256", ""),
        artifact_label=f"{manifest_name} ",
    )
    entrypoint = str(manifest.get("entrypoint", DEFAULT_ENTRYPOINT)).strip() or DEFAULT_ENTRYPOINT
    if not remote_version or not package_asset:
        raise RuntimeError("发布清单字段缺失")

    app_asset = _find_asset(assets, package_asset)
    if not app_asset:
        raise RuntimeError(f"未找到应用包: {package_asset}")
    package_url = str(app_asset.get("browser_download_url", "")).strip()
    if not package_url:
        raise RuntimeError("应用包下载地址无效")
    package_size = app_asset.get("size", None)

    return {
        "remote_version": remote_version,
        "min_launcher_version": min_launcher_version,
        "package_url": package_url,
        "package_sha256": package_sha256,
        "entrypoint": entrypoint,
        "package_size": package_size,
        "source_name": (f"GitHub ({tag_name})" if tag_name else "GitHub"),
    }


def _launcher_manifest_from_github_release(release: Dict[str, Any]) -> Dict[str, Any]:
    assets = release.get("assets", [])
    tag_name = str(release.get("tag_name", "")).strip()
    launcher_asset = _find_launcher_asset(assets)
    if not launcher_asset:
        raise RuntimeError("未找到启动器安装包")

    asset_name = str(launcher_asset.get("name", "")).strip()
    remote_version = _parse_launcher_version_from_asset_name(asset_name)
    package_url = str(launcher_asset.get("browser_download_url", "")).strip()
    if not remote_version or not package_url:
        raise RuntimeError("启动器发布字段缺失")

    manifest_asset = _find_asset(assets, "launcher_manifest.json")
    if not manifest_asset:
        raise RuntimeError("未找到启动器发布清单")
    manifest_url = str(manifest_asset.get("browser_download_url", "")).strip()
    if not manifest_url:
        raise RuntimeError("启动器发布清单下载地址无效")
    manifest = _fetch_json(manifest_url)
    package_sha256 = _require_remote_checksum(
        manifest.get("launcher_sha256", ""),
        artifact_label="launcher_manifest.json ",
    )

    return {
        "remote_version": remote_version,
        "package_url": package_url,
        "package_sha256": package_sha256,
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
    remote_version = str(payload.get("app_version", "")).strip()
    raw_package_url = str(payload.get("package_url", "")).strip()
    package_url = (
        _join_base_url_path(PRIMARY_UPDATE_BASE_URL, raw_package_url) if raw_package_url else ""
    )
    package_sha256 = _require_remote_checksum(
        payload.get("package_sha256", ""),
        artifact_label="国内应用更新清单 ",
    )
    package_size = payload.get("package_size_bytes", payload.get("package_size"))
    entrypoint = str(payload.get("entrypoint", DEFAULT_ENTRYPOINT)).strip() or DEFAULT_ENTRYPOINT
    min_launcher_version = str(payload.get("min_launcher_version", "")).strip()
    source_name = str(payload.get("source_name", "腾讯云更新服务")).strip() or "腾讯云更新服务"
    if used_anonymous_fallback:
        source_name = f"{source_name} (匿名回退)"

    if not remote_version:
        raise RuntimeError("国内更新服务返回字段缺失")

    return {
        "remote_version": remote_version,
        "min_launcher_version": min_launcher_version,
        "package_url": package_url,
        "package_sha256": package_sha256,
        "entrypoint": entrypoint,
        "package_size": package_size,
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

    remote_version = str(payload.get("launcher_version", payload.get("app_version", ""))).strip()
    raw_package_url = str(payload.get("package_url", "")).strip()
    package_url = (
        _join_base_url_path(PRIMARY_UPDATE_BASE_URL, raw_package_url) if raw_package_url else ""
    )
    package_sha256 = _require_remote_checksum(
        payload.get("package_sha256", ""),
        artifact_label="国内启动器更新清单 ",
    )
    package_size = payload.get("package_size_bytes", payload.get("package_size"))
    source_name = str(payload.get("source_name", "腾讯云更新服务")).strip() or "腾讯云更新服务"
    if used_anonymous_fallback:
        source_name = f"{source_name} (匿名回退)"

    if not remote_version:
        raise RuntimeError("国内启动器更新服务返回字段缺失")

    return {
        "remote_version": remote_version,
        "package_url": package_url,
        "package_sha256": package_sha256,
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

    local_version = _read_local_app_version(_app_runtime_dir(base))
    source_mode = _normalize_download_source_mode(download_source_mode)

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
    source_mode = _normalize_download_source_mode(download_source_mode)
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


class UpdateService:
    """Coordinates manifest resolution, update checks, and download operations."""

    def __init__(
        self,
        base: Path,
        channel: str,
        identity: Dict[str, str],
        download_source_mode: str = DOWNLOAD_SOURCE_MODE_AUTO,
        status_cb: Optional[Callable[[str, str, Optional[float], str], None]] = None,
        cancel_cb: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.base = base
        self.channel = channel
        self.identity = identity
        self.download_source_mode = download_source_mode
        self.status_cb = status_cb
        self.cancel_cb = cancel_cb

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
        return _resolve_update_manifest(
            self.base,
            self.channel,
            self.identity,
            download_source_mode=self.download_source_mode,
            status_cb=self.notify,
        )

    def resolve_launcher_manifest(self) -> Dict[str, Any]:
        return _resolve_launcher_update_manifest(
            self.base,
            self.identity,
            download_source_mode=self.download_source_mode,
            status_cb=self.notify,
        )

    def check(self) -> Dict[str, Any]:
        local_version, manifest = self.resolve_app_manifest()
        remote_version = str(manifest.get("remote_version", "")).strip()
        min_launcher_version = str(manifest.get("min_launcher_version", "")).strip()
        package_url = str(manifest.get("package_url", "")).strip()
        source_name = str(manifest.get("source_name", "GitHub")).strip() or "GitHub"
        if not remote_version:
            raise RuntimeError("更新清单字段缺失")

        update_available = _version_is_newer(remote_version, local_version)
        app_requires_launcher_update = bool(
            update_available
            and min_launcher_version
            and _version_is_older(LAUNCHER_VERSION, min_launcher_version)
        )
        if update_available and not package_url:
            raise RuntimeError("更新清单字段缺失")

        package_size = self._manifest_package_size(manifest)
        if update_available and package_size is None and package_url:
            package_size = _fetch_content_length(package_url, timeout_sec=NET_TIMEOUT_SEC)

        launcher_manifest = self.resolve_launcher_manifest()
        launcher_remote_version = str(launcher_manifest.get("remote_version", "")).strip()
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

        return {
            "local_version": local_version,
            "remote_version": remote_version,
            "min_launcher_version": min_launcher_version,
            "source_name": source_name,
            "update_available": update_available,
            "app_requires_launcher_update": app_requires_launcher_update,
            "package_size": package_size,
            "manifest": manifest,
            "launcher_manifest": launcher_manifest,
            "launcher_remote_version": launcher_remote_version,
            "launcher_source_name": launcher_source_name,
            "launcher_update_available": launcher_update_available,
            "launcher_package_size": launcher_package_size,
        }

    def download_app_update(self, manifest: Dict[str, Any]) -> Tuple[str, str]:
        return _download_update_from_manifest(
            self.base,
            manifest,
            status_cb=self.notify,
            cancel_cb=self.cancel_cb,
        )

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
    min_launcher_version = str(manifest.get("min_launcher_version", "")).strip()
    package_url = str(manifest.get("package_url", "")).strip()
    package_sha256 = _require_remote_checksum(
        manifest.get("package_sha256", ""),
        artifact_label="应用更新清单 ",
    )
    entrypoint = str(manifest.get("entrypoint", DEFAULT_ENTRYPOINT)).strip() or DEFAULT_ENTRYPOINT
    source_name = str(manifest.get("source_name", "GitHub")).strip() or "GitHub"
    if not remote_version or not package_url:
        raise RuntimeError("更新清单字段缺失")
    package_sha256 = _require_remote_checksum(
        package_sha256,
        artifact_label="应用更新清单",
    )
    if min_launcher_version and _version_is_older(LAUNCHER_VERSION, min_launcher_version):
        raise RuntimeError(
            f"此版本要求先更新启动器（当前 v{LAUNCHER_VERSION}，要求 >= v{min_launcher_version}）"
        )

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

    package_bytes = _fetch_bytes(package_url, progress_cb=on_progress, cancel_cb=cancel_cb)
    if cancel_cb and cancel_cb():
        raise RuntimeError("已取消当前操作")
    _install_zip_package(
        base,
        package_bytes,
        package_sha256,
        entrypoint,
        status_cb=notify,
        cancel_cb=cancel_cb,
    )
    notify("更新完成", f"已更新到 v{remote_version}", 1.0, "success")
    return remote_version, source_name


def _launch_updater_script(script_path: Path) -> None:
    creation_flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creation_flags |= subprocess.CREATE_NO_WINDOW
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creation_flags |= subprocess.DETACHED_PROCESS
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        cwd=str(script_path.parent),
        close_fds=True,
        creationflags=creation_flags,
    )


def _stage_launcher_self_update(
    base: Path,
    launcher_bytes: bytes,
    remote_version: str,
) -> None:
    if not _is_frozen_launcher():
        raise RuntimeError("源码模式不支持启动器自更新")

    target = Path(sys.executable).resolve()
    work_dir = Path(tempfile.mkdtemp(prefix=LAUNCHER_SELF_UPDATE_WORKDIR_PREFIX))
    staged = work_dir / f"{target.stem}.update.new{target.suffix}"
    backup = target.with_name(f"{target.stem}.bomana_backup_{os.getpid()}{target.suffix}")
    script_path = work_dir / "bomana_update_launcher_apply.ps1"
    result_path = base / LAUNCHER_UPDATE_RESULT_FILE_NAME

    try:
        result_path.unlink(missing_ok=True)
        staged.write_bytes(launcher_bytes)
        _log(base, f"已在临时目录准备启动器自更新文件：{staged}")
        script = f"""$ErrorActionPreference = 'Stop'
$target = {json.dumps(str(target))}
$staged = {json.dumps(str(staged))}
$backup = {json.dumps(str(backup))}
$resultPath = {json.dumps(str(result_path))}
$oldPid = {os.getpid()}
$targetVersion = {json.dumps(str(remote_version))}

function Write-Result([string]$status, [string]$message) {{
    $payload = [ordered]@{{
        status = $status
        target_version = $targetVersion
        message = $message
        updated_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    }}
    $payload | ConvertTo-Json -Compress | Set-Content -LiteralPath $resultPath -Encoding UTF8
}}

try {{
    for ($i = 0; $i -lt 120; $i++) {{
        if (-not (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {{
            break
        }}
        Start-Sleep -Seconds 1
    }}

    Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $target) {{
        Move-Item -LiteralPath $target -Destination $backup -Force
    }}
    if (-not (Test-Path -LiteralPath $staged)) {{
        throw "staged launcher file missing"
    }}
    Move-Item -LiteralPath $staged -Destination $target -Force
    if (-not (Test-Path -LiteralPath $target)) {{
        throw "launcher target missing after replace"
    }}
    Start-Process -FilePath $target | Out-Null
    Write-Result "success" ("Launcher replaced and restarted: " + $targetVersion)
    Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
}}
catch {{
    $detail = ($_ | Out-String).Trim()
    if ((-not (Test-Path -LiteralPath $target)) -and (Test-Path -LiteralPath $backup)) {{
        Move-Item -LiteralPath $backup -Destination $target -Force -ErrorAction SilentlyContinue
    }}
    Write-Result "error" $detail
    exit 1
}}
finally {{
    Start-Sleep -Milliseconds 500
    Remove-Item -LiteralPath $staged -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
}}
"""
        script_path.write_text(script, encoding="utf-8")
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

    launcher_bytes = _fetch_bytes(package_url, progress_cb=on_progress, cancel_cb=cancel_cb)
    if cancel_cb and cancel_cb():
        raise RuntimeError("已取消当前操作")
    actual_sha256 = hashlib.sha256(launcher_bytes).hexdigest().lower()
    if actual_sha256 != package_sha256:
        raise RuntimeError("SHA256 校验失败")
    current_name = Path(sys.executable).name
    notify(
        "准备替换启动器",
        f"新版启动器文件已下载完成；关闭当前窗口后会替换 {current_name} 并自动重启。",
        0.9,
        "info",
    )
    _stage_launcher_self_update(base, launcher_bytes, remote_version)
    notify(
        "启动器更新已就绪",
        f"已准备好升级到 v{remote_version}；关闭当前窗口后会用新版启动器文件替换当前 exe 并自动重启。",
        1.0,
        "success",
    )
    return remote_version, source_name


def _source_site_packages(base: Path) -> Tuple[Path, ...]:
    venv_dir = base / ".venv"
    version_tag = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates = (
        venv_dir / "Lib" / "site-packages",
        venv_dir / "lib" / version_tag / "site-packages",
        venv_dir / "lib" / "site-packages",
    )
    return tuple(path for path in candidates if path.exists())


def _prepare_source_test_runtime(base: Path) -> None:
    for site_packages in reversed(_source_site_packages(base)):
        site_text = str(site_packages)
        if site_text not in sys.path:
            sys.path.insert(0, site_text)


def _reset_embedded_app_modules() -> None:
    """Clear launcher-bundled bomana modules before handing off to the app package."""
    stale_modules = [
        name for name in tuple(sys.modules.keys()) if name == "bomana" or name.startswith("bomana.")
    ]
    for name in stale_modules:
        sys.modules.pop(name, None)
    importlib.invalidate_caches()


def _launch_app(base: Path, channel: str) -> None:
    _recover_incomplete_install(base)
    app_dir = _app_runtime_dir(base)
    entry = app_dir / DEFAULT_ENTRYPOINT
    if not entry.exists():
        raise RuntimeError("本地应用不存在，请联网后重试。")

    if _is_source_test_run(base):
        _prepare_source_test_runtime(base)
    _reset_embedded_app_modules()
    os.environ["BOMANA_CHANNEL"] = channel
    os.environ["BOMANA_RUNTIME_ROOT"] = str(app_dir)
    os.chdir(app_dir)
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    runpy.run_path(str(entry), run_name="__main__")


def _friendly_error_text(err: Exception, channel: str) -> str:
    msg = str(err)
    if "已取消" in msg:
        return "已取消当前操作。"
    if "要求先更新启动器" in msg:
        return f"{msg}。请先更新启动器后再安装 {channel} 通道的新版本。"
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
    ):
        super().__init__(parent)
        self.title("关于 Bomana")
        self.configure(bg=_THEME["BG"])
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()
        _apply_window_icon(self)
        self._images: list = []

        self._build_ui(channel, local_version, launcher_version, install_dir)
        self._fit_window_to_parent(parent)
        self._center_on_parent(parent)

    def _build_ui(
        self, channel: str, local_version: str, launcher_version: str, install_dir: Path
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

        info_text = (
            f"当前通道：{channel}\n"
            f"本地版本：v{local_version}\n"
            f"安装目录：{install_dir}\n"
            f"启动器版本：v{launcher_version}"
        )
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


class LauncherWindow:
    """Simple, user-friendly GUI for launcher status and recovery actions."""

    def __init__(self, base: Path, channel: str):
        self.base = base
        self.source_test_mode = _is_source_test_run(base)
        self.saved_state = _read_state(base)
        self.channel = channel
        self.detected_channel = channel
        self.download_source_mode = _normalize_download_source_mode(
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
        _set_use_system_proxy(self.use_system_proxy)
        self.client_identity = _build_client_identity(base)
        self.local_version = _read_local_app_version(_app_runtime_dir(base))
        self.previous_version = _read_local_app_version(_previous_app_dir(base))
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
        self.latest_launcher_manifest: Optional[Dict[str, Any]] = None
        self.latest_launcher_version = LAUNCHER_VERSION
        self.latest_launcher_source_name = ""
        self.latest_launcher_package_size: Optional[int] = None
        self.launcher_update_available = False
        self.last_check_ok = False
        self.last_check_error = ""
        self.install_dir = _app_runtime_dir(self.base)
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
        self._base_min_w = self._px(760)
        self._base_min_h = self._px(520)
        self._max_w = self._base_min_w
        self._max_h = self._base_min_h
        self._min_w = self._base_min_w
        self._min_h = self._base_min_h

        self.root = tk.Tk()
        self.root.title(DISPLAY_NAME)
        _apply_window_icon(self.root)
        self._init_window_scale_context()
        self.root.geometry(f"{self._px(760)}x{self._px(520)}")
        self.root.resizable(True, True)
        self.root.configure(bg=_THEME["BG"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_exit)
        self.channel_var = tk.StringVar(master=self.root, value=channel)
        self.proxy_var = tk.BooleanVar(master=self.root, value=self.use_system_proxy)
        self.download_source_var = tk.StringVar(
            master=self.root,
            value=_download_source_label(self.download_source_mode),
        )

        self._build_ui()
        self._fit_window_to_screen()
        self.root.bind("<Configure>", self._on_window_configure, add="+")
        self._refresh_wraplengths()
        self._schedule_layout_reflow()
        if self.source_test_mode:
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
            content_w = max(self._px(300), win_w - self._px(354))
            if hasattr(self, "selection_summary_lbl"):
                self.selection_summary_lbl.config(wraplength=max(self._px(220), win_w // 3))
            if hasattr(self, "rollback_status_lbl"):
                self.rollback_status_lbl.config(wraplength=max(self._px(190), win_w // 3))
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
            text="WAR THUNDER FIELD CONSOLE",
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
            text=f"启动器 v{LAUNCHER_VERSION}  |  最低兼容应用包 v{MIN_SUPPORTED_APP_VERSION}+",
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

        self.sub_lbl = tk.Label(
            top,
            text=self._subline_text(),
            font=self._font(10),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["BG"],
            anchor="w",
        )
        self.sub_lbl.pack(fill="x", padx=self._px(18), pady=(0, self._px(12)))

        content_row = tk.Frame(top, bg=_THEME["BG"])
        content_row.pack(
            fill="both",
            expand=True,
            padx=self._px(18),
            pady=(0, self._px(12)),
        )
        content_row.grid_columnconfigure(0, weight=0, minsize=self._px(258))
        content_row.grid_columnconfigure(1, weight=1)
        content_row.grid_rowconfigure(0, weight=1)

        controls_card = tk.Frame(
            content_row,
            bg=_THEME["CARD_ALT"],
            highlightthickness=1,
            highlightbackground=_THEME["BORDER"],
        )
        controls_card.grid(row=0, column=0, sticky="nsew", padx=(0, self._px(12)))

        controls_head = tk.Frame(controls_card, bg=_THEME["CARD_ALT"])
        controls_head.pack(fill="x", padx=self._px(12), pady=(self._px(12), self._px(8)))
        tk.Label(
            controls_head,
            text="部署配置",
            font=self._font(10, "bold"),
            fg=_THEME["TEXT"],
            bg=_THEME["CARD_ALT"],
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            controls_head,
            text="通道、下载源与代理",
            font=self._font(8),
            fg=_THEME["TEXT_MUTED"],
            bg=_THEME["CARD_ALT"],
            anchor="w",
        ).pack(anchor="w", pady=(self._px(2), 0))

        picker_row = tk.Frame(controls_card, bg=_THEME["CARD_ALT"])
        picker_row.pack(fill="x", padx=self._px(12), pady=(0, self._px(10)))

        channel_cluster = tk.Frame(picker_row, bg=_THEME["CARD_ALT"])
        channel_cluster.pack(fill="x", pady=(0, self._px(10)))
        tk.Label(
            channel_cluster,
            text="通道",
            font=self._font(9, "bold"),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["CARD_ALT"],
        ).pack(anchor="w")

        self.channel_menu = tk.OptionMenu(
            channel_cluster, self.channel_var, "Enhanced", "Standard", "Lite"
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
        self.channel_menu.pack(anchor="w", pady=(self._px(5), 0))

        source_cluster = tk.Frame(picker_row, bg=_THEME["CARD_ALT"])
        source_cluster.pack(fill="x", pady=(0, self._px(10)))
        tk.Label(
            source_cluster,
            text="来源",
            font=self._font(9, "bold"),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["CARD_ALT"],
        ).pack(anchor="w")

        source_choices = [label for _mode, label in DOWNLOAD_SOURCE_CHOICES]
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
            width=20,
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
        self.download_source_menu.pack(anchor="w", pady=(self._px(5), 0))

        self.proxy_chk = tk.Checkbutton(
            picker_row,
            text="使用系统代理",
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
        self.proxy_chk.pack(anchor="w", pady=(0, self._px(4)))

        self.selection_summary_lbl = tk.Label(
            controls_card,
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
            pady=(self._px(2), self._px(12)),
        )

        rollback_card = tk.Frame(
            controls_card,
            bg=_THEME["CARD"],
            highlightthickness=1,
            highlightbackground=_THEME["SEPARATOR"],
        )
        rollback_card.pack(
            fill="x",
            padx=self._px(12),
            pady=(0, self._px(12)),
        )
        tk.Label(
            rollback_card,
            text="版本回退",
            font=self._font(10, "bold"),
            fg=_THEME["TEXT"],
            bg=_THEME["CARD"],
            anchor="w",
        ).pack(fill="x", padx=self._px(10), pady=(self._px(9), self._px(2)))

        self.rollback_status_lbl = tk.Label(
            rollback_card,
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
            rollback_card,
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
        self._refresh_channel_details()
        self._refresh_download_source_details()

        card = tk.Frame(
            content_row,
            bg=_THEME["CARD"],
            highlightthickness=1,
            highlightbackground=_THEME["BORDER"],
        )
        card.grid(row=0, column=1, sticky="nsew")

        status_header = tk.Frame(card, bg=_THEME["CARD"])
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
            card,
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
            card,
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
            card,
            text="首次使用请先下载应用包；后续更新会自动保留一个上一版本供回退。",
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

        self.import_btn = tk.Button(
            btn_row,
            text="导入本地包",
            width=11,
            command=self._on_import_zip,
            cursor="hand2",
            font=self._font(10),
            padx=self._px(6),
            pady=self._px(3),
        )
        self.import_btn.pack(side="right", padx=(0, self._px(8)))
        self._style_action_button(self.import_btn, "secondary")

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
        self.latest_launcher_manifest = None
        self.latest_launcher_package_size = None
        self.launcher_update_available = False
        self.last_check_ok = False
        self.last_check_error = ""
        self.channel = self.channel_var.get().strip() or self.detected_channel
        self._refresh_installed_versions()
        if automatic:
            self._set_status(
                "自动检查更新",
                f"正在检查 {self.channel} 通道，并同步检查启动器版本...",
                None,
                "info",
            )
        else:
            self._set_status("正在检查更新", f"正在重新检查 {self.channel} 通道...", None, "info")
        self._set_running(True)
        self._start_worker("check")

    def _worker_main(self, task: str) -> None:
        service = UpdateService(
            self.base,
            self.channel,
            self.client_identity,
            download_source_mode=self.download_source_mode,
            status_cb=self._emit_status,
            cancel_cb=lambda: self._cancel_requested.is_set(),
        )
        if task == "check":
            try:
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
                            "已准备好下载并接管新版启动器；当前窗口关闭后会自动替换当前 exe 并重启。"
                            if update_ok
                            else update_error
                        ),
                        "level": ("success" if update_ok else "warning"),
                    },
                )
            )
            return
        if task == "rollback":
            final_version = _read_local_app_version(_app_runtime_dir(self.base))
            preserved_version = _read_local_app_version(_previous_app_dir(self.base))
            update_ok = False
            detail = ""
            try:
                final_version, preserved_version = _rollback_to_previous_app(
                    self.base,
                    status_cb=self._emit_status,
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
            final_version = _read_local_app_version(_app_runtime_dir(self.base))
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
                package_bytes = zip_file.read_bytes()
                _install_zip_package(
                    self.base,
                    package_bytes,
                    expected_sha256="",
                    entrypoint=DEFAULT_ENTRYPOINT,
                    status_cb=self._emit_status,
                    cancel_cb=lambda: self._cancel_requested.is_set(),
                )
                final_version = _read_local_app_version(_app_runtime_dir(self.base))
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
                                    f"；已保留上一版本 v{_read_local_app_version(_previous_app_dir(self.base))}"
                                    if _is_previous_app_ready(self.base)
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

        final_version = _read_local_app_version(_app_runtime_dir(self.base))
        update_ok = False
        update_source = ""
        update_error = ""
        local_ready = _is_local_app_ready(self.base)
        manifest = dict(self.latest_manifest or {})
        try:
            if not manifest:
                raise RuntimeError("请先完成更新检查")
            final_version, update_source = service.download_app_update(manifest)
            update_ok = True
            local_ready = _is_local_app_ready(self.base)
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
                "device_id": self.client_identity.get("device_id", ""),
                "install_id": self.client_identity.get("install_id", ""),
            }
        )

        if update_ok:
            self.events.put(
                (
                    "download_done",
                    {
                        "update_ok": True,
                        "final_version": final_version,
                        "warning": "",
                        "status": "下载完成",
                        "detail": (
                            f"已更新到 v{final_version}（来源：{update_source}）。现在可点击“启动应用”。\n"
                            f"安装位置：{self.install_dir}"
                            + (
                                f"\n已保留上一版本 v{_read_local_app_version(_previous_app_dir(self.base))}，可随时回退。"
                                if _is_previous_app_ready(self.base)
                                else ""
                            )
                        ),
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
                        self.launcher_update_available = bool(
                            payload.get("launcher_update_available", False)
                        )

                        if self.app_requires_launcher_update:
                            detail = self._compose_check_detail()
                            self._set_status("需要先更新启动器", detail, 0.0, "warning")
                        elif self.update_available:
                            detail = self._compose_check_detail()
                            self._set_status("发现新版本", detail, 0.0, "success")
                        elif self.launcher_update_available:
                            detail = self._compose_check_detail()
                            self._set_status("检测到启动器更新", detail, 0.0, "success")
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
                        self.latest_launcher_manifest = None
                        self.latest_launcher_package_size = None
                        self.latest_launcher_source_name = ""
                        self.launcher_update_available = False
                        self.last_check_error = str(payload.get("error", "检查失败"))
                        self._set_status("检查失败", self.last_check_error, 0.0, "warning")
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
                    self.decision = LaunchDecision(
                        action="exit",
                        final_version=final_version,
                        warning=warning,
                    )
                    self._set_status(
                        str(payload.get("status", "")),
                        str(payload.get("detail", "")),
                        self.progress_value,
                        str(payload.get("level", "info")),
                    )
                    self._refresh_installed_versions()
                    self.current_task = ""
                    if bool(payload.get("update_ok", False)):
                        self.update_available = False
                        self.app_requires_launcher_update = False
                        self.latest_min_launcher_version = ""
                        self.latest_package_size = None
                        self.last_check_ok = True
                        self.last_download_success = True
                    else:
                        self.last_download_success = False
                    self._set_running(False)
                    if self._exit_after_task:
                        self._finalize_exit()
                        continue
                    if not bool(payload.get("update_ok", False)):
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
        if self.launcher_update_available:
            launcher_size_text = _format_size_text(self.latest_launcher_package_size)
            lines.append(
                f"启动器 v{LAUNCHER_VERSION} -> v{self.latest_launcher_version}（来源：{self.latest_launcher_source_name}，大小：{launcher_size_text}）"
            )
        return "\n".join(line for line in lines if line)

    def _subline_text(self) -> str:
        base = f"通道：{self.channel}  |  本地版本：v{self.local_version}"
        if self.previous_version != "0.0.0":
            return f"{base}  |  可回退：v{self.previous_version}"
        return base

    def _rollback_status_text(self) -> str:
        if self.source_test_mode:
            return "源码模式不会写入 app/ 安装槽，因此不提供版本回退。"
        if self.previous_version != "0.0.0":
            return (
                f"上一版本 v{self.previous_version} 已保留。回退会与当前 v{self.local_version} "
                "对调，可再次切回。"
            )
        return "更新或导入本地包后，会自动保留一个上一版本用于快速回退。"

    def _refresh_installed_versions(self) -> None:
        self.local_version = _read_local_app_version(_app_runtime_dir(self.base))
        self.previous_version = _read_local_app_version(_previous_app_dir(self.base))
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
            self._style_action_button(self.launch_btn, "secondary")
            return
        if self.last_download_success:
            self.launch_btn.config(text="启动（已下载更新）")
            self._style_action_button(self.launch_btn, "success")
            return
        if self.last_check_ok and not self.update_available:
            self.launch_btn.config(text="启动应用")
            self._style_action_button(self.launch_btn, "secondary")
            return
        if self.last_check_ok and self.update_available:
            self.launch_btn.config(text="启动本地（跳过更新）")
            self._style_action_button(self.launch_btn, "secondary")
            return
        self.launch_btn.config(text="启动应用（本地）")
        self._style_action_button(self.launch_btn, "secondary")

    def _update_download_button_state(self) -> None:
        if self.source_test_mode:
            self.start_btn.config(text="源码模式不下载")
            self._style_action_button(self.start_btn, "secondary")
            return
        if self.last_check_ok and self.update_available and self.app_requires_launcher_update:
            self.start_btn.config(text="需先更新启动器")
            self._style_action_button(self.start_btn, "secondary")
            return
        self.start_btn.config(text="下载更新")
        self._style_action_button(
            self.start_btn,
            "primary" if (self.last_check_ok and self.update_available) else "secondary",
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
        if self.previous_version != "0.0.0":
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
        if running and self.current_task == "check" and _is_local_app_ready(self.base):
            # Allow launching local app immediately while background check continues.
            self.launch_btn.config(state="normal")
        else:
            self.launch_btn.config(state=state)
        self.release_btn.config(state="normal")
        self.import_btn.config(state=("disabled" if self.source_test_mode else "normal"))
        self.details_btn.config(state="normal")
        self.exit_btn.config(state="normal")
        self.rollback_btn.config(state=("disabled" if running else self.rollback_btn.cget("state")))
        self.channel_menu.config(
            state=("normal" if running and self.current_task == "check" else state)
        )
        self.download_source_menu.config(
            state=("normal" if (not running or self.current_task == "check") else "disabled")
        )
        if hasattr(self, "proxy_chk"):
            self.proxy_chk.config(
                state=("normal" if running and self.current_task == "check" else state)
            )

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
                and self.update_available
                and (not self.app_requires_launcher_update)
            ):
                self.start_btn.config(state="normal")
            else:
                self.start_btn.config(state="disabled")
            if _is_local_app_ready(self.base):
                self.launch_btn.config(state="normal")
            else:
                self.launch_btn.config(state="disabled")
            if self.source_test_mode:
                self.hint_lbl.config(
                    text=(
                        "当前处于源码测试模式：launcher.pyw 将直接启动同目录 Bomana.pyw，"
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
                size_text = _format_size_text(self.latest_package_size)
                self.hint_lbl.config(
                    text=(
                        f"可下载 v{self.latest_remote_version}（总大小：{size_text}）。点击“下载更新”会再次确认。\n"
                        f"安装位置：{self.install_dir}"
                    )
                )
                if self.launcher_update_available:
                    self.hint_lbl.config(
                        text=(
                            f"{self.hint_lbl.cget('text')}\n"
                            f"同时检测到启动器 v{self.latest_launcher_version} 可更新，可单独点击“更新启动器”。"
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
            elif self.last_check_ok and not self.update_available:
                if _is_local_app_ready(self.base):
                    self.hint_lbl.config(
                        text=f"当前已是最新版本，可直接点击“启动应用”。\n安装位置：{self.install_dir}"
                    )
                else:
                    self.hint_lbl.config(text="当前设备没有本地版本，请等待在线更新可用后下载。")
            elif self.last_check_error:
                if _is_local_app_ready(self.base):
                    self.hint_lbl.config(
                        text="自动检查失败，可点击“重新检查”，或先点击“启动应用”使用本地版本。"
                    )
                else:
                    self.hint_lbl.config(
                        text="自动检查失败，且当前没有本地版本。请点击“重新检查”或“打开下载页”。"
                    )
            else:
                self.hint_lbl.config(text="启动后会自动检查更新。")
            if (not self.source_test_mode) and self.previous_version != "0.0.0":
                self.hint_lbl.config(
                    text=f"{self.hint_lbl.cget('text')}\n可通过“回退 v{self.previous_version}”快速切回上一版。"
                )
        self._schedule_layout_reflow()

    def _show_error_actions(self) -> None:
        if _is_local_app_ready(self.base):
            text = "可点击“重新检查”或“打开下载页”。也可直接点击“启动应用”。"
            if self.previous_version != "0.0.0":
                text += f"\n如果新版异常，也可以点击“回退 v{self.previous_version}”。"
            self.hint_lbl.config(text=text)
        else:
            self.hint_lbl.config(text="可点击“重新检查”或“打开下载页”。首次使用请先完成下载。")
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
        _write_state(self.base, state)

    def _on_proxy_changed(self) -> None:
        if self.running and self.current_task != "check":
            self.proxy_var.set(bool(self.use_system_proxy))
            return
        self.use_system_proxy = bool(self.proxy_var.get())
        _set_use_system_proxy(self.use_system_proxy)
        self._save_launcher_state()
        mode = "系统代理" if self.use_system_proxy else "直连模式"
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

    def _on_download_source_changed(self, *_args) -> None:
        new_mode = _DOWNLOAD_SOURCE_LABEL_TO_MODE.get(
            self.download_source_var.get(),
            DOWNLOAD_SOURCE_MODE_AUTO,
        )
        if self.running and self.current_task != "check":
            self.download_source_var.set(_download_source_label(self.download_source_mode))
            return
        new_mode = _normalize_download_source_mode(new_mode)
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
        if not self.update_available:
            messagebox.showinfo(DISPLAY_NAME, "当前已是最新版本，无需下载。")
            return
        if not self.latest_manifest:
            messagebox.showwarning(DISPLAY_NAME, "缺少下载清单，请先点击“重新检查”。")
            return
        size_text = _format_size_text(self.latest_package_size)
        ok = messagebox.askyesno(
            DISPLAY_NAME,
            (
                f"将下载并安装 v{self.latest_remote_version}。\n"
                f"下载总大小：{size_text}\n"
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
            f"即将下载 v{self.latest_remote_version}，总大小：{size_text}\n安装位置：{self.install_dir}",
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
        if self.previous_version == "0.0.0" or not _is_previous_app_ready(self.base):
            messagebox.showinfo(DISPLAY_NAME, "当前没有可回退的上一版本。")
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
        if self.running and self.current_task != "check":
            self.channel_var.set(self.channel)
            return
        self.channel = self.channel_var.get().strip() or self.detected_channel
        self._save_launcher_state()
        self._refresh_installed_versions()
        self._refresh_channel_details()
        if self.running and self.current_task == "check":
            self._queue_recheck_after_check(
                f"通道已切换到 {self.channel}，当前检查结束后将自动重查。"
            )
            return
        self._begin_check(automatic=True)

    def _refresh_channel_details(self) -> None:
        ch = self.channel_var.get().strip() or self.detected_channel
        info = CHANNEL_DETAILS.get(ch, CHANNEL_DETAILS["Enhanced"])
        label = _download_source_label(self.download_source_mode)
        source_detail = DOWNLOAD_SOURCE_DETAILS.get(
            self.download_source_mode,
            DOWNLOAD_SOURCE_DETAILS[DOWNLOAD_SOURCE_MODE_AUTO],
        )
        self.selection_summary_lbl.config(
            text=(
                f"{info['title']}  |  推荐：{self.detected_channel}  |  来源：{label}\n"
                f"{info['desc']} {source_detail}"
            )
        )
        self._refresh_wraplengths()

    def _refresh_download_source_details(self) -> None:
        self._refresh_channel_details()

    def _on_launch(self) -> None:
        if not _is_local_app_ready(self.base):
            detail = (
                "同目录源码入口缺失，请确认 Bomana.pyw 存在。"
                if self.source_test_mode
                else "本地没有可用应用包，请先点击“下载更新”。"
            )
            self._set_status("无法启动", detail, None, "error")
            return
        final_version = _read_local_app_version(_app_runtime_dir(self.base))
        self.decision = LaunchDecision(action="launch", final_version=final_version, warning="")
        self._set_status("准备启动", f"将启动本地版本 v{final_version}", 1.0, "success")
        self.root.after(300, self._commit_launch)

    def _open_releases(self) -> None:
        try:
            webbrowser.open(RELEASES_URL)
        except Exception:
            pass

    def _open_details(self) -> None:
        try:
            LauncherDetailsDialog(
                self.root,
                channel=self.channel,
                local_version=self.local_version,
                launcher_version=LAUNCHER_VERSION,
                install_dir=self.install_dir,
            )
        except Exception as e:
            _log(self.base, f"打开详情弹窗失败：{e}")

    def _commit_launch(self) -> None:
        if self.decision.action == "launch":
            self.root.destroy()

    def _finalize_exit(self) -> None:
        self._exit_after_task = False
        self.decision = LaunchDecision(
            action="exit",
            final_version=_read_local_app_version(_app_runtime_dir(self.base)),
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
    _recover_incomplete_install(base)
    _cleanup_temp_files_on_launcher_upgrade(base)
    _cleanup_stale_launcher_self_update_temp(base)
    _cleanup_legacy_launcher_self_update_files(base)
    _consume_launcher_update_result(base)
    Win32.enable_dpi()
    channel = _detect_channel()
    identity = _build_client_identity(base)

    gui = LauncherWindow(base, channel)
    decision = gui.run()
    if decision.action != "launch":
        return

    selected_channel = gui.channel

    threading.Thread(
        target=_report_primary_event,
        args=(base, identity, "app_launch", selected_channel, decision.final_version),
        daemon=True,
    ).start()

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
