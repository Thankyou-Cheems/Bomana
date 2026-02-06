# -*- coding: utf-8 -*-
"""Bomana portable launcher with user-friendly GUI update flow."""

import hashlib
import json
import os
import queue
import re
import runpy
import shutil
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import tkinter as tk
from tkinter import messagebox

# Launcher metadata
LAUNCHER_VERSION = "1.1.0"
DISPLAY_NAME = "Bomana香焦"
REPO_OWNER = "Thankyou-Cheems"
REPO_NAME = "Bomana"
DEFAULT_CHANNEL = "Enhanced"
APP_DIR_NAME = "app"
STATE_FILE_NAME = "launcher_state.json"
LOG_FILE_NAME = "launcher.log"
INSTALL_ID_FILE_NAME = ".bomana_install_id"
DEFAULT_ENTRYPOINT = "Bomana.pyw"
NET_TIMEOUT_SEC = 8.0
PRIMARY_TIMEOUT_SEC = 4.0
UA = f"BomanaLauncher/{LAUNCHER_VERSION}"
PRIMARY_UPDATE_BASE_URL = os.environ.get("BOMANA_UPDATE_BASE_URL", "https://bomanaupdate.007985.xyz").strip().rstrip("/")
PRIMARY_VERSION_API_PATH = "/api/v1/version"
PRIMARY_EVENT_API_PATH = "/api/v1/event"

RELEASES_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/latest"

_CHANNEL_MAP = {
    "enhanced": "Enhanced",
    "standard": "Standard",
    "lite": "Lite",
}

_THEME = {
    "BG": "#0a0e13",
    "CARD": "#161b22",
    "BORDER": "#30363d",
    "TEXT": "#e6edf3",
    "TEXT_DIM": "#8b949e",
    "TEXT_MUTED": "#484f58",
    "BLUE": "#58a6ff",
    "GREEN": "#3fb950",
    "YELLOW": "#d29922",
    "RED": "#f85149",
}

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


@dataclass
class LaunchDecision:
    action: str  # "launch" | "exit"
    final_version: str
    warning: str = ""


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


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
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, msg)
        root.destroy()
    except tk.TclError:
        pass


