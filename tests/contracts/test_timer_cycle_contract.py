# enforces: docs/specs/timer-cycle.md TIMER-01..TIMER-03 TIMER-05..TIMER-08

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_timer_bounds_and_default_have_one_config_owner() -> None:
    settings = (ROOT / "bomana/config/settings.py").read_text(encoding="utf-8")
    assert "DEFAULT_CYCLE_MINUTES = 15" in settings
    assert "MIN_CYCLE_MINUTES = 1" in settings
    assert "MAX_CYCLE_MINUTES = 180" in settings
    assert "CYCLE_SECONDS = DEFAULT_CYCLE_MINUTES * 60" in settings


def test_timer_web_schema_has_one_bounded_explicit_command() -> None:
    schema = json.loads(
        (ROOT / "docs/specs/schemas/web-dashboard-command.schema.json").read_text(encoding="utf-8")
    )
    matches = [
        definition
        for definition in schema["$defs"].values()
        if definition.get("properties", {}).get("command", {}).get("const")
        == "config.set_timer_cycle_minutes"
    ]
    assert len(matches) == 1
    assert matches[0]["properties"]["minutes"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 180,
    }


def test_timer_restore_persists_and_checks_exact_cycle_seconds() -> None:
    persistence = (ROOT / "bomana/utils/file_utils.py").read_text(encoding="utf-8")
    assert '"cycle_seconds": GameConfig.CYCLE_SECONDS' in persistence
    assert "saved_cycle_seconds" in persistence
    assert "LEGACY_CYCLE_SECONDS" in persistence


def test_timer_uses_banana_emoji_percent_and_removes_legacy_horizontal_strip() -> None:
    main_window = (ROOT / "bomana/ui/main_window.py").read_text(encoding="utf-8")
    app = (ROOT / "bomana/ui/app.py").read_text(encoding="utf-8")
    widgets = (ROOT / "bomana/ui/widgets.py").read_text(encoding="utf-8")
    assert "BananaProgress" in main_window
    assert "banana_progress.set_progress" in app
    assert "class BananaProgress" in widgets
    assert 'text="🍌"' in widgets
    assert "Segoe UI Emoji" in widgets
    assert "percent_text" in widgets
    assert "progress_arc" in widgets
    assert "banana_silhouette" not in widgets
    assert "banana_outline" not in widgets
    assert "outline_points" not in widgets
    assert "app.bar_bg" not in main_window
    assert "app.bar_fill" not in main_window


def test_timer_warning_thresholds_remain_absolute_seconds() -> None:
    settings = (ROOT / "bomana/config/settings.py").read_text(encoding="utf-8")
    app = (ROOT / "bomana/ui/app.py").read_text(encoding="utf-8")
    assert "FINAL_WARNING_SEC = 30" in settings
    assert "SoundConfig.WARNING_SECONDS" in app


def test_timer_tray_has_presets_and_custom_target() -> None:
    runtime = (ROOT / "bomana/ui/runtime_services.py").read_text(encoding="utf-8")
    assert "计时周期 ·" in runtime
    assert "for minutes in (15, 30, 45, 60)" in runtime
    assert "自定义…" in runtime
    assert "app._prompt_timer_cycle_minutes" in runtime
