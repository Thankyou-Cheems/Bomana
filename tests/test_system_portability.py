import time
import tkinter as tk

import pytest

from bomana.utils import system


def test_win32_helpers_degrade_without_windll(monkeypatch) -> None:
    monkeypatch.delattr(system.ctypes, "windll", raising=False)
    monkeypatch.setattr(system.Win32, "user32", None)
    monkeypatch.setattr(system.Win32, "kernel32", None)

    system.Win32.enable_dpi()
    system.Win32.hide_console()
    system.SingleInstanceManager.ensure_single_instance_or_exit()
    system.SingleInstanceManager.release()

    assert system.Win32.get_dpi_scale(0) == 1.0
    assert system.Win32.screen_size() == (1920, 1080)
    assert system.Win32.setup_window(0, click_through=True) is False
    assert system.Win32.get_all_monitors() == [
        {"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080, "is_primary": True}
    ]


def test_setup_window_reports_layered_attribute_failure(monkeypatch) -> None:
    class FakeKernel32:
        def __init__(self) -> None:
            self.last_error = 0

        def SetLastError(self, value: int) -> None:
            self.last_error = value

        def GetLastError(self) -> int:
            return self.last_error

    class FakeUser32:
        def GetWindowLongW(self, _hwnd, _index) -> int:
            return 1

        def SetWindowLongW(self, _hwnd, _index, _style) -> int:
            return 1

        def SetLayeredWindowAttributes(self, _hwnd, _key, _alpha, _flags) -> bool:
            return False

    monkeypatch.setattr(system.Win32, "user32", FakeUser32())
    monkeypatch.setattr(system.Win32, "kernel32", FakeKernel32())

    assert system.Win32.setup_window(100, click_through=True) is False


def test_setup_window_reports_set_window_long_failure(monkeypatch) -> None:
    class FakeKernel32:
        def __init__(self) -> None:
            self.last_error = 0

        def SetLastError(self, value: int) -> None:
            self.last_error = value

        def GetLastError(self) -> int:
            return self.last_error

    class FakeUser32:
        def __init__(self, kernel32: FakeKernel32) -> None:
            self.kernel32 = kernel32

        def GetWindowLongW(self, _hwnd, _index) -> int:
            return 1

        def SetWindowLongW(self, _hwnd, _index, _style) -> int:
            self.kernel32.last_error = 5
            return 0

        def SetLayeredWindowAttributes(self, _hwnd, _key, _alpha, _flags) -> bool:
            raise AssertionError("style failure should stop before layered attributes")

    kernel32 = FakeKernel32()
    monkeypatch.setattr(system.Win32, "user32", FakeUser32(kernel32))
    monkeypatch.setattr(system.Win32, "kernel32", kernel32)

    assert system.Win32.setup_window(100, click_through=True) is False


def test_global_hotkeys_register_against_message_window_and_dispatch_errors(monkeypatch) -> None:
    class FakeUser32:
        def __init__(self) -> None:
            self.registered: list[tuple[int, int, int, int]] = []
            self.unregistered: list[tuple[int, int]] = []

        def RegisterHotKey(self, hwnd, hotkey_id, modifiers, vk) -> bool:
            self.registered.append((hwnd, hotkey_id, modifiers, vk))
            return hotkey_id == 1

        def UnregisterHotKey(self, hwnd, hotkey_id) -> bool:
            self.unregistered.append((hwnd, hotkey_id))
            return True

    dispatched: list[tuple[object, tuple[object, ...]]] = []
    errors: list[tuple[str, ...]] = []
    destroyed: list[int] = []
    manager = system.GlobalHotkeys(
        lambda callback, *args: dispatched.append((callback, args)),
        [(1, "F8", lambda: None), (2, "F9", lambda: None)],
        error_cb=errors.append,
    )
    fake_user32 = FakeUser32()
    monkeypatch.setattr(system.os, "name", "nt")
    monkeypatch.setattr(system.Win32, "user32", fake_user32)
    monkeypatch.setattr(
        manager, "_create_message_window", lambda: setattr(manager, "_message_hwnd", 99)
    )

    def destroy_message_window() -> None:
        destroyed.append(manager._message_hwnd or 0)
        manager._message_hwnd = None

    monkeypatch.setattr(manager, "_destroy_message_window", destroy_message_window)

    manager.start()

    assert fake_user32.registered == [
        (99, 1, system.GlobalHotkeys.MOD_NOREPEAT, 0x77),
        (99, 2, system.GlobalHotkeys.MOD_NOREPEAT, 0x78),
    ]
    assert errors == []
    error_callback, error_args = dispatched.pop()
    error_callback(*error_args)
    assert errors == [("F9",)]

    manager.stop()

    assert fake_user32.unregistered == [(99, 1)]
    assert destroyed == [99]


def test_global_hotkeys_wm_hotkey_queues_callback_without_calling_it() -> None:
    dispatched: list[tuple[object, tuple[object, ...]]] = []
    called: list[str] = []

    def callback() -> None:
        called.append("hotkey")

    manager = system.GlobalHotkeys(
        lambda queued, *args: dispatched.append((queued, args)),
        [(1, "F8", callback)],
    )

    manager._dispatch_hotkey(1)

    assert called == []
    assert dispatched == [(manager._deliver_hotkey, (1, "F8", callback))]
    queued, args = dispatched[0]
    queued(*args)
    assert called == ["hotkey"]


def test_global_hotkeys_window_failure_queues_registration_error(monkeypatch) -> None:
    dispatched: list[tuple[object, tuple[object, ...]]] = []
    errors: list[tuple[str, ...]] = []
    manager = system.GlobalHotkeys(
        lambda callback, *args: dispatched.append((callback, args)),
        [(1, "F8", lambda: None), (2, "F9", lambda: None)],
        error_cb=errors.append,
    )

    def fail_create() -> None:
        raise OSError("message window unavailable")

    monkeypatch.setattr(system.os, "name", "nt")
    monkeypatch.setattr(manager, "_create_message_window", fail_create)

    manager.start()

    assert errors == []
    assert len(dispatched) == 1
    error_callback, error_args = dispatched[0]
    error_callback(*error_args)
    assert errors == [("F8", "F9")]


def test_global_hotkeys_keeps_wndproc_alive_when_window_destroy_fails(monkeypatch) -> None:
    class FakeUser32:
        def DestroyWindow(self, _hwnd) -> bool:
            return False

        def UnregisterClassW(self, _class_name, _module_handle) -> bool:
            raise AssertionError("window class must stay registered while the HWND exists")

    manager = system.GlobalHotkeys(lambda _callback, *_args: None, [])
    wndproc = object()
    manager._message_hwnd = 99
    manager._module_handle = 100
    manager._window_class_name = "Bomana.GlobalHotkeys.test"
    manager._wndproc = wndproc
    monkeypatch.setattr(system.Win32, "user32", FakeUser32())
    monkeypatch.setattr(
        system.ctypes,
        "WinError",
        lambda: OSError("DestroyWindow failed"),
        raising=False,
    )

    with pytest.raises(OSError, match="DestroyWindow failed"):
        manager._destroy_message_window()

    assert manager._message_hwnd == 99
    assert manager._window_class_name == "Bomana.GlobalHotkeys.test"
    assert manager._wndproc is wndproc


@pytest.mark.skipif(system.os.name != "nt", reason="Win32 message-window integration")
def test_global_hotkeys_real_message_window_receives_wm_hotkey() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    dispatched: list[tuple[object, tuple[object, ...]]] = []
    called: list[str] = []

    def callback() -> None:
        called.append("hotkey")

    manager = system.GlobalHotkeys(
        lambda queued, *args: dispatched.append((queued, args)),
        [(4242, "F8", callback)],
    )

    try:
        manager._create_message_window()
        hwnd = manager._message_hwnd
        assert hwnd is not None
        post_message = system.Win32.user32.PostMessageW
        post_message.argtypes = [
            system.ctypes.c_void_p,
            system.ctypes.c_uint,
            system.ctypes.c_size_t,
            system.ctypes.c_ssize_t,
        ]
        post_message.restype = system.ctypes.c_bool
        assert post_message(hwnd, system.GlobalHotkeys.WM_HOTKEY, 4242, 0)

        deadline = time.monotonic() + 2.0
        while not dispatched and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)

        assert called == []
        assert dispatched == [(manager._deliver_hotkey, (4242, "F8", callback))]
        queued, args = dispatched[0]
        queued(*args)
        assert called == ["hotkey"]
    finally:
        manager._destroy_message_window()
        root.destroy()
