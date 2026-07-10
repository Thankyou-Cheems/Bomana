"""Constrained Windows elevation helpers for the launcher app-only handoff."""

from __future__ import annotations

import contextlib
import ctypes
import os
import subprocess
import sys
from collections.abc import Sequence
from ctypes import wintypes
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

ALLOWED_CHANNELS = frozenset({"Enhanced", "Standard", "Lite"})
INTERNAL_APP_ONLY_FLAG = "--bomana-elevated-app"
INTERNAL_CHANNEL_FLAG = "--channel"

ERROR_CANCELLED = 1223
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_SHOWNORMAL = 1
TOKEN_QUERY = 0x0008
TOKEN_INFORMATION_CLASS_ELEVATION = 20


class ElevationStatus(StrEnum):
    """Result of requesting the constrained elevated app launch."""

    STARTED = "started"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ElevationResult:
    """Structured elevation outcome without exposing credentials or shell state."""

    status: ElevationStatus
    error_code: int | None = None
    error_message: str = ""


@dataclass(frozen=True, slots=True)
class ElevatedLaunchCommand:
    """Absolute ShellExecute target and its already-quoted fixed parameters."""

    executable: Path
    parameters: str
    working_directory: Path
    argument_vector: tuple[str, ...]


class SHELLEXECUTEINFOW(ctypes.Structure):
    """ctypes representation of the Win32 SHELLEXECUTEINFOW structure."""

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


class TOKEN_ELEVATION(ctypes.Structure):
    """ctypes representation of the Win32 TOKEN_ELEVATION structure."""

    _fields_ = [("TokenIsElevated", wintypes.DWORD)]


def _is_windows() -> bool:
    return os.name == "nt"


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _windows_dll(name: str) -> Any | None:
    win_dll = getattr(ctypes, "WinDLL", None)
    if win_dll is not None:
        try:
            return win_dll(name, use_last_error=True)
        except OSError:
            return None
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None
    return getattr(windll, name, None)


def _validate_channel(
    channel: str, allowed_channels: Sequence[str] = tuple(ALLOWED_CHANNELS)
) -> str:
    value = str(channel)
    allowed_values = frozenset(str(item) for item in allowed_channels)
    if value not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise ValueError(f"unsupported launcher channel {value!r}; expected one of: {allowed}")
    return value


def parse_elevated_app_request(
    argv: Sequence[str],
    allowed_channels: Sequence[str],
) -> str | None:
    """Parse ``sys.argv[1:]`` for the exact internal app-only command shape.

    An empty list is a normal launcher invocation. Any non-empty invocation must
    match the fixed three-token form; arbitrary entrypoints and extra arguments
    are deliberately unsupported.
    """

    tokens = tuple(str(value) for value in argv)
    if INTERNAL_APP_ONLY_FLAG not in tokens:
        return None
    if (
        len(tokens) != 3
        or tokens[0] != INTERNAL_APP_ONLY_FLAG
        or tokens[1] != INTERNAL_CHANNEL_FLAG
    ):
        raise ValueError("invalid internal app-only launcher arguments")
    return _validate_channel(tokens[2], allowed_channels)


def _resolved_existing_file(path: str | Path, label: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} does not exist: {resolved}")
    return resolved


def build_elevated_app_command(
    *,
    launcher_entry: Path,
    base: Path,
    channel: str,
) -> ElevatedLaunchCommand:
    """Build the only command shape allowed across the elevation boundary."""

    validated_channel = _validate_channel(channel)
    executable = _resolved_existing_file(sys.executable, "launcher executable")
    resolved_base = Path(base).resolve()
    if not resolved_base.is_dir():
        raise FileNotFoundError(f"launcher base does not exist: {resolved_base}")
    internal_args = (
        INTERNAL_APP_ONLY_FLAG,
        INTERNAL_CHANNEL_FLAG,
        validated_channel,
    )

    if _is_frozen():
        argument_vector = internal_args
        working_directory = resolved_base
    else:
        resolved_launcher_entry = _resolved_existing_file(launcher_entry, "source launcher entry")
        expected_launcher_entry = (resolved_base / "launcher.pyw").resolve()
        if resolved_launcher_entry != expected_launcher_entry:
            raise ValueError("source launcher entry must be the launcher.pyw file under base")
        argument_vector = (str(resolved_launcher_entry), *internal_args)
        working_directory = resolved_base

    return ElevatedLaunchCommand(
        executable=executable,
        parameters=subprocess.list2cmdline(list(argument_vector)),
        working_directory=working_directory.resolve(),
        argument_vector=tuple(argument_vector),
    )


