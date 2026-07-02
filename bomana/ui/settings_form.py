"""Headless settings-dialog form collection and validation helpers."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass

from bomana.config import (
    HUDConfig,
    OverspeedConfig,
    UIConfig,
)

NUMERIC_PARSE_ERRORS = (TypeError, ValueError, tk.TclError)
OVERSPEED_FIELD_LABELS = {
    "caution_ratio": "IAS 提示线",
    "warning_ratio": "IAS 警告线",
    "critical_ratio": "IAS 危险线",
    "mach_caution_margin": "Mach 提示线",
    "mach_warning_margin": "Mach 警告线",
    "mach_critical_margin": "Mach 危险线",
}
CCRP_TUNING_FIELD_LABELS = {
    "range_correction_mult": "CCRP 距离修正倍率",
    "time_correction_mult": "CCRP 时间修正倍率",
}
HUD_COLOR_STYLES = {"auto", "green", "amber", "cyan", "white"}
HOTKEY_ACTION_LABELS = {
    "reset": "重置计时器",
    "lock": "锁定/解锁",
    "corner": "切换角落",
    "beep": "声音开关",
    "zones": "战区提示音",
}


@dataclass(frozen=True, slots=True)
class SettingsSavePayload:
    window_alpha: int
    nav_width: float
    ui_scale: float
    text_scale: float
    theme: str
    hud_enabled: bool
    hud_config: dict[str, object]
    hotkeys_enabled: bool
    hotkey_bindings: dict[str, str]
    panel_config: dict[str, object]
    snap_enabled: bool
    snap_distance: int
    sound_enabled: bool
    zone_sound_enabled: bool
    overspeed_thresholds: dict[str, float]
    overspeed_overrides: dict[str, dict[str, float]]
    ccrp_tuning: dict[str, float] | None
    selected_bomb: str | None


def collect_numeric_var_values(
    vars_by_key: dict, labels_by_key: dict[str, str]
) -> dict[str, float]:
    values = {}
    for key, var in vars_by_key.items():
        try:
            values[key] = float(var.get())
        except NUMERIC_PARSE_ERRORS as exc:
            label = labels_by_key.get(key, str(key))
            raise ValueError(f"{label} 必须输入有效数字。") from exc
    return values


def collect_hotkey_bindings(hotkey_vars: dict[str, object]) -> dict[str, str]:
    hotkey_bindings = {key: str(var.get() or "").strip() for key, var in hotkey_vars.items()}
    key_to_actions: dict[str, list[str]] = {}
    for action, key_name in hotkey_bindings.items():
        if not key_name:
            continue
        key_to_actions.setdefault(key_name, []).append(action)

    duplicate_groups = [
        (key_name, actions) for key_name, actions in key_to_actions.items() if len(actions) > 1
    ]
    if duplicate_groups:
        details = []
        for key_name, actions in duplicate_groups:
            labels = "、".join(HOTKEY_ACTION_LABELS.get(action, action) for action in actions)
            details.append(f"{key_name}: {labels}")
        raise ValueError(
            "检测到重复快捷键绑定：\n" + "\n".join(details) + "\n\n请为每个功能选择不同的快捷键。"
        )
    return hotkey_bindings


def collect_overspeed_thresholds(vars_by_key: dict) -> dict[str, float]:
    overspeed_thresholds = collect_numeric_var_values(vars_by_key, OVERSPEED_FIELD_LABELS)
    return OverspeedConfig.normalize_thresholds(overspeed_thresholds)


def normalize_overspeed_overrides(raw_override_map: object) -> dict[str, dict[str, float]]:
    normalized_overspeed_overrides: dict[str, dict[str, float]] = {}
    if not isinstance(raw_override_map, dict):
        return normalized_overspeed_overrides
    for aircraft_key, raw_override in raw_override_map.items():
        aircraft_name = str(aircraft_key or "").strip()
        if not aircraft_name or not isinstance(raw_override, dict):
            continue
        normalized_overspeed_overrides[aircraft_name] = OverspeedConfig.normalize_thresholds(
            raw_override
        )
    return normalized_overspeed_overrides


def collect_ccrp_tuning(range_var: object, time_var: object) -> dict[str, float]:
    return collect_numeric_var_values(
        {
            "range_correction_mult": range_var,
            "time_correction_mult": time_var,
        },
        CCRP_TUNING_FIELD_LABELS,
    )


def normalized_hud_color_style(raw_style: object) -> str:
    color_style = str(raw_style or "auto").strip().lower()
    if color_style not in HUD_COLOR_STYLES:
        return "auto"
    return color_style


def merged_panel_config(existing_config: dict[str, object], panel_vars: dict[str, object]) -> dict:
    existing_panels = existing_config.get("panels", {})
    panel_config = dict(existing_panels) if isinstance(existing_panels, dict) else {}
    for key, var in panel_vars.items():
        panel_config[key] = var.get()
    return panel_config


def build_settings_save_payload(
    *,
    alpha_var: object,
    nav_width_var: object,
    scale_var: object,
    text_scale_var: object,
    theme_var: object,
    hud_enabled_var: object,
    hud_alpha_var: object,
    hud_scale_var: object,
    hud_smoothing_var: object,
    hud_follow_main_monitor_var: object,
    hud_color_style_var: object,
    hotkeys_enabled_var: object,
    hotkey_bindings: dict[str, str],
    panel_vars: dict[str, object],
    snap_var: object,
    snap_dist_var: object,
    sound_enabled_var: object,
    zone_sound_enabled_var: object,
    overspeed_vars: dict,
    overspeed_override_map: object,
    existing_config: dict[str, object],
    enable_ccrp: bool,
    ccrp_range_mult_var: object | None = None,
    ccrp_time_mult_var: object | None = None,
    selected_bomb_id: object | None = None,
) -> SettingsSavePayload:
    window_alpha = int(alpha_var.get())
    nav_width = float(nav_width_var.get())
    ui_scale = UIConfig.clamp_ui_scale(scale_var.get())
    text_scale = UIConfig.clamp_text_scale(text_scale_var.get())
    hud_color_style = normalized_hud_color_style(hud_color_style_var.get())
    hud_config = {
        "alpha": max(30, min(255, int(hud_alpha_var.get()))),
        "scale": max(0.5, min(2.0, float(hud_scale_var.get()))),
        "smoothing": max(0.0, min(1.0, float(hud_smoothing_var.get()))),
        "follow_main_window_monitor": bool(hud_follow_main_monitor_var.get()),
        "color_style": hud_color_style,
        "horizontal_fov_deg": float(HUDConfig.horizontal_fov_deg),
        "vertical_fov_deg": float(HUDConfig.vertical_fov_deg),
    }
    ccrp_tuning = None
    selected_bomb = None
    if enable_ccrp and ccrp_range_mult_var is not None and ccrp_time_mult_var is not None:
        ccrp_tuning = collect_ccrp_tuning(ccrp_range_mult_var, ccrp_time_mult_var)
        if selected_bomb_id:
            selected_bomb = str(selected_bomb_id)

    return SettingsSavePayload(
        window_alpha=window_alpha,
        nav_width=nav_width,
        ui_scale=ui_scale,
        text_scale=text_scale,
        theme=str(theme_var.get()),
        hud_enabled=bool(hud_enabled_var.get()),
        hud_config=hud_config,
        hotkeys_enabled=bool(hotkeys_enabled_var.get()),
        hotkey_bindings=hotkey_bindings,
        panel_config=merged_panel_config(existing_config, panel_vars),
        snap_enabled=bool(snap_var.get()),
        snap_distance=int(snap_dist_var.get()),
        sound_enabled=bool(sound_enabled_var.get()),
        zone_sound_enabled=bool(zone_sound_enabled_var.get()),
        overspeed_thresholds=collect_overspeed_thresholds(overspeed_vars),
        overspeed_overrides=normalize_overspeed_overrides(overspeed_override_map),
        ccrp_tuning=ccrp_tuning,
        selected_bomb=selected_bomb,
    )


def apply_settings_payload_to_config(
    config: dict[str, object],
    payload: SettingsSavePayload,
    *,
    sound_settings: dict[str, str],
) -> dict[str, object]:
    config["alpha"] = payload.window_alpha
    config["navigation_bar_width"] = payload.nav_width
    config["scale"] = payload.ui_scale
    config["text_scale"] = payload.text_scale
    config["theme"] = payload.theme
    config["hud_enabled"] = payload.hud_enabled
    config["hud"] = payload.hud_config
    config["panels"] = payload.panel_config
    config["global_hotkeys"] = payload.hotkeys_enabled
    config["hotkey_bindings"] = payload.hotkey_bindings
    config["snap_enabled"] = payload.snap_enabled
    config["snap_distance"] = payload.snap_distance
    config["beep_enabled"] = payload.sound_enabled
    config["zone_sound_enabled"] = payload.zone_sound_enabled
    config["sound_settings"] = sound_settings
    config["overspeed"] = {
        "global": payload.overspeed_thresholds,
        "aircraft_overrides": payload.overspeed_overrides,
    }
    if payload.ccrp_tuning is not None:
        config["ccrp_tuning"] = dict(payload.ccrp_tuning)
        if payload.selected_bomb:
            config["selected_bomb"] = payload.selected_bomb
    return config
