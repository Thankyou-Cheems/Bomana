from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_experimental_desktop_hud_modules_are_absent() -> None:
    retired_paths = (
        ROOT / "bomana" / "ui" / "hud_overlay.py",
        ROOT / "bomana" / "ui" / "hud_presenter.py",
        ROOT / "tools" / "sample_8111_attitude.py",
    )

    assert not [path for path in retired_paths if path.exists()]


def test_desktop_runtime_and_settings_have_no_hud_surface() -> None:
    settings_source = (ROOT / "bomana" / "config" / "settings.py").read_text(encoding="utf-8")
    dialogs_source = (ROOT / "bomana" / "ui" / "dialogs.py").read_text(encoding="utf-8")
    runtime_source = (ROOT / "bomana" / "ui" / "runtime_services.py").read_text(encoding="utf-8")
    app_source = (ROOT / "bomana" / "ui" / "app.py").read_text(encoding="utf-8")

    assert "class HUDConfig" not in settings_source
    assert '"实验性"' not in dialogs_source
    assert "hud_overlay" not in dialogs_source
    assert "hud_overlay" not in runtime_source
    assert "hud_overlay" not in app_source
