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
