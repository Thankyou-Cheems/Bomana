"""Constrained client for Bomana's protected native Windows hotkey broker."""

from __future__ import annotations

import contextlib
import ctypes
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

BROKER_DIRECTORY_NAME = "HotkeyBroker"
BROKER_EXECUTABLE_NAME = "BomanaHotkeyBroker.exe"
BROKER_INSTALL_RELATIVE = Path("Bomana") / BROKER_DIRECTORY_NAME / BROKER_EXECUTABLE_NAME
BROKER_RELEASES_URL = "https://github.com/Thankyou-Cheems/Bomana/releases"

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


@dataclass(frozen=True, slots=True)
class BrokerStartResult:
    status: BrokerStartStatus
    message: str = ""
    error_code: int | None = None


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


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


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


class WINTRUST_FILE_INFO(ctypes.Structure):
    _fields_ = [
        ("cbStruct", wintypes.DWORD),
        ("pcwszFilePath", wintypes.LPCWSTR),
        ("hFile", wintypes.HANDLE),
        ("pgKnownSubject", ctypes.POINTER(GUID)),
    ]


class WINTRUST_DATA(ctypes.Structure):
    _fields_ = [
        ("cbStruct", wintypes.DWORD),
        ("pPolicyCallbackData", wintypes.LPVOID),
        ("pSIPClientData", wintypes.LPVOID),
        ("dwUIChoice", wintypes.DWORD),
        ("fdwRevocationChecks", wintypes.DWORD),
        ("dwUnionChoice", wintypes.DWORD),
        ("pFile", ctypes.POINTER(WINTRUST_FILE_INFO)),
        ("dwStateAction", wintypes.DWORD),
        ("hWVTStateData", wintypes.HANDLE),
        ("pwszURLReference", wintypes.LPCWSTR),
        ("dwProvFlags", wintypes.DWORD),
        ("dwUIContext", wintypes.DWORD),
        ("pSignatureSettings", wintypes.LPVOID),
    ]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]


class TOKEN_USER(ctypes.Structure):
    _fields_ = [("User", SID_AND_ATTRIBUTES)]


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


def _known_program_files() -> Path | None:
    if not _is_windows():
        return None
    shell32 = _windows_dll("shell32")
    ole32 = _windows_dll("ole32")
    if shell32 is None or ole32 is None:
        return None

    folder_id = GUID(
        0x905E63B6,
        0xC1BF,
        0x494E,
        (ctypes.c_ubyte * 8)(0xB2, 0x9C, 0x65, 0xB7, 0x32, 0xD3, 0xD2, 0x1A),
    )
    path_pointer = wintypes.LPWSTR()
    get_known_folder = shell32.SHGetKnownFolderPath
    get_known_folder.argtypes = [
        ctypes.POINTER(GUID),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    get_known_folder.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [wintypes.LPVOID]
    ole32.CoTaskMemFree.restype = None
    if get_known_folder(ctypes.byref(folder_id), 0, None, ctypes.byref(path_pointer)) != 0:
        return None
    try:
        return Path(path_pointer.value)
    finally:
        ole32.CoTaskMemFree(path_pointer)


def installed_broker_path(*, program_files: Path | None = None) -> Path | None:
    """Return the one allowed broker path; injection is test-only and not runtime config."""

    root = Path(program_files).resolve() if program_files is not None else _known_program_files()
    if root is None:
        return None
    return root / BROKER_INSTALL_RELATIVE


def verify_authenticode(path: Path) -> bool:
    """Verify that Windows trusts the executable's Authenticode signature."""

    if not _is_windows() or not path.is_file():
        return False
    wintrust = _windows_dll("wintrust")
    if wintrust is None:
        return False

    action = GUID(
        0x00AAC56B,
        0xCD44,
        0x11D0,
        (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE),
    )
    file_info = WINTRUST_FILE_INFO()
    file_info.cbStruct = ctypes.sizeof(WINTRUST_FILE_INFO)
    file_info.pcwszFilePath = str(path)

    trust_data = WINTRUST_DATA()
    trust_data.cbStruct = ctypes.sizeof(WINTRUST_DATA)
    trust_data.dwUIChoice = 2  # WTD_UI_NONE
    trust_data.fdwRevocationChecks = 0  # WTD_REVOKE_NONE
    trust_data.dwUnionChoice = 1  # WTD_CHOICE_FILE
    trust_data.pFile = ctypes.pointer(file_info)
    trust_data.dwStateAction = 1  # WTD_STATEACTION_VERIFY
    trust_data.dwProvFlags = 0x1000  # WTD_CACHE_ONLY_URL_RETRIEVAL

    verify = wintrust.WinVerifyTrust
    verify.argtypes = [wintypes.HWND, ctypes.POINTER(GUID), wintypes.LPVOID]
    verify.restype = ctypes.c_long
    status = int(verify(None, ctypes.byref(action), ctypes.byref(trust_data)))
    trust_data.dwStateAction = 2  # WTD_STATEACTION_CLOSE
    with contextlib.suppress(OSError, ValueError):
        verify(None, ctypes.byref(action), ctypes.byref(trust_data))
    return status == 0


def find_trusted_broker() -> BrokerStartResult | Path:
    path = installed_broker_path()
    if path is None or not path.is_file():
        return BrokerStartResult(
            BrokerStartStatus.UNAVAILABLE,
            "未安装受保护的热键组件。",
        )
    try:
        expected_parent = path.parent.resolve(strict=True)
        actual = path.resolve(strict=True)
    except OSError as exc:
        return BrokerStartResult(BrokerStartStatus.UNAVAILABLE, str(exc))
    if actual.parent != expected_parent or actual.name != BROKER_EXECUTABLE_NAME:
        return BrokerStartResult(BrokerStartStatus.UNTRUSTED, "热键组件路径不可信。")
    if not verify_authenticode(actual):
        return BrokerStartResult(
            BrokerStartStatus.UNTRUSTED,
            "热键组件缺少有效的 Authenticode 签名。",
        )
    return actual


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
        self._reader_thread: threading.Thread | None = None
        self._stopping = False
        self._ready = False
        self._session_token = ""

    def start(self) -> BrokerStartResult:
        if not _is_windows():
            return BrokerStartResult(BrokerStartStatus.UNSUPPORTED)
        trusted = find_trusted_broker()
        if isinstance(trusted, BrokerStartResult):
            return trusted

        kernel32 = _windows_dll("kernel32")
        if kernel32 is None:
            return BrokerStartResult(BrokerStartStatus.UNSUPPORTED, "Windows IPC API 不可用。")
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
            trusted,
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
        log_event(
            "hotkey_broker_started",
            binding_count=len(self.bindings),
            broker_path=str(trusted),
        )
        return result

    def stop(self) -> None:
        self._stopping = True
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
        for attribute in ("_pipe_handle", "_stop_event_handle"):
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
