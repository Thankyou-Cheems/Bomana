"""Runtime application helpers for SettingsDialog saves."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from bomana.config.settings import (
    BombConfig,
    HotkeyConfig,
    OverspeedConfig,
    PanelConfig,
    SnapConfig,
    SoundConfig,
    UIConfig,
)
from bomana.ui.theme import Theme


class SettingsRuntimeMixin:
    """Behavior-preserving runtime side effects used after settings are persisted."""

    def _capture_runtime_settings_state(self) -> dict[str, Any]:
        return {
            "scale": float(UIConfig.UI_SCALE_MULT),
            "text_scale": float(UIConfig.TEXT_SCALE_MULT),
            "nav_width": float(PanelConfig.navigation_bar_width),
            "nav_scale": float(PanelConfig.navigation_bar_scale),
            "sound_enabled": bool(self.app.sound.is_enabled()),
            "zone_sound_enabled": bool(getattr(self.app, "_zone_sound_enabled", True)),
            "hotkeys_enabled": HotkeyConfig.GLOBAL_HOTKEYS,
            "hotkey_bindings": HotkeyConfig.get_bindings(),
            "theme": Theme.get_current(),
        }

    def _rollback_created_sound_files(self, created_sound_files: list[Path]) -> None:
        for path in created_sound_files:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)

    def _apply_runtime_settings(
        self,
        *,
        new_window_alpha: int,
        new_nav_width: float,
        new_nav_scale: float,
        new_ui_scale: float,
        new_text_scale: float,
        panel_config: dict[str, object],
        new_hotkeys_enabled: bool,
        hotkey_bindings: dict[str, str],
        new_snap_enabled: bool,
        new_snap_distance: int,
        new_sound_enabled: bool,
        new_zone_sound_enabled: bool,
        normalized_sound_overrides: dict[str, str],
        normalized_overspeed_thresholds: dict[str, float],
        normalized_overspeed_overrides: dict[str, dict[str, float]],
        pending_selected_bomb: str | None,
    ) -> None:
        UIConfig.WINDOW_ALPHA = new_window_alpha
        PanelConfig.navigation_bar_width = new_nav_width
        PanelConfig.navigation_bar_scale = new_nav_scale
        UIConfig.UI_SCALE_MULT = new_ui_scale
        UIConfig.TEXT_SCALE_MULT = new_text_scale
        for key, value in panel_config.items():
            setattr(PanelConfig, key, value)
        HotkeyConfig.GLOBAL_HOTKEYS = new_hotkeys_enabled
        HotkeyConfig.set_bindings(hotkey_bindings)
        self.app.runtime_services.refresh_local_hotkey_bindings()
        SnapConfig.enabled = new_snap_enabled
        SnapConfig.SNAP_DISTANCE = new_snap_distance
        self.app.sound.set_enabled(new_sound_enabled)
        self.app._zone_sound_enabled = new_zone_sound_enabled
        SoundConfig.apply_user_config(normalized_sound_overrides)
        OverspeedConfig.apply_user_thresholds(
            normalized_overspeed_thresholds,
            normalized_overspeed_overrides,
        )
        if hasattr(self.app, "_refresh_overspeed_threshold_ui"):
            self.app._refresh_overspeed_threshold_ui()
        if pending_selected_bomb:
            BombConfig.selected_bomb = pending_selected_bomb
