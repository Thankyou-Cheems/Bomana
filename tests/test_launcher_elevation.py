from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest

from launcher import elevation


class FakeShell32:
    def __init__(self, *, success: bool, elevated: bool = False) -> None:
        self.success = success
        self.elevated = elevated
        self.calls: list[dict[str, object]] = []

    def IsUserAnAdmin(self) -> bool:
        return self.elevated

    def ShellExecuteExW(self, info_pointer) -> bool:
        info = info_pointer._obj
        self.calls.append(
            {
                "verb": info.lpVerb,
                "file": info.lpFile,
                "parameters": info.lpParameters,
                "directory": info.lpDirectory,
                "mask": info.fMask,
            }
        )
        if self.success:
            info.hProcess = 9876
        return self.success


class FakeKernel32:
    def __init__(self, error_code: int = 0) -> None:
        self.error_code = error_code
        self.closed_handles: list[int] = []

    def GetLastError(self) -> int:
        return self.error_code

    def GetCurrentProcess(self) -> int:
        return 1234

    def CloseHandle(self, handle) -> bool:
        value = getattr(handle, "value", handle)
        self.closed_handles.append(int(value))
        return True


class FakeAdvapi32:
    def __init__(self, *, elevated: bool) -> None:
        self.elevated = elevated

    def OpenProcessToken(self, process_handle, desired_access, token_pointer) -> bool:
        assert process_handle == 1234
        assert desired_access == elevation.TOKEN_QUERY
        token_pointer._obj.value = 4321
        return True

    def GetTokenInformation(
        self,
        token_handle,
        information_class,
        information_pointer,
        information_size,
        returned_length_pointer,
    ) -> bool:
        assert token_handle.value == 4321
        assert information_class == elevation.TOKEN_INFORMATION_CLASS_ELEVATION
        assert information_size == elevation.ctypes.sizeof(elevation.TOKEN_ELEVATION)
        information_pointer._obj.TokenIsElevated = int(self.elevated)
        returned_length_pointer._obj.value = information_size
        return True


def install_fake_windows(
    monkeypatch: pytest.MonkeyPatch,
    *,
    shell32: FakeShell32,
    kernel32: FakeKernel32,
    advapi32: FakeAdvapi32 | None = None,
) -> None:
    monkeypatch.setattr(elevation, "_is_windows", lambda: True)
    monkeypatch.setattr(
        elevation,
        "_windows_dll",
        lambda name: {
            "shell32": shell32,
            "kernel32": kernel32,
            "advapi32": advapi32,
        }.get(name),
    )


