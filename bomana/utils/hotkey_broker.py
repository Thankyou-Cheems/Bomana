"""Ordinary-first client for Bomana's optional native Windows hotkey broker."""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import os
import secrets
import subprocess
import threading
from collections.abc import Callable, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from bomana.utils.diagnostics import log_event, log_exception

BROKER_EXECUTABLE_NAME = "BomanaHotkeyBroker.exe"
BROKER_CHECKSUM_NAME = "BomanaHotkeyBroker.sha256"
BROKER_BIN_DIRECTORY = "bin"
WAR_THUNDER_EXECUTABLES = frozenset({"aces.exe", "aces64.exe", "aces_be.exe"})
WAR_THUNDER_WINDOW_TITLE = "war thunder"

ERROR_CANCELLED = 1223
ERROR_PIPE_CONNECTED = 535
ERROR_BROKEN_PIPE = 109
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_SHOWNORMAL = 1

PIPE_ACCESS_INBOUND = 0x00000001
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_TYPE_MESSAGE = 0x00000004
PIPE_READMODE_MESSAGE = 0x00000002
PIPE_WAIT = 0x00000000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x00000080
BROKER_READY_TIMEOUT_SECONDS = 12.0

FRAME_SIZE = 8
FRAME_MAGIC = b"BHK1"
FRAME_READY = 1
FRAME_ACTION = 2

ACTION_IDS = {
    "reset": 1,
    "lock": 2,
    "corner": 3,
    "beep": 4,
    "zones": 5,
}
REQUIRED_ACTIONS = frozenset({"reset", "lock", "corner", "beep"})
OPTIONAL_ACTIONS = frozenset({"zones"})


class BrokerStartStatus(StrEnum):
    STARTED = "started"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    UNTRUSTED = "untrusted"
    UNSUPPORTED = "unsupported"


class GameIntegrityStatus(StrEnum):
    ORDINARY = "ordinary"
    ELEVATED = "elevated"
    NOT_RUNNING = "not_running"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class BrokerStartResult:
    status: BrokerStartStatus
    message: str = ""
    error_code: int | None = None


@dataclass(frozen=True, slots=True)
class GameIntegrityResult:
    status: GameIntegrityStatus
    process_id: int | None = None
    image_name: str = ""
    message: str = ""


@dataclass(frozen=True, slots=True)
class BrokerBinding:
    action: str
    key_name: str
    callback: Callable[[], None]


@dataclass(frozen=True, slots=True)
class BrokerFrame:
    kind: int
    code: int
    detail: int


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", wintypes.LPVOID),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]


class TOKEN_USER(ctypes.Structure):
    _fields_ = [("User", SID_AND_ATTRIBUTES)]


class TOKEN_ELEVATION(ctypes.Structure):
    _fields_ = [("TokenIsElevated", wintypes.DWORD)]


def _is_windows() -> bool:
    return os.name == "nt"


def _windows_dll(name: str) -> Any | None:
    win_dll = getattr(ctypes, "WinDLL", None)
    if win_dll is None:
        return None
    try:
        return win_dll(name, use_last_error=True)
    except OSError:
        return None


def bundled_broker_path(*, package_directory: Path | None = None) -> Path:
    """Return the fixed broker path inside this App package.

    ``package_directory`` is dependency injection for tests/build validation;
    runtime configuration and environment variables cannot override this path.
    """

    package_root = (
        Path(package_directory).resolve()
        if package_directory is not None
        else Path(__file__).resolve().parents[1]
    )
    return package_root / BROKER_BIN_DIRECTORY / BROKER_EXECUTABLE_NAME


def broker_checksum_path(path: Path) -> Path:
    return path.with_name(BROKER_CHECKSUM_NAME)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_broker_sha256(path: Path) -> str:
    checksum = broker_checksum_path(path)
    text = checksum.read_text(encoding="ascii").strip()
    fields = text.split()
    if len(fields) != 2 or fields[1] != BROKER_EXECUTABLE_NAME:
        raise ValueError("invalid bundled hotkey broker checksum")
    expected = fields[0].lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise ValueError("invalid bundled hotkey broker SHA-256")
    return expected


def verify_bundled_broker(path: Path) -> bool:
    try:
        return sha256_file(path) == expected_broker_sha256(path)
    except OSError, UnicodeError, ValueError:
        return False