def is_current_process_elevated() -> bool | None:
    """Return current-token administrator state, or ``None`` when unavailable."""

    if not _is_windows():
        return None
    kernel32 = _windows_dll("kernel32")
    advapi32 = _windows_dll("advapi32")
    if kernel32 is None or advapi32 is None:
        return None
    get_current_process = getattr(kernel32, "GetCurrentProcess", None)
    close_handle = getattr(kernel32, "CloseHandle", None)
    open_process_token = getattr(advapi32, "OpenProcessToken", None)
    get_token_information = getattr(advapi32, "GetTokenInformation", None)
    if None in (
        get_current_process,
        close_handle,
        open_process_token,
        get_token_information,
    ):
        return None

    with contextlib.suppress(AttributeError, TypeError):
        get_current_process.argtypes = []
        get_current_process.restype = wintypes.HANDLE
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        open_process_token.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        open_process_token.restype = wintypes.BOOL
        get_token_information.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        get_token_information.restype = wintypes.BOOL

    token_handle = wintypes.HANDLE()
    try:
        process_handle = get_current_process()
        if not open_process_token(process_handle, TOKEN_QUERY, ctypes.byref(token_handle)):
            return None
        elevation = TOKEN_ELEVATION()
        returned_length = wintypes.DWORD()
        if not get_token_information(
            token_handle,
            TOKEN_INFORMATION_CLASS_ELEVATION,
            ctypes.byref(elevation),
            ctypes.sizeof(elevation),
            ctypes.byref(returned_length),
        ):
            return None
        return bool(elevation.TokenIsElevated)
    except OSError, AttributeError, TypeError:
        return None
    finally:
        if token_handle.value:
            with contextlib.suppress(OSError, TypeError, ValueError):
                close_handle(token_handle)


def request_elevated_app(
    *,
    launcher_entry: Path,
    base: Path,
    channel: str,
) -> ElevationResult:
    """Request a fixed elevated app-only launcher process with ``runas``."""

    validated_channel = _validate_channel(channel)
    if not _is_windows():
        return ElevationResult(
            ElevationStatus.UNSUPPORTED,
            error_message="Windows elevation is unavailable on this platform.",
        )

    shell32 = _windows_dll("shell32")
    kernel32 = _windows_dll("kernel32")
    if shell32 is None or kernel32 is None:
        return ElevationResult(
            ElevationStatus.UNSUPPORTED,
            error_message="Windows ShellExecute APIs are unavailable.",
        )

    try:
        command = build_elevated_app_command(
            launcher_entry=launcher_entry,
            base=base,
            channel=validated_channel,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return ElevationResult(ElevationStatus.FAILED, error_message=str(exc))

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = str(command.executable)
    info.lpParameters = command.parameters
    info.lpDirectory = str(command.working_directory)
    info.nShow = SW_SHOWNORMAL

    shell_execute = getattr(shell32, "ShellExecuteExW", None)
    get_last_error = getattr(kernel32, "GetLastError", None)
    if shell_execute is None or get_last_error is None:
        return ElevationResult(
            ElevationStatus.UNSUPPORTED,
            error_message="Windows ShellExecute APIs are unavailable.",
        )

    with contextlib.suppress(AttributeError, TypeError):
        shell_execute.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
        shell_execute.restype = wintypes.BOOL
        get_last_error.argtypes = []
        get_last_error.restype = wintypes.DWORD

    try:
        success = bool(shell_execute(ctypes.byref(info)))
    except (OSError, TypeError, ValueError) as exc:
        return ElevationResult(ElevationStatus.FAILED, error_message=str(exc))

    if not success:
        try:
            get_saved_last_error = getattr(ctypes, "get_last_error", None)
            error_code = int(get_saved_last_error()) if get_saved_last_error else 0
            if not error_code:
                error_code = int(get_last_error())
        except OSError, TypeError, ValueError:
            error_code = 0
        status = (
            ElevationStatus.CANCELLED if error_code == ERROR_CANCELLED else ElevationStatus.FAILED
        )
        message = (
            "User cancelled the Windows elevation request."
            if status is ElevationStatus.CANCELLED
            else f"ShellExecuteExW failed with Win32 error {error_code}."
        )
        return ElevationResult(status, error_code=error_code or None, error_message=message)

    process_handle = info.hProcess
    close_handle = getattr(kernel32, "CloseHandle", None)
    if process_handle and close_handle is not None:
        with contextlib.suppress(OSError, TypeError, ValueError):
            close_handle(process_handle)
    return ElevationResult(ElevationStatus.STARTED)
