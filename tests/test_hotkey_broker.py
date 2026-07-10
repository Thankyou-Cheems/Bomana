from __future__ import annotations

from pathlib import Path

import pytest

from bomana.utils import hotkey_broker

# enforces: docs/specs/startup-elevation.md ELEV-03, ELEV-05, ELEV-07..ELEV-12


def _bindings(calls: list[str] | None = None) -> tuple[hotkey_broker.BrokerBinding, ...]:
    calls = calls if calls is not None else []
    return (
        hotkey_broker.BrokerBinding("reset", "F7", lambda: calls.append("reset")),
        hotkey_broker.BrokerBinding("lock", "F8", lambda: calls.append("lock")),
        hotkey_broker.BrokerBinding("corner", "F9", lambda: calls.append("corner")),
        hotkey_broker.BrokerBinding("beep", "F10", lambda: calls.append("beep")),
        hotkey_broker.BrokerBinding("zones", "F11", lambda: calls.append("zones")),
    )


def test_bundled_broker_path_is_fixed_inside_app_package(tmp_path: Path) -> None:
    path = hotkey_broker.bundled_broker_path(package_directory=tmp_path)

    assert path == tmp_path.resolve() / "bin" / "BomanaHotkeyBroker.exe"


def test_broker_arguments_allow_only_fixed_actions_and_function_keys() -> None:
    arguments = hotkey_broker.build_broker_arguments(
        "1234-0123456789abcdef0123456789abcdef",
        _bindings(),
    )

    assert arguments == (
        "--session",
        "1234-0123456789abcdef0123456789abcdef",
        "--binding",
        "reset=F7",
        "--binding",
        "lock=F8",
        "--binding",
        "corner=F9",
        "--binding",
        "beep=F10",
        "--binding",
        "zones=F11",
    )

    with pytest.raises(ValueError, match="unsupported broker action"):
        hotkey_broker.normalize_bindings(
            (*_bindings()[:4], hotkey_broker.BrokerBinding("shell", "F11", lambda: None))
        )
    with pytest.raises(ValueError, match="must be unique"):
        duplicate = list(_bindings())
        duplicate[-1] = hotkey_broker.BrokerBinding("zones", "F10", lambda: None)
        hotkey_broker.normalize_bindings(duplicate)


def test_decode_frame_accepts_only_fixed_eight_byte_protocol() -> None:
    assert hotkey_broker.decode_frame(b"BHK1\x01\x05\x10\x00") == hotkey_broker.BrokerFrame(
        hotkey_broker.FRAME_READY,
        5,
        0x10,
    )
    assert hotkey_broker.decode_frame(b"BHK1\x02\x02\x00\x00") == hotkey_broker.BrokerFrame(
        hotkey_broker.FRAME_ACTION,
        hotkey_broker.ACTION_IDS["lock"],
        0,
    )

    for invalid in (
        b"short",
        b"EVIL\x02\x02\x00\x00",
        b"BHK1\x02\xff\x00\x00",
        b"BHK1\x03\x01\x00\x00",
    ):
        with pytest.raises(ValueError):
            hotkey_broker.decode_frame(invalid)


def test_find_bundled_broker_rejects_tampered_binary(monkeypatch, tmp_path: Path) -> None:
    broker = tmp_path / "bin" / "BomanaHotkeyBroker.exe"
    broker.parent.mkdir()
    broker.write_bytes(b"original")
    checksum = hotkey_broker.sha256_file(broker)
    broker.with_name(hotkey_broker.BROKER_CHECKSUM_NAME).write_text(
        f"{checksum}  {broker.name}\n",
        encoding="ascii",
    )
    broker.write_bytes(b"tampered")
    monkeypatch.setattr(hotkey_broker, "bundled_broker_path", lambda: broker)

    result = hotkey_broker.find_bundled_broker()

    assert isinstance(result, hotkey_broker.BrokerStartResult)
    assert result.status is hotkey_broker.BrokerStartStatus.UNTRUSTED


def test_war_thunder_integrity_probe_uses_visible_allowlisted_processes(monkeypatch) -> None:
    monkeypatch.setattr(hotkey_broker, "_is_windows", lambda: True)
    monkeypatch.setattr(hotkey_broker, "_visible_window_process_ids", lambda: (11, 22))
    monkeypatch.setattr(
        hotkey_broker,
        "_process_image_name",
        lambda process_id: "notepad.exe" if process_id == 11 else "aces.exe",
    )
    monkeypatch.setattr(hotkey_broker, "_process_is_elevated", lambda process_id: process_id == 22)

    result = hotkey_broker.detect_war_thunder_integrity()

    assert result.status is hotkey_broker.GameIntegrityStatus.ELEVATED
    assert result.process_id == 22
    assert result.image_name == "aces.exe"


def test_war_thunder_integrity_probe_distinguishes_absent_and_unknown(monkeypatch) -> None:
    monkeypatch.setattr(hotkey_broker, "_is_windows", lambda: True)
    monkeypatch.setattr(hotkey_broker, "_visible_window_process_ids", lambda: (31,))
    monkeypatch.setattr(hotkey_broker, "_process_image_name", lambda _pid: "explorer.exe")
    assert (
        hotkey_broker.detect_war_thunder_integrity().status
        is hotkey_broker.GameIntegrityStatus.NOT_RUNNING
    )

    monkeypatch.setattr(hotkey_broker, "_process_image_name", lambda _pid: "aces_be.exe")
    monkeypatch.setattr(
        hotkey_broker,
        "_process_is_elevated",
        lambda _pid: (_ for _ in ()).throw(OSError("access denied")),
    )
    assert (
        hotkey_broker.detect_war_thunder_integrity().status
        is hotkey_broker.GameIntegrityStatus.UNKNOWN
    )


