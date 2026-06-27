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


def test_global_hotkeys_stop_sets_event_before_thread_id_exists(monkeypatch) -> None:
    class FakeThread:
        def __init__(self) -> None:
            self.join_timeout = None

        def join(self, timeout: float) -> None:
            self.join_timeout = timeout

    manager = system.GlobalHotkeys(object(), [])
    thread = FakeThread()
    manager._thread = thread
    manager._tid = None
    monkeypatch.setattr(system.os, "name", "nt")

    manager.stop()

    assert manager._stop_event.is_set()
    assert thread.join_timeout == 1.0
