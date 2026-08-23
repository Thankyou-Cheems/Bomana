from __future__ import annotations

from pathlib import Path


def test_public_editions_expose_desktop_and_tray_encyclopedia_entries() -> None:
    app_source = Path("bomana/ui/app.py").read_text(encoding="utf-8")
    main_source = Path("bomana/ui/main_window.py").read_text(encoding="utf-8")
    tray_source = Path("bomana/ui/runtime_services.py").read_text(encoding="utf-8")

    assert "app.encyclopedia_btn = tk.Button(" in main_source
    assert 'text="百科"' in main_source
    assert 'pystray.MenuItem("打击百科", do_strike_encyclopedia)' in tray_source
    show_method = app_source[app_source.index("def _show_strike_encyclopedia") :]
    show_method = show_method[: show_method.index("\n    def ", 1)]
    assert "ENABLE_CCRP" not in show_method

    ui_source = Path("bomana/ui/strike_encyclopedia.py").read_text(encoding="utf-8")
    assert "EC 目标与武器数量计算器" in ui_source
    assert "StrikeDamageCalculator" in ui_source
    assert "ENABLE_CCRP" not in ui_source