def test_uac_cancellation_cleans_ipc_without_starting_reader(monkeypatch, tmp_path: Path) -> None:
    broker = tmp_path / "BomanaHotkeyBroker.exe"
    broker.write_bytes(b"signed test broker")
    calls: list[tuple[str, int]] = []

    class FakeKernel32:
        def CreateNamedPipeW(self, *_args) -> int:
            return 101

        def CreateEventW(self, *_args) -> int:
            return 102

        def LocalFree(self, _descriptor) -> int:
            return 0

        def SetEvent(self, handle) -> bool:
            calls.append(("set", int(handle.value)))
            return True

        def DisconnectNamedPipe(self, handle) -> bool:
            calls.append(("disconnect", int(handle.value)))
            return True

        def CloseHandle(self, handle) -> bool:
            calls.append(("close", int(handle.value)))
            return True

    fake_kernel32 = FakeKernel32()
    monkeypatch.setattr(hotkey_broker, "_is_windows", lambda: True)
    monkeypatch.setattr(hotkey_broker, "find_bundled_broker", lambda: broker)
    monkeypatch.setattr(hotkey_broker, "_lock_broker_file", lambda _path: 103)
    monkeypatch.setattr(hotkey_broker, "verify_bundled_broker", lambda _path: True)
    monkeypatch.setattr(
        hotkey_broker,
        "_security_attributes",
        lambda: (hotkey_broker.SECURITY_ATTRIBUTES(), hotkey_broker.wintypes.LPVOID()),
    )
    monkeypatch.setattr(
        hotkey_broker,
        "_request_runas",
        lambda *_args: hotkey_broker.BrokerStartResult(
            hotkey_broker.BrokerStartStatus.CANCELLED,
            "cancelled",
            hotkey_broker.ERROR_CANCELLED,
        ),
    )
    monkeypatch.setattr(
        hotkey_broker,
        "_windows_dll",
        lambda name: fake_kernel32 if name == "kernel32" else None,
    )

    client = hotkey_broker.ElevatedHotkeyBrokerClient(
        lambda _callback, *_args: None,
        _bindings(),
        ready_cb=lambda _failed: None,
        failure_cb=lambda _message: None,
    )
    result = client.start()

    assert result.status is hotkey_broker.BrokerStartStatus.CANCELLED
    assert client._reader_thread is None
    assert ("set", 102) in calls
    assert ("disconnect", 101) in calls
    assert ("close", 101) in calls
    assert ("close", 102) in calls
    assert ("close", 103) in calls


def test_broker_frames_dispatch_callbacks_only_through_dispatcher() -> None:
    dispatched: list[tuple[object, tuple[object, ...]]] = []
    action_calls: list[str] = []
    ready_calls: list[tuple[str, ...]] = []
    client = hotkey_broker.ElevatedHotkeyBrokerClient(
        lambda callback, *args: dispatched.append((callback, args)),
        _bindings(action_calls),
        ready_cb=ready_calls.append,
        failure_cb=lambda _message: None,
    )

    client._dispatch_frame(hotkey_broker.BrokerFrame(hotkey_broker.FRAME_READY, 4, 0x10))
    client._dispatch_frame(
        hotkey_broker.BrokerFrame(
            hotkey_broker.FRAME_ACTION,
            hotkey_broker.ACTION_IDS["lock"],
            0,
        )
    )

    assert ready_calls == []
    assert action_calls == []
    assert len(dispatched) == 2
    for callback, args in dispatched:
        callback(*args)
    assert ready_calls == [("F11",)]
    assert action_calls == ["lock"]


def test_broken_pipe_before_ready_dispatches_visible_failure(monkeypatch) -> None:
    dispatched: list[tuple[object, tuple[object, ...]]] = []
    failures: list[str] = []

    class FakeFunction:
        def __init__(self, callback) -> None:
            self.callback = callback
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            return self.callback(*args)

    class FakeKernel32:
        def __init__(self) -> None:
            self.ConnectNamedPipe = FakeFunction(lambda *_args: True)
            self.ReadFile = FakeFunction(self._read_file)

        @staticmethod
        def _read_file(*_args) -> bool:
            hotkey_broker.ctypes.set_last_error(hotkey_broker.ERROR_BROKEN_PIPE)
            return False

    client = hotkey_broker.ElevatedHotkeyBrokerClient(
        lambda callback, *args: dispatched.append((callback, args)),
        _bindings(),
        ready_cb=lambda _failed: None,
        failure_cb=failures.append,
    )
    client._pipe_handle = 101
    monkeypatch.setattr(
        hotkey_broker,
        "_windows_dll",
        lambda name: FakeKernel32() if name == "kernel32" else None,
    )

    client._read_frames()

    assert failures == []
    assert len(dispatched) == 1
    callback, args = dispatched[0]
    callback(*args)
    assert len(failures) == 1
    assert "109" in failures[0]


def test_broker_start_timeout_stops_session_and_dispatches_failure(monkeypatch) -> None:
    dispatched: list[tuple[object, tuple[object, ...]]] = []
    failures: list[str] = []
    client = hotkey_broker.ElevatedHotkeyBrokerClient(
        lambda callback, *args: dispatched.append((callback, args)),
        _bindings(),
        ready_cb=lambda _failed: None,
        failure_cb=failures.append,
    )
    stopped: list[bool] = []
    monkeypatch.setattr(client, "stop", lambda: stopped.append(True))

    client._handle_start_timeout()

    assert stopped == [True]
    assert failures == []
    callback, args = dispatched[0]
    callback(*args)
    assert "限定时间" in failures[0]