def find_bundled_broker() -> BrokerStartResult | Path:
    path = bundled_broker_path()
    if not path.is_file() or path.is_symlink():
        return BrokerStartResult(
            BrokerStartStatus.UNAVAILABLE,
            "当前 App 包未携带游戏内热键组件。",
        )
    try:
        expected_parent = path.parent.resolve(strict=True)
        actual = path.resolve(strict=True)
    except OSError as exc:
        return BrokerStartResult(BrokerStartStatus.UNAVAILABLE, str(exc))
    if actual.parent != expected_parent or actual.name != BROKER_EXECUTABLE_NAME:
        return BrokerStartResult(BrokerStartStatus.UNTRUSTED, "热键组件路径不可信。")
    if not verify_bundled_broker(actual):
        return BrokerStartResult(
            BrokerStartStatus.UNTRUSTED,
            "热键组件 SHA-256 校验失败，请重新下载官方 App 包。",
        )
    return actual


def _open_limited_process(process_id: int) -> int:
    kernel32 = _windows_dll("kernel32")
    if kernel32 is None:
        raise OSError("Windows process APIs are unavailable")
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(process_id))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return int(handle)


def _visible_window_process_ids() -> tuple[int, ...]:
    user32 = _windows_dll("user32")
    if not _is_windows() or user32 is None:
        return ()
    callback_type = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM,
    )
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    process_ids: set[int] = set()

    @callback_type
    def collect(hwnd: int, _parameter: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = int(user32.GetWindowTextLengthW(hwnd))
        if length <= 0:
            return True
        title = ctypes.create_unicode_buffer(length + 1)
        if user32.GetWindowTextW(hwnd, title, len(title)) <= 0:
            return True
        if WAR_THUNDER_WINDOW_TITLE not in title.value.casefold():
            return True
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value:
            process_ids.add(int(process_id.value))
        return True

    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    if not user32.EnumWindows(collect, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return tuple(sorted(process_ids))


def _process_image_name(process_id: int) -> str:
    kernel32 = _windows_dll("kernel32")
    if kernel32 is None:
        raise OSError("Windows process APIs are unavailable")
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = _open_limited_process(process_id)
    try:
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(
            wintypes.HANDLE(handle),
            0,
            buffer,
            ctypes.byref(length),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return Path(buffer.value).name.casefold()
    finally:
        kernel32.CloseHandle(wintypes.HANDLE(handle))


def _process_is_elevated(process_id: int) -> bool:
    kernel32 = _windows_dll("kernel32")
    advapi32 = _windows_dll("advapi32")
    if kernel32 is None or advapi32 is None:
        raise OSError("Windows token APIs are unavailable")
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    process = _open_limited_process(process_id)
    token = wintypes.HANDLE()
    try:
        advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        if not advapi32.OpenProcessToken(
            wintypes.HANDLE(process), TOKEN_QUERY, ctypes.byref(token)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        elevation = TOKEN_ELEVATION()
        returned = wintypes.DWORD()
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        advapi32.GetTokenInformation.restype = wintypes.BOOL
        if not advapi32.GetTokenInformation(
            token,
            20,  # TokenElevation
            ctypes.byref(elevation),
            ctypes.sizeof(elevation),
            ctypes.byref(returned),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return bool(elevation.TokenIsElevated)
    finally:
        if token:
            kernel32.CloseHandle(token)
        kernel32.CloseHandle(wintypes.HANDLE(process))


def detect_war_thunder_integrity() -> GameIntegrityResult:
    """Inspect only visible War Thunder-titled windows and token elevation."""

    if not _is_windows():
        return GameIntegrityResult(GameIntegrityStatus.UNSUPPORTED)
    try:
        process_ids = _visible_window_process_ids()
    except OSError as exc:
        return GameIntegrityResult(GameIntegrityStatus.UNKNOWN, message=str(exc))

    ordinary: GameIntegrityResult | None = None
    unknown: GameIntegrityResult | None = None
    for process_id in process_ids:
        try:
            image_name = _process_image_name(process_id)
        except OSError:
            continue
        if image_name not in WAR_THUNDER_EXECUTABLES:
            continue
        try:
            elevated = _process_is_elevated(process_id)
        except OSError as exc:
            unknown = GameIntegrityResult(
                GameIntegrityStatus.UNKNOWN,
                process_id,
                image_name,
                str(exc),
            )
            continue
        result = GameIntegrityResult(
            GameIntegrityStatus.ELEVATED if elevated else GameIntegrityStatus.ORDINARY,
            process_id,
            image_name,
        )
        if elevated:
            return result
        ordinary = result
    return ordinary or unknown or GameIntegrityResult(GameIntegrityStatus.NOT_RUNNING)


def _lock_broker_file(path: Path) -> int:
    kernel32 = _windows_dll("kernel32")
    if kernel32 is None:
        raise OSError("Windows file APIs are unavailable")
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    handle = kernel32.CreateFileW(
        str(path),
        GENERIC_READ,
        FILE_SHARE_READ,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if int(handle or 0) == int(INVALID_HANDLE_VALUE or 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(handle)


def normalize_bindings(bindings: Sequence[BrokerBinding]) -> tuple[BrokerBinding, ...]:
    normalized: list[BrokerBinding] = []
    seen_actions: set[str] = set()
    seen_keys: set[str] = set()
    for binding in bindings:
        action = str(binding.action).strip().lower()
        key_name = str(binding.key_name).strip().upper()
        if action not in REQUIRED_ACTIONS | OPTIONAL_ACTIONS:
            raise ValueError(f"unsupported broker action: {action!r}")
        if not key_name.startswith("F") or not key_name[1:].isdigit():
            raise ValueError(f"unsupported broker key: {key_name!r}")
        number = int(key_name[1:])
        if number not in range(1, 13):
            raise ValueError(f"unsupported broker key: {key_name!r}")
        if action in seen_actions or key_name in seen_keys:
            raise ValueError("broker actions and function keys must be unique")
        seen_actions.add(action)
        seen_keys.add(key_name)
        normalized.append(BrokerBinding(action, key_name, binding.callback))
    if not seen_actions >= REQUIRED_ACTIONS or len(normalized) not in (4, 5):
        raise ValueError("broker requires reset, lock, corner, beep, and optional zones")
    return tuple(sorted(normalized, key=lambda item: ACTION_IDS[item.action]))


def build_broker_arguments(
    session_token: str, bindings: Sequence[BrokerBinding]
) -> tuple[str, ...]:
    normalized = normalize_bindings(bindings)
    arguments: list[str] = ["--session", session_token]
    for binding in normalized:
        arguments.extend(("--binding", f"{binding.action}={binding.key_name}"))
    return tuple(arguments)


def decode_frame(payload: bytes) -> BrokerFrame:
    if len(payload) != FRAME_SIZE or payload[:4] != FRAME_MAGIC:
        raise ValueError("invalid broker frame")
    kind = int(payload[4])
    code = int(payload[5])
    detail = int.from_bytes(payload[6:8], "little")
    if kind == FRAME_READY:
        if code > 5 or detail & ~0x001F:
            raise ValueError("invalid broker ready frame")
    elif kind == FRAME_ACTION:
        if code not in ACTION_IDS.values() or detail != 0:
            raise ValueError("invalid broker action frame")
    else:
        raise ValueError("unsupported broker frame type")
    return BrokerFrame(kind, code, detail)


def _current_user_sid_string() -> str:
    kernel32 = _windows_dll("kernel32")
    advapi32 = _windows_dll("advapi32")
    if kernel32 is None or advapi32 is None:
        raise OSError("Windows token APIs are unavailable")

    token = wintypes.HANDLE()
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            1,
            buffer,
            required.value,
            ctypes.byref(required),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        token_user = ctypes.cast(buffer, ctypes.POINTER(TOKEN_USER)).contents
        sid_pointer = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(token_user.User.Sid, ctypes.byref(sid_pointer)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return str(sid_pointer.value)
        finally:
            kernel32.LocalFree(sid_pointer)
    finally:
        kernel32.CloseHandle(token)


def _security_attributes() -> tuple[SECURITY_ATTRIBUTES, wintypes.LPVOID]:
    advapi32 = _windows_dll("advapi32")
    if advapi32 is None:
        raise OSError("Windows security descriptor APIs are unavailable")
    sid = _current_user_sid_string()
    descriptor = wintypes.LPVOID()
    sddl = f"D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;{sid})"
    convert = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert.restype = wintypes.BOOL
    if not convert(sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    attributes = SECURITY_ATTRIBUTES()
    attributes.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
    attributes.lpSecurityDescriptor = descriptor
    attributes.bInheritHandle = False
    return attributes, descriptor


def _request_runas(path: Path, arguments: Sequence[str]) -> BrokerStartResult:
    shell32 = _windows_dll("shell32")
    kernel32 = _windows_dll("kernel32")
    if shell32 is None or kernel32 is None:
        return BrokerStartResult(BrokerStartStatus.UNSUPPORTED, "Windows UAC API 不可用。")
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = str(path)
    info.lpParameters = subprocess.list2cmdline(list(arguments))
    info.lpDirectory = str(path.parent)
    info.nShow = SW_SHOWNORMAL

    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error_code = int(ctypes.get_last_error())
        if error_code == ERROR_CANCELLED:
            return BrokerStartResult(
                BrokerStartStatus.CANCELLED,
                "用户取消了游戏内热键权限。",
                error_code,
            )
        return BrokerStartResult(
            BrokerStartStatus.FAILED,
            f"热键组件启动失败（Windows 错误 {error_code}）。",
            error_code or None,
        )
    if info.hProcess:
        kernel32.CloseHandle(info.hProcess)
    return BrokerStartResult(BrokerStartStatus.STARTED)


class ElevatedHotkeyBrokerClient:
    """Own one ACL-restricted broker session and dispatch fixed action frames."""

    def __init__(
        self,
        dispatch: Callable[..., None],
        bindings: Sequence[BrokerBinding],
        *,
        ready_cb: Callable[[tuple[str, ...]], None],
        failure_cb: Callable[[str], None],
    ) -> None:
        self.dispatch = dispatch
        self.bindings = normalize_bindings(bindings)
        self.ready_cb = ready_cb
        self.failure_cb = failure_cb
        self._pipe_handle: int | None = None
        self._stop_event_handle: int | None = None
        self._broker_file_handle: int | None = None
        self._reader_thread: threading.Thread | None = None
        self._startup_timer: threading.Timer | None = None
        self._stopping = False
        self._ready = False
        self._session_token = ""

    def start(self) -> BrokerStartResult:
        if not _is_windows():
            return BrokerStartResult(BrokerStartStatus.UNSUPPORTED)
        broker_path = find_bundled_broker()
        if isinstance(broker_path, BrokerStartResult):
            return broker_path

        kernel32 = _windows_dll("kernel32")
        if kernel32 is None:
            return BrokerStartResult(BrokerStartStatus.UNSUPPORTED, "Windows IPC API 不可用。")
        try:
            self._broker_file_handle = _lock_broker_file(broker_path)
        except OSError as exc:
            return BrokerStartResult(BrokerStartStatus.UNTRUSTED, str(exc))
        if not verify_bundled_broker(broker_path):
            self.stop()
            return BrokerStartResult(
                BrokerStartStatus.UNTRUSTED,
                "热键组件在启动前发生变化，请重新下载官方 App 包。",
            )
        self._session_token = f"{os.getpid()}-{secrets.token_hex(16)}"
        pipe_name = rf"\\.\pipe\Bomana.HotkeyBroker.{self._session_token}"
        event_name = rf"Local\Bomana.HotkeyBroker.Stop.{self._session_token}"

        descriptor = wintypes.LPVOID()
        try:
            attributes, descriptor = _security_attributes()
            with contextlib.suppress(AttributeError, TypeError):
                kernel32.CreateNamedPipeW.argtypes = [
                    wintypes.LPCWSTR,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    ctypes.POINTER(SECURITY_ATTRIBUTES),
                ]
                kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
                kernel32.CreateEventW.argtypes = [
                    ctypes.POINTER(SECURITY_ATTRIBUTES),
                    wintypes.BOOL,
                    wintypes.BOOL,
                    wintypes.LPCWSTR,
                ]
                kernel32.CreateEventW.restype = wintypes.HANDLE
            pipe_handle = kernel32.CreateNamedPipeW(
                pipe_name,
                PIPE_ACCESS_INBOUND | FILE_FLAG_FIRST_PIPE_INSTANCE,
                PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                1,
                FRAME_SIZE,
                FRAME_SIZE,
                0,
                ctypes.byref(attributes),
            )
            if int(pipe_handle or 0) == int(INVALID_HANDLE_VALUE or 0):
                raise ctypes.WinError(ctypes.get_last_error())
            self._pipe_handle = int(pipe_handle)
            stop_event = kernel32.CreateEventW(
                ctypes.byref(attributes),
                True,
                False,
                event_name,
            )
            if not stop_event:
                raise ctypes.WinError(ctypes.get_last_error())
            self._stop_event_handle = int(stop_event)
        except OSError as exc:
            self.stop()
            return BrokerStartResult(BrokerStartStatus.FAILED, str(exc))
        finally:
            if descriptor:
                kernel32.LocalFree(descriptor)

        result = _request_runas(
            broker_path,
            build_broker_arguments(self._session_token, self.bindings),
        )
        if result.status is not BrokerStartStatus.STARTED:
            self.stop()
            return result

        self._stopping = False
        self._reader_thread = threading.Thread(
            target=self._read_frames,
            name="BomanaHotkeyBrokerPipe",
            daemon=True,
        )
        self._reader_thread.start()
        self._startup_timer = threading.Timer(
            BROKER_READY_TIMEOUT_SECONDS,
            self._handle_start_timeout,
        )
        self._startup_timer.daemon = True
        self._startup_timer.start()
        log_event(
            "hotkey_broker_started",
            binding_count=len(self.bindings),
            broker_path=str(broker_path),
        )
        return result

    def stop(self) -> None:
        self._stopping = True
        timer = self._startup_timer
        self._startup_timer = None
        if timer is not None:
            timer.cancel()
        kernel32 = _windows_dll("kernel32")
        if kernel32 is None:
            return
        if self._stop_event_handle:
            with contextlib.suppress(OSError, TypeError, ValueError):
                kernel32.SetEvent(wintypes.HANDLE(self._stop_event_handle))
        if self._pipe_handle:
            with contextlib.suppress(OSError, TypeError, ValueError):
                kernel32.DisconnectNamedPipe(wintypes.HANDLE(self._pipe_handle))
        thread = self._reader_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._reader_thread = None
        for attribute in ("_pipe_handle", "_stop_event_handle", "_broker_file_handle"):
            handle = getattr(self, attribute)
            if handle:
                with contextlib.suppress(OSError, TypeError, ValueError):
                    kernel32.CloseHandle(wintypes.HANDLE(handle))
                setattr(self, attribute, None)

    def _read_frames(self) -> None:
        kernel32 = _windows_dll("kernel32")
        pipe_handle = self._pipe_handle
        if kernel32 is None or pipe_handle is None:
            return
        kernel32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        kernel32.ConnectNamedPipe.restype = wintypes.BOOL
        kernel32.ReadFile.argtypes = [
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        ]
        kernel32.ReadFile.restype = wintypes.BOOL
        connected = bool(kernel32.ConnectNamedPipe(wintypes.HANDLE(pipe_handle), None))
        if not connected and ctypes.get_last_error() != ERROR_PIPE_CONNECTED:
            self._dispatch_failure("热键组件未能建立安全连接。")
            return

        while not self._stopping:
            payload = ctypes.create_string_buffer(FRAME_SIZE)
            bytes_read = wintypes.DWORD()
            ok = bool(
                kernel32.ReadFile(
                    wintypes.HANDLE(pipe_handle),
                    payload,
                    FRAME_SIZE,
                    ctypes.byref(bytes_read),
                    None,
                )
            )
            if not ok:
                error_code = int(ctypes.get_last_error())
                if not self._stopping:
                    self._dispatch_failure(f"热键组件连接已中断（Windows 错误 {error_code}）。")
                return
            try:
                frame = decode_frame(payload.raw[: bytes_read.value])
            except ValueError as exc:
                self._dispatch_failure(str(exc))
                return
            self._dispatch_frame(frame)

    def _dispatch_frame(self, frame: BrokerFrame) -> None:
        if frame.kind == FRAME_READY:
            failed = tuple(
                binding.key_name
                for binding in self.bindings
                if frame.detail & (1 << (ACTION_IDS[binding.action] - 1))
            )
            self._ready = True
            timer = self._startup_timer
            self._startup_timer = None
            if timer is not None:
                timer.cancel()
            self.dispatch(self.ready_cb, failed)
            return
        binding = next(
            (item for item in self.bindings if ACTION_IDS[item.action] == frame.code),
            None,
        )
        if binding is not None:
            self.dispatch(self._deliver_action, binding)

    @staticmethod
    def _deliver_action(binding: BrokerBinding) -> None:
        log_event(
            "global_hotkey_received",
            backend="privileged_broker",
            action=binding.action,
            key_name=binding.key_name,
        )
        binding.callback()

    def _dispatch_failure(self, message: str) -> None:
        log_exception("hotkey_broker_failed", RuntimeError(message))
        if not self._stopping:
            self.dispatch(self.failure_cb, message)

    def _handle_start_timeout(self) -> None:
        if self._stopping or self._ready:
            return
        message = "管理员热键组件未在限定时间内建立连接。"
        log_exception("hotkey_broker_start_timeout", TimeoutError(message))
        self.stop()
        self.dispatch(self.failure_cb, message)
