"""Runtime application helpers for SettingsDialog saves."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from bomana.config.settings import (
    BallisticPhysicsParams,
    BombConfig,
    HotkeyConfig,
    HUDConfig,
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
            "hud_enabled": bool(HUDConfig.enabled),
            "hud_alpha": int(HUDConfig.alpha),
            "hud_scale": float(HUDConfig.scale),
            "hud_follow_main": bool(HUDConfig.follow_main_window_monitor),
            "hud_color_style": str(getattr(HUDConfig, "color_style", "auto")),
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
        new_ui_scale: float,
        new_text_scale: float,
        new_hud_enabled: bool,
        pending_hud_config: dict[str, object],
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
        pending_ccrp_tuning: dict[str, float] | None,
        pending_selected_bomb: str | None,
    ) -> None:
        UIConfig.WINDOW_ALPHA = new_window_alpha
        PanelConfig.navigation_bar_width = new_nav_width
        UIConfig.UI_SCALE_MULT = new_ui_scale
        UIConfig.TEXT_SCALE_MULT = new_text_scale
        HUDConfig.enabled = new_hud_enabled
        HUDConfig.apply_dict(pending_hud_config)
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
        if pending_ccrp_tuning is not None:
            BallisticPhysicsParams.apply_user_tuning(pending_ccrp_tuning)
        if pending_selected_bomb:
            BombConfig.selected_bomb = pending_selected_bomb
            if hasattr(self.app, "bomb_select_lbl"):
                self.app.bomb_select_lbl.config(
                    text=f"炸弹: {BombConfig.format_bomb_name(pending_selected_bomb)} (点击更换)"
                )

    def _refresh_runtime_hud_after_settings(self, previous: dict[str, object]) -> None:
        hud_enabled_changed = bool(previous["hud_enabled"]) != bool(HUDConfig.enabled)
        hud_alpha_changed = int(previous["hud_alpha"]) != int(HUDConfig.alpha)
        hud_scale_changed = abs(float(HUDConfig.scale) - float(previous["hud_scale"])) > 1e-6
        hud_follow_changed = bool(previous["hud_follow_main"]) != bool(
            HUDConfig.follow_main_window_monitor
        )
        hud_color_changed = str(previous["hud_color_style"]) != str(HUDConfig.color_style)

        if HUDConfig.enabled:
            if hasattr(self.app, "_show_hud_overlay"):
                self.app._show_hud_overlay()
            if getattr(self.app, "hud_overlay", None):
                if hud_follow_changed:
                    self.app.hud_overlay.refresh_monitor_geometry()
                if hud_scale_changed and hasattr(self.app.hud_overlay, "refresh_text_scale"):
                    self.app.hud_overlay.refresh_text_scale()
                self.app.hud_overlay.update_transparency()
        else:
            if getattr(self.app, "hud_overlay", None) and self.app.hud_overlay.is_visible():
                self.app.hud_overlay.hide()
            if hasattr(self.app, "_hud_last_target"):
                self.app._hud_last_target = None

        if hud_enabled_changed or hud_alpha_changed or hud_color_changed:
            if hasattr(self.app, "_update_hint"):
                self.app._update_hint()
            if hasattr(self.app, "_refresh_tray"):
                self.app._refresh_tray()
