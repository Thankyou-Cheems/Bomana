"""Headless presentation helpers for settings dialogs."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PanelOptionSpec:
    key: str
    icon: str
    label: str
    description: str


def build_panel_option_specs(
    *,
    enable_ccrp: bool,
    enable_zones: bool,
    enable_airfields: bool,
    enable_fuel: bool,
    enable_checklist: bool,
) -> list[PanelOptionSpec]:
    panels: list[PanelOptionSpec] = []
    if enable_ccrp:
        panels.append(PanelOptionSpec("show_bombing", "bomb", "投弹预测", "显示CCRP投弹预测面板"))
    if enable_zones:
        panels.append(PanelOptionSpec("show_zones", "aim", "战区导航", "显示战区位置和距离"))
    if enable_airfields:
        panels.append(
            PanelOptionSpec("show_airfields", "aircraft", "机场导航", "显示友方/敌方机场")
        )
    if enable_fuel:
        panels.append(PanelOptionSpec("show_fuel", "fuel", "燃油管理", "显示油量和返航估算"))
    panels.append(PanelOptionSpec("show_speed", "speed", "速度监视", "显示紧凑速度条和超速提示"))
    panels.append(
        PanelOptionSpec(
            "speed_history_mode",
            "clock",
            "历史模式(独立速度界面)",
            "隐藏计时和其他扩展面板，切换为仅速度提醒的专用界面",
        )
    )
    if enable_checklist:
        panels.append(
            PanelOptionSpec("show_checklist", "checklist", "出击检查", "显示起飞前检查清单")
        )
    return panels


def format_aircraft_override_label(raw: str) -> str:
    return str(raw or "").strip().replace("_", " ") or "未知机型"


def format_overspeed_override_summary(override_map: dict[str, object]) -> str:
    count = len(override_map)
    if count <= 0:
        return "当前没有机型覆盖，所有飞机使用全局阈值。"
    names = sorted(format_aircraft_override_label(name) for name in override_map)
    preview = ", ".join(names[:4])
    if count > 4:
        preview += f" 等 {count} 个机型"
    return f"已配置 {count} 个机型覆盖：{preview}"