def _fetch_bytes(
    url: str,
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
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
    with urlopen(req, timeout=(timeout_sec if timeout_sec is not None else NET_TIMEOUT_SEC)) as resp:
        total: Optional[int] = None
        try:
            header = resp.headers.get("Content-Length")
            total = int(header) if header else None
        except Exception:
            total = None

        chunks = []
        downloaded = 0
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            downloaded += len(chunk)
            if progress_cb:
                progress_cb(downloaded, total)

        if progress_cb:
            progress_cb(downloaded, total)
        return b"".join(chunks)


def _fetch_json(url: str) -> Dict[str, Any]:
    raw = _fetch_bytes(url)
    return json.loads(raw.decode("utf-8"))


def _fetch_json_with_timeout(url: str, timeout_sec: float) -> Dict[str, Any]:
    raw = _fetch_bytes(url, timeout_sec=timeout_sec)
    return json.loads(raw.decode("utf-8"))


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
    with urlopen(req, timeout=timeout_sec) as resp:
        data = resp.read()
    if not data:
        return {}
    return json.loads(data.decode("utf-8"))


def _detect_channel() -> str:
    env = os.environ.get("BOMANA_CHANNEL", "").strip().lower()
    if env in _CHANNEL_MAP:
        return _CHANNEL_MAP[env]

    exe_name = (Path(sys.executable).name if getattr(sys, "frozen", False) else Path(__file__).name).lower()
    for key, value in _CHANNEL_MAP.items():
        if key in exe_name:
            return value
    return DEFAULT_CHANNEL


def _extract_version_tuple(version: str) -> Tuple[int, ...]:
    nums = re.findall(r"\d+", version or "")
    if not nums:
        return (0,)
    return tuple(int(x) for x in nums)


def _version_is_newer(remote: str, local: str) -> bool:
    a = _extract_version_tuple(remote)
    b = _extract_version_tuple(local)
    n = max(len(a), len(b))
    aa = a + (0,) * (n - len(a))
    bb = b + (0,) * (n - len(b))
    return aa > bb


def _read_local_app_version(app_dir: Path) -> str:
    cfg = app_dir / "bomana" / "config.py"
    if not cfg.exists():
        return "0.0.0"
    try:
        text = cfg.read_text(encoding="utf-8")
        m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
        if m:
            return m.group(1).strip()
    except Exception:
        return "0.0.0"
    return "0.0.0"


def _is_local_app_ready(base: Path) -> bool:
    return (base / APP_DIR_NAME / DEFAULT_ENTRYPOINT).exists()


def _write_state(base: Path, state: Dict[str, Any]) -> None:
    path = base / STATE_FILE_NAME
    try:
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
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


def _find_asset(assets: list, name: str) -> Optional[Dict[str, Any]]:
    for asset in assets:
        if str(asset.get("name", "")).lower() == name.lower():
            return asset
    return None


def _normalize_package_root(stage_dir: Path, entrypoint: str) -> Path:
    if (stage_dir / entrypoint).exists():
        return stage_dir
    children = [p for p in stage_dir.iterdir() if p.is_dir()]
    if len(children) == 1 and (children[0] / entrypoint).exists():
        return children[0]
    return stage_dir


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().lower()


def _safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    target_root = target_dir.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            member_path = (target_dir / member.filename).resolve()
            if target_root not in [member_path] + list(member_path.parents):
                raise RuntimeError("应用包包含非法路径")
        zf.extractall(target_dir)


def _install_zip_package(
    base: Path,
    package_bytes: bytes,
    expected_sha256: str,
    entrypoint: str,
    status_cb: Optional[Callable[[str, str, Optional[float], str], None]] = None,
) -> None:
    expected = (expected_sha256 or "").strip().lower()
    actual = _sha256_bytes(package_bytes)
    if expected and actual != expected:
        raise RuntimeError("应用包 SHA256 校验失败")

    app_dir = base / APP_DIR_NAME
    backup_dir = base / f"{APP_DIR_NAME}_backup"
    work_dir = Path(tempfile.mkdtemp(prefix="bomana_update_", dir=str(base)))
    zip_path = work_dir / "app.zip"
    stage_dir = work_dir / "stage"
    stage_dir.mkdir(parents=True, exist_ok=True)

    try:
        if status_cb:
            status_cb("正在安装更新", "正在解压应用包...", 0.86, "info")
        zip_path.write_bytes(package_bytes)
        _safe_extract_zip(zip_path, stage_dir)

        src_root = _normalize_package_root(stage_dir, entrypoint)
        if not (src_root / entrypoint).exists():
            raise RuntimeError("应用包缺少入口文件 Bomana.pyw")

        if status_cb:
            status_cb("正在安装更新", "正在替换旧版本文件...", 0.94, "info")

        new_dir = base / f"{APP_DIR_NAME}_new"
        if new_dir.exists():
            shutil.rmtree(new_dir, ignore_errors=True)
        shutil.copytree(src_root, new_dir)

        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
        if app_dir.exists():
            os.replace(str(app_dir), str(backup_dir))
        os.replace(str(new_dir), str(app_dir))

        if backup_dir.exists():
            shutil.rmtree(backup_dir, ignore_errors=True)
    except Exception:
        # rollback
        try:
            if app_dir.exists():
                shutil.rmtree(app_dir, ignore_errors=True)
            if backup_dir.exists():
                os.replace(str(backup_dir), str(app_dir))
        except Exception:
            pass
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _latest_release_url() -> str:
    return f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"


def _join_base_url_path(base_url: str, path: str) -> str:
    if not path:
        return base_url
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return f"{base_url}{path}"


def _fetch_manifest_from_github(channel: str) -> Dict[str, str]:
    release = _fetch_json(_latest_release_url())
    assets = release.get("assets", [])

    manifest_name = f"manifest_{channel}.json"
    manifest_asset = _find_asset(assets, manifest_name)
    if not manifest_asset:
        raise RuntimeError(f"未找到发布清单: {manifest_name}")

    manifest_url = str(manifest_asset.get("browser_download_url", "")).strip()
    if not manifest_url:
        raise RuntimeError("发布清单下载地址无效")

    manifest = _fetch_json(manifest_url)
    remote_version = str(manifest.get("app_version", "")).strip()
    package_asset = str(manifest.get("package_asset", "")).strip()
    package_sha256 = str(manifest.get("package_sha256", "")).strip()
    entrypoint = str(manifest.get("entrypoint", DEFAULT_ENTRYPOINT)).strip() or DEFAULT_ENTRYPOINT
    if not remote_version or not package_asset:
        raise RuntimeError("发布清单字段缺失")

    app_asset = _find_asset(assets, package_asset)
    if not app_asset:
        raise RuntimeError(f"未找到应用包: {package_asset}")
    package_url = str(app_asset.get("browser_download_url", "")).strip()
    if not package_url:
        raise RuntimeError("应用包下载地址无效")

    return {
        "remote_version": remote_version,
        "package_url": package_url,
        "package_sha256": package_sha256,
        "entrypoint": entrypoint,
        "source_name": "GitHub",
    }


def _fetch_manifest_from_primary(channel: str, local_version: str, identity: Dict[str, str]) -> Dict[str, str]:
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
    payload = _fetch_json_with_timeout(f"{version_url}?{urlencode(params)}", PRIMARY_TIMEOUT_SEC)
    remote_version = str(payload.get("app_version", "")).strip()
    raw_package_url = str(payload.get("package_url", "")).strip()
    package_url = _join_base_url_path(PRIMARY_UPDATE_BASE_URL, raw_package_url) if raw_package_url else ""
    package_sha256 = str(payload.get("package_sha256", "")).strip()
    entrypoint = str(payload.get("entrypoint", DEFAULT_ENTRYPOINT)).strip() or DEFAULT_ENTRYPOINT
    source_name = str(payload.get("source_name", "腾讯云更新服务")).strip() or "腾讯云更新服务"

    if not remote_version or not package_url:
        raise RuntimeError("国内更新服务返回字段缺失")

    return {
        "remote_version": remote_version,
        "package_url": package_url,
        "package_sha256": package_sha256,
        "entrypoint": entrypoint,
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
    if not PRIMARY_UPDATE_BASE_URL:
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


def _check_and_update(
    base: Path,
    channel: str,
    identity: Dict[str, str],
    status_cb: Optional[Callable[[str, str, Optional[float], str], None]] = None,
) -> Tuple[str, str]:
    def notify(title: str, detail: str = "", progress: Optional[float] = None, level: str = "info") -> None:
        if status_cb:
            status_cb(title, detail, progress, level)

    app_dir = base / APP_DIR_NAME
    local_version = _read_local_app_version(app_dir)
    source_name = "GitHub"

    manifest: Optional[Dict[str, str]] = None
    primary_err: Optional[Exception] = None
    if PRIMARY_UPDATE_BASE_URL:
        notify("正在检查更新", "优先连接腾讯云更新服务...", 0.08, "info")
        try:
            manifest = _fetch_manifest_from_primary(channel, local_version, identity)
        except Exception as e:
            primary_err = e
            _log(base, f"腾讯云更新服务不可用：{e}")
            notify("国内服务暂不可用", "正在切换 GitHub 回退...", 0.1, "warning")

    if manifest is None:
        notify("正在检查更新", "连接 GitHub 获取最新版本信息...", 0.12, "info")
        try:
            manifest = _fetch_manifest_from_github(channel)
        except Exception as e:
            if primary_err is not None:
                raise RuntimeError(f"国内更新服务不可用({primary_err})，GitHub 回退失败({e})") from e
            raise

    remote_version = str(manifest.get("remote_version", "")).strip()
    package_url = str(manifest.get("package_url", "")).strip()
    package_sha256 = str(manifest.get("package_sha256", "")).strip()
    entrypoint = str(manifest.get("entrypoint", DEFAULT_ENTRYPOINT)).strip() or DEFAULT_ENTRYPOINT
    source_name = str(manifest.get("source_name", "GitHub")).strip() or "GitHub"

    if not remote_version or not package_url:
        raise RuntimeError("更新清单字段缺失")

    if not _version_is_newer(remote_version, local_version):
        notify("已是最新版本", f"当前版本 v{local_version}（来源：{source_name}）", 1.0, "success")
        return local_version, source_name

    notify("发现新版本", f"v{local_version} -> v{remote_version}（来源：{source_name}）", 0.24, "success")
    last_emit = [0.0]

    def on_progress(downloaded: int, total: Optional[int]) -> None:
        now = time.monotonic()
        if (now - last_emit[0]) < 0.15 and total and downloaded < total:
            return
        last_emit[0] = now

        if total and total > 0:
            percent = downloaded / float(total)
            progress = 0.24 + min(0.56, 0.56 * percent)
            detail = f"正在下载应用包：{downloaded / 1048576:.1f} / {total / 1048576:.1f} MB"
            notify("正在下载更新", detail, progress, "info")
        else:
            detail = f"正在下载应用包：{downloaded / 1048576:.1f} MB"
            notify("正在下载更新", detail, None, "info")

    package_bytes = _fetch_bytes(package_url, progress_cb=on_progress)
    _install_zip_package(base, package_bytes, package_sha256, entrypoint, status_cb=notify)
    notify("更新完成", f"已更新到 v{remote_version}", 1.0, "success")
    return remote_version, source_name


def _launch_app(base: Path, channel: str) -> None:
    app_dir = base / APP_DIR_NAME
    entry = app_dir / DEFAULT_ENTRYPOINT
    if not entry.exists():
        raise RuntimeError("本地应用不存在，请联网后重试。")

    os.environ["BOMANA_CHANNEL"] = channel
    os.chdir(app_dir)
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    runpy.run_path(str(entry), run_name="__main__")


def _friendly_error_text(err: Exception, channel: str) -> str:
    msg = str(err)
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
    if "发布清单字段缺失" in msg:
        return "更新清单格式异常。请稍后重试或联系维护者。"
    if "更新清单字段缺失" in msg:
        return "在线更新接口返回异常。请稍后重试。"
    return f"更新失败：{msg}"


class LauncherWindow:
    """Simple, user-friendly GUI for launcher status and recovery actions."""

    def __init__(self, base: Path, channel: str):
        self.base = base
        self.channel = channel
        self.detected_channel = channel
        self.client_identity = _build_client_identity(base)
        self.local_version = _read_local_app_version(base / APP_DIR_NAME)
        self.events: "queue.Queue[Tuple[str, Dict[str, Any]]]" = queue.Queue()
        self.running = False
        self.has_attempted_update = False
        self.indeterminate = True
        self.anim_phase = 0
        self.progress_value = 0.0
        self.decision = LaunchDecision(action="exit", final_version=self.local_version)
        self._worker: Optional[threading.Thread] = None
        self._spin = ["◜", "◠", "◝", "◞", "◡", "◟"]

        self.root = tk.Tk()
        self.root.title(DISPLAY_NAME)
        self.root.geometry("560x360")
        self.root.resizable(False, False)
        self.root.configure(bg=_THEME["BG"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_exit)
        self.channel_var = tk.StringVar(master=self.root, value=channel)

        self._build_ui()
        self._set_status("准备就绪", "请选择通道，然后点击“开始更新并启动”。", 0.0, "info")
        self._set_running(False)
        self.root.after(80, self._poll_events)
        self.root.after(100, self._animate)

    def _build_ui(self) -> None:
        top = tk.Frame(self.root, bg=_THEME["BG"])
        top.pack(fill="x", padx=20, pady=(16, 8))

        self.title_lbl = tk.Label(
            top,
            text=DISPLAY_NAME,
            font=("Segoe UI", 18, "bold"),
            fg=_THEME["TEXT"],
            bg=_THEME["BG"],
            anchor="w",
        )
        self.title_lbl.pack(fill="x")

        self.sub_lbl = tk.Label(
            top,
            text=f"通道：{self.channel}  |  本地版本：v{self.local_version}",
            font=("Segoe UI", 10),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["BG"],
            anchor="w",
        )
        self.sub_lbl.pack(fill="x", pady=(3, 0))

        channel_row = tk.Frame(top, bg=_THEME["BG"])
        channel_row.pack(fill="x", pady=(8, 0))

        channel_title = tk.Label(
            channel_row,
            text="版本通道",
            font=("Segoe UI", 10, "bold"),
            fg=_THEME["TEXT"],
            bg=_THEME["BG"],
            anchor="w",
        )
        channel_title.pack(side="left")

        self.channel_menu = tk.OptionMenu(channel_row, self.channel_var, "Enhanced", "Standard", "Lite")
        self.channel_menu.config(
            bg=_THEME["CARD"],
            fg=_THEME["TEXT"],
            activebackground=_THEME["BORDER"],
            activeforeground=_THEME["TEXT"],
            highlightthickness=1,
            highlightbackground=_THEME["BORDER"],
            bd=0,
            width=10,
            cursor="hand2",
        )
        self.channel_menu["menu"].config(
            bg=_THEME["CARD"],
            fg=_THEME["TEXT"],
            activebackground=_THEME["BORDER"],
            activeforeground=_THEME["TEXT"],
            bd=0,
        )
        self.channel_menu.pack(side="left", padx=(8, 0))

        auto_tip = tk.Label(
            channel_row,
            text=f"默认推荐通道：{self.detected_channel}",
            font=("Segoe UI", 9),
            fg=_THEME["TEXT_MUTED"],
            bg=_THEME["BG"],
            anchor="w",
        )
        auto_tip.pack(side="left", padx=(10, 0))

        self.channel_desc_lbl = tk.Label(
            top,
            text="",
            font=("Segoe UI", 9),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["BG"],
            anchor="w",
            justify="left",
            wraplength=540,
        )
        self.channel_desc_lbl.pack(fill="x", pady=(6, 0))
        self.channel_var.trace_add("write", self._on_channel_changed)
        self._refresh_channel_details()

        card = tk.Frame(
            self.root,
            bg=_THEME["CARD"],
            highlightthickness=1,
            highlightbackground=_THEME["BORDER"],
        )
        card.pack(fill="both", expand=True, padx=20, pady=(4, 10))

        self.status_lbl = tk.Label(
            card,
            text="◜ 正在准备",
            font=("Segoe UI", 12, "bold"),
            fg=_THEME["BLUE"],
            bg=_THEME["CARD"],
            anchor="w",
        )
        self.status_lbl.pack(fill="x", padx=16, pady=(16, 6))

        self.detail_lbl = tk.Label(
            card,
            text="",
            font=("Segoe UI", 10),
            fg=_THEME["TEXT_DIM"],
            bg=_THEME["CARD"],
            anchor="w",
            justify="left",
            wraplength=520,
        )
        self.detail_lbl.pack(fill="x", padx=16)

        self.progress_canvas = tk.Canvas(
            card,
            width=520,
            height=12,
            bg=_THEME["BORDER"],
            bd=0,
            highlightthickness=0,
        )
        self.progress_canvas.pack(padx=16, pady=(14, 6))
        self.progress_bar = self.progress_canvas.create_rectangle(0, 0, 0, 12, fill=_THEME["BLUE"], width=0)

        self.hint_lbl = tk.Label(
            card,
            text="首次启动会自动下载应用包，请保持网络可用。",
            font=("Segoe UI", 9),
            fg=_THEME["TEXT_MUTED"],
            bg=_THEME["CARD"],
            anchor="w",
        )
        self.hint_lbl.pack(fill="x", padx=16, pady=(2, 10))

        btn_row = tk.Frame(card, bg=_THEME["CARD"])
        btn_row.pack(fill="x", padx=16, pady=(0, 14))

        self.start_btn = tk.Button(
            btn_row,
            text="开始更新并启动",
            width=14,
            command=self._on_start,
            bg=_THEME["BLUE"],
            fg="#0a0e13",
            activebackground="#79b8ff",
            activeforeground="#0a0e13",
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self.start_btn.pack(side="left")

        self.retry_btn = tk.Button(
            btn_row,
            text="重试",
            width=10,
            command=self._on_retry,
            bg=_THEME["CARD"],
            fg=_THEME["TEXT"],
            activebackground=_THEME["BORDER"],
            activeforeground=_THEME["TEXT"],
            relief="flat",
            bd=1,
            highlightthickness=1,
            highlightbackground=_THEME["BORDER"],
            cursor="hand2",
        )
        self.retry_btn.pack(side="left")

        self.offline_btn = tk.Button(
            btn_row,
            text="离线启动",
            width=12,
            command=self._on_offline_launch,
            bg=_THEME["CARD"],
            fg=_THEME["TEXT"],
            activebackground=_THEME["BORDER"],
            activeforeground=_THEME["TEXT"],
            relief="flat",
            bd=1,
            highlightthickness=1,
            highlightbackground=_THEME["BORDER"],
            cursor="hand2",
        )
        self.offline_btn.pack(side="left", padx=(8, 0))

        self.release_btn = tk.Button(
            btn_row,
            text="打开下载页",
            width=12,
            command=self._open_releases,
            bg=_THEME["CARD"],
            fg=_THEME["TEXT"],
            activebackground=_THEME["BORDER"],
            activeforeground=_THEME["TEXT"],
            relief="flat",
            bd=1,
            highlightthickness=1,
            highlightbackground=_THEME["BORDER"],
            cursor="hand2",
        )
        self.release_btn.pack(side="right")

        self.exit_btn = tk.Button(
            btn_row,
            text="退出",
            width=10,
            command=self._on_exit,
            bg=_THEME["CARD"],
            fg=_THEME["TEXT"],
            activebackground=_THEME["BORDER"],
            activeforeground=_THEME["TEXT"],
            relief="flat",
            bd=1,
            highlightthickness=1,
            highlightbackground=_THEME["BORDER"],
            cursor="hand2",
        )
        self.exit_btn.pack(side="right", padx=(0, 8))

    def _start_worker(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._worker_main, daemon=True)
        self._worker.start()

    def _worker_main(self) -> None:
        final_version = self.local_version
        update_ok = False
        update_source = ""
        update_error = ""
        local_ready = _is_local_app_ready(self.base)

        _log(self.base, f"Launcher start, channel={self.channel}, version={LAUNCHER_VERSION}")
        _report_primary_event(
            self.base,
            self.client_identity,
            "launcher_start",
            self.channel,
            final_version,
        )

        try:
            final_version, update_source = _check_and_update(
                self.base,
                self.channel,
                self.client_identity,
                status_cb=self._emit_status,
            )
            update_ok = True
            local_ready = _is_local_app_ready(self.base)
        except Exception as e:
            update_error = _friendly_error_text(e, self.channel)
            _log(self.base, f"更新检查失败：{e}")

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

        _write_state(
            self.base,
            {
                "launcher_version": LAUNCHER_VERSION,
                "display_name": DISPLAY_NAME,
                "channel": self.channel,
                "last_check_utc": _now_utc_iso(),
                "app_version": final_version,
                "update_ok": update_ok,
                "update_source": update_source,
                "update_error": update_error,
                "device_id": self.client_identity.get("device_id", ""),
                "install_id": self.client_identity.get("install_id", ""),
            },
        )

        if local_ready:
            if update_ok:
                self.events.put(
                    (
                        "done",
                        {
                            "launch": True,
                            "final_version": final_version,
                            "warning": "",
                            "status": "准备启动",
                            "detail": f"版本 v{final_version}，正在启动...",
                            "level": "success",
                        },
                    )
                )
            else:
                self.events.put(
                    (
                        "done",
                        {
                            "launch": True,
                            "final_version": final_version,
                            "warning": update_error,
                            "status": "已切换离线启动",
                            "detail": f"{update_error}\n将使用本地版本 v{final_version} 启动。",
                            "level": "warning",
                        },
                    )
                )
        else:
            detail = update_error or "当前没有本地可用版本，请先联网完成首次下载。"
            self.events.put(
                (
                    "done",
                    {
                        "launch": False,
                        "final_version": final_version,
                        "warning": detail,
                        "status": "无法启动",
                        "detail": detail,
                        "level": "error",
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
                elif typ == "done":
                    launch = bool(payload.get("launch", False))
                    final_version = str(payload.get("final_version", self.local_version))
                    warning = str(payload.get("warning", ""))
                    self.decision = LaunchDecision(
                        action=("launch" if launch else "exit"),
                        final_version=final_version,
                        warning=warning,
                    )
                    self._set_status(
                        str(payload.get("status", "")),
                        str(payload.get("detail", "")),
                        (1.0 if launch else self.progress_value),
                        str(payload.get("level", "info")),
                    )
                    self._set_running(False)
                    if launch:
                        self.sub_lbl.config(text=f"通道：{self.channel}  |  本地版本：v{final_version}")
                        self.root.after(700, self._commit_launch)
                    else:
                        self._show_error_actions()
        except queue.Empty:
            pass
        finally:
            self.root.after(80, self._poll_events)

    def _animate(self) -> None:
        if self.running:
            spin = self._spin[self.anim_phase % len(self._spin)]
            self.anim_phase += 1
            text = self.status_lbl.cget("text")
            if len(text) > 2:
                self.status_lbl.config(text=f"{spin} {text[2:]}")
            if self.indeterminate:
                width = 520
                block = 110
                x = (self.anim_phase * 14) % (width + block) - block
                x0 = max(0, x)
                x1 = min(width, x + block)
                self.progress_canvas.coords(self.progress_bar, x0, 0, x1, 12)
        self.root.after(100, self._animate)

    def _set_status(self, title: str, detail: str, progress: Optional[float], level: str) -> None:
        color = _THEME["BLUE"]
        if level == "success":
            color = _THEME["GREEN"]
        elif level == "warning":
            color = _THEME["YELLOW"]
        elif level == "error":
            color = _THEME["RED"]

        if title:
            self.status_lbl.config(text=f"◜ {title}", fg=color)
        self.detail_lbl.config(text=detail or "")

        if progress is None:
            self.indeterminate = True
        else:
            self.indeterminate = False
            self.progress_value = max(0.0, min(1.0, progress))
            width = int(520 * self.progress_value)
            self.progress_canvas.coords(self.progress_bar, 0, 0, width, 12)

    def _set_running(self, running: bool) -> None:
        self.running = running
        state = "disabled" if running else "normal"
        self.start_btn.config(state=state)
        self.retry_btn.config(state=state)
        self.offline_btn.config(state=state)
        self.release_btn.config(state="normal")
        self.exit_btn.config(state="normal")
        self.channel_menu.config(state=state)

        if running:
            self.retry_btn.pack_forget()
            self.hint_lbl.config(text="正在自动处理更新流程，请稍候...")
        else:
            if self.has_attempted_update:
                self.retry_btn.pack(side="left", padx=(8, 0))
            else:
                self.retry_btn.pack_forget()
            if _is_local_app_ready(self.base):
                self.offline_btn.config(state="normal")
            else:
                self.offline_btn.config(state="disabled")
            if not self.has_attempted_update:
                self.hint_lbl.config(text="建议先使用默认通道；仅在你明确知道差异时再切换。")
            if not _is_local_app_ready(self.base):
                self.hint_lbl.config(text="离线启动不可用：当前设备没有已下载的本地版本。")

    def _show_error_actions(self) -> None:
        self.hint_lbl.config(text="可点击“重试”或“打开下载页”。首次使用请先联网完成下载。")

    def _on_start(self) -> None:
        if self.running:
            return
        self.has_attempted_update = True
        self.channel = self.channel_var.get().strip() or self.detected_channel
        self.local_version = _read_local_app_version(self.base / APP_DIR_NAME)
        self.sub_lbl.config(text=f"通道：{self.channel}  |  本地版本：v{self.local_version}")
        self._set_status("准备开始", f"已选择通道：{self.channel}", 0.0, "info")
        self._set_running(True)
        self._start_worker()

    def _on_retry(self) -> None:
        self._on_start()

    def _on_channel_changed(self, *_args) -> None:
        if self.running:
            return
        self.channel = self.channel_var.get().strip() or self.detected_channel
        self.local_version = _read_local_app_version(self.base / APP_DIR_NAME)
        self.sub_lbl.config(text=f"通道：{self.channel}  |  本地版本：v{self.local_version}")
        self._refresh_channel_details()

    def _refresh_channel_details(self) -> None:
        ch = self.channel_var.get().strip() or self.detected_channel
        info = CHANNEL_DETAILS.get(ch, CHANNEL_DETAILS["Enhanced"])
        self.channel_desc_lbl.config(text=f"{info['title']}\n{info['desc']}\n{info['who']}")

    def _on_offline_launch(self) -> None:
        if not _is_local_app_ready(self.base):
            self._set_status("无法离线启动", "本地没有可用应用包。", None, "error")
            return
        final_version = _read_local_app_version(self.base / APP_DIR_NAME)
        self.decision = LaunchDecision(action="launch", final_version=final_version, warning="")
        self._set_status("离线启动", f"将启动本地版本 v{final_version}", 1.0, "success")
        self.root.after(300, self._commit_launch)

    def _open_releases(self) -> None:
        try:
            webbrowser.open(RELEASES_URL)
        except Exception:
            pass

    def _commit_launch(self) -> None:
        if self.decision.action == "launch":
            self.root.destroy()

    def _on_exit(self) -> None:
        self.decision = LaunchDecision(action="exit", final_version=self.local_version, warning=self.decision.warning)
        self.root.destroy()

    def run(self) -> LaunchDecision:
        self.root.mainloop()
        return self.decision


def main() -> None:
    base = _base_dir()
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
            "无法启动应用。\n"
            f"名称: {DISPLAY_NAME}\n"
            f"版本: {decision.final_version}\n"
            f"通道: {selected_channel}\n"
            f"错误: {e}\n"
            "请检查 launcher.log。",
        )


if __name__ == "__main__":
    main()