def make_frozen_launcher(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    executable = tmp_path / "Bomana launcher.exe"
    executable.touch()
    monkeypatch.setattr(elevation.sys, "executable", str(executable))
    monkeypatch.setattr(elevation, "_is_frozen", lambda: True)
    return executable.resolve()


@pytest.mark.parametrize("value", [True, False])
def test_current_process_elevation_uses_current_token(
    monkeypatch: pytest.MonkeyPatch,
    value: bool,
) -> None:
    shell32 = FakeShell32(success=False, elevated=value)
    kernel32 = FakeKernel32()
    install_fake_windows(
        monkeypatch,
        shell32=shell32,
        kernel32=kernel32,
        advapi32=FakeAdvapi32(elevated=value),
    )

    assert elevation.is_current_process_elevated() is value
    assert kernel32.closed_handles == [4321]


def test_current_process_elevation_is_unknown_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(elevation, "_is_windows", lambda: False)

    assert elevation.is_current_process_elevated() is None


def test_request_elevated_app_reports_started_and_closes_process_handle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = make_frozen_launcher(monkeypatch, tmp_path)
    shell32 = FakeShell32(success=True)
    kernel32 = FakeKernel32()
    install_fake_windows(monkeypatch, shell32=shell32, kernel32=kernel32)

    result = elevation.request_elevated_app(
        launcher_entry=tmp_path / "unused-launcher.pyw",
        base=tmp_path,
        channel="Enhanced",
    )

    assert result == elevation.ElevationResult(elevation.ElevationStatus.STARTED)
    assert shell32.calls == [
        {
            "verb": "runas",
            "file": str(executable),
            "parameters": subprocess.list2cmdline(
                ["--bomana-elevated-app", "--channel", "Enhanced"]
            ),
            "directory": str(executable.parent),
            "mask": elevation.SEE_MASK_NOCLOSEPROCESS,
        }
    ]
    assert kernel32.closed_handles == [9876]


def test_request_elevated_app_reports_uac_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    make_frozen_launcher(monkeypatch, tmp_path)
    shell32 = FakeShell32(success=False)
    kernel32 = FakeKernel32(elevation.ERROR_CANCELLED)
    install_fake_windows(monkeypatch, shell32=shell32, kernel32=kernel32)

    result = elevation.request_elevated_app(
        launcher_entry=tmp_path / "unused-launcher.pyw",
        base=tmp_path,
        channel="Standard",
    )

    assert result == elevation.ElevationResult(
        elevation.ElevationStatus.CANCELLED,
        error_code=elevation.ERROR_CANCELLED,
        error_message="User cancelled the Windows elevation request.",
    )


def test_request_elevated_app_reports_other_shell_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    make_frozen_launcher(monkeypatch, tmp_path)
    shell32 = FakeShell32(success=False)
    kernel32 = FakeKernel32(5)
    install_fake_windows(monkeypatch, shell32=shell32, kernel32=kernel32)

    result = elevation.request_elevated_app(
        launcher_entry=tmp_path / "unused-launcher.pyw",
        base=tmp_path,
        channel="Lite",
    )

    assert result == elevation.ElevationResult(
        elevation.ElevationStatus.FAILED,
        error_code=5,
        error_message="ShellExecuteExW failed with Win32 error 5.",
    )


def test_request_elevated_app_is_unsupported_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(elevation, "_is_windows", lambda: False)

    assert elevation.request_elevated_app(
        launcher_entry=Path("launcher.pyw"),
        base=Path.cwd(),
        channel="Enhanced",
    ) == elevation.ElevationResult(
        elevation.ElevationStatus.UNSUPPORTED,
        error_message="Windows elevation is unavailable on this platform.",
    )


def test_source_command_quotes_absolute_unicode_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "测试 路径" / "Bomana [source]"
    launcher_package = repo / "launcher"
    launcher_package.mkdir(parents=True)
    launcher_module = launcher_package / "elevation.py"
    launcher_module.touch()
    launcher_entry = repo / "launcher.pyw"
    launcher_entry.touch()
    python_exe = repo / ".venv" / "Scripts" / "pythonw.exe"
    python_exe.parent.mkdir(parents=True)
    python_exe.touch()

    monkeypatch.setattr(elevation, "__file__", str(launcher_module))
    monkeypatch.setattr(elevation.sys, "executable", str(python_exe))
    monkeypatch.setattr(elevation, "_is_frozen", lambda: False)

    command = elevation.build_elevated_app_command(
        launcher_entry=launcher_entry,
        base=repo,
        channel="Enhanced",
    )

    expected_args = (
        str(launcher_entry.resolve()),
        "--bomana-elevated-app",
        "--channel",
        "Enhanced",
    )
    assert command.executable == python_exe.resolve()
    assert command.working_directory == repo.resolve()
    assert command.argument_vector == expected_args
    assert command.parameters == subprocess.list2cmdline(list(expected_args))
    assert "测试 路径" in command.parameters


@pytest.mark.parametrize(
    "args",
    [
        ["--bomana-elevated-app"],
        ["--bomana-elevated-app", "--channel", "enhanced"],
        ["--bomana-elevated-app", "--channel", "Enhanced", "--extra"],
        ["--bomana-elevated-app", "--entrypoint", "Bomana.pyw"],
    ],
)
def test_internal_app_only_parser_rejects_invalid_or_arbitrary_args(args: list[str]) -> None:
    with pytest.raises(ValueError):
        elevation.parse_elevated_app_request(args, sorted(elevation.ALLOWED_CHANNELS))


def test_arbitrary_entrypoint_args_do_not_activate_internal_mode() -> None:
    assert (
        elevation.parse_elevated_app_request(
            ["--entrypoint", "evil.pyw", "--channel", "Enhanced"],
            sorted(elevation.ALLOWED_CHANNELS),
        )
        is None
    )


@pytest.mark.parametrize("channel", sorted(elevation.ALLOWED_CHANNELS))
def test_internal_app_only_parser_accepts_only_allowlisted_channels(channel: str) -> None:
    request = elevation.parse_elevated_app_request(
        ["--bomana-elevated-app", "--channel", channel],
        sorted(elevation.ALLOWED_CHANNELS),
    )

    assert request == channel


def test_normal_launcher_args_are_not_internal_app_only() -> None:
    assert elevation.parse_elevated_app_request([], sorted(elevation.ALLOWED_CHANNELS)) is None


def test_command_builder_has_no_arbitrary_entrypoint_parameter() -> None:
    parameters = inspect.signature(elevation.build_elevated_app_command).parameters
    request_parameters = inspect.signature(elevation.request_elevated_app).parameters

    assert tuple(parameters) == ("launcher_entry", "base", "channel")
    assert tuple(request_parameters) == ("launcher_entry", "base", "channel")
    assert not hasattr(elevation, "DEFAULT_ENTRYPOINT")
