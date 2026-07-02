"""Headless panel presentation models shared by Tk renderers and tests."""

from dataclasses import dataclass
from typing import Any

from bomana.config.settings import (
    BombConfig,
    FuelConfig,
)
from bomana.ui.theme import Theme


@dataclass(frozen=True, slots=True)
class IconTextModel:
    icon: str | None
    text: str
    fg: str


@dataclass(frozen=True, slots=True)
class FuelDisplayModel:
    main_text: str
    main_fg: str
    time: IconTextModel
    return_status: IconTextModel
    detail_text: str
    altitude_text: str
    return_detail_text: str


@dataclass(frozen=True, slots=True)
class BombingDisplayModel:
    bomb_label_text: str
    trajectory_text: str
    trajectory_fg: str
    flight_text: str
    flight_fg: str
    release: IconTextModel
    release_detail_text: str


@dataclass(frozen=True, slots=True)
class SpeedStripModel:
    level: str
    state_text: str
    state_fg: str
    model_text: str
    model_fg: str
    value_text: str
    value_fg: str
    fill_color: str
    fill_ratio: float


@dataclass(frozen=True, slots=True)
class SpeedHistoryHeaderModel:
    phase_text: str
    phase_fg: str
    hint_text: str


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except TypeError, ValueError:
        return default


def _format_fuel_remaining_time(minutes: float | None) -> str:
    if minutes is None:
        return ""
    if minutes > 60:
        return ">60:00"
    remaining_seconds = max(0, int(minutes * 60))
    rm, rs = divmod(remaining_seconds, 60)
    return f"{rm:02d}:{rs:02d}"


def _compute_overspeed_fill_ratio(snap: Any, ias_ratio: float) -> float:
    mach = getattr(snap, "overspeed_current_mach", None)
    limit_mach = _safe_float(getattr(snap, "overspeed_limit_mach", 0.0))
    mach_ratio = 0.0
    if mach is not None and limit_mach > 0.0:
        mach_ratio = _safe_float(mach) / limit_mach
    return max(ias_ratio, mach_ratio, 0.0)


def format_aircraft_type_label(raw: str) -> str:
    text = str(raw or "").strip().replace("_", " ")
    text = " ".join(text.split())
    if not text:
        return "机型未识别"
    if len(text) > 28:
        return text[:25] + "..."
    return text


def build_fuel_display_model(snap: Any) -> FuelDisplayModel:
    if snap.fuel_kg > 0:
        main_text = f"{int(snap.fuel_kg)}kg ({snap.fuel_percent:.0f}%)"
        if snap.fuel_percent <= FuelConfig.DANGER_PERCENT:
            main_fg = Theme.RED
        elif snap.fuel_percent <= FuelConfig.WARNING_PERCENT:
            main_fg = Theme.YELLOW
        else:
            main_fg = Theme.TEXT
    else:
        main_text = "-- kg (--%)"
        main_fg = Theme.TEXT_MUTED

    remaining_time_text = _format_fuel_remaining_time(
        getattr(snap, "fuel_remaining_time_min", None)
    )
    if remaining_time_text:
        time = IconTextModel("clock", remaining_time_text, Theme.TEXT)
    else:
        time = IconTextModel("clock", "计算中...", Theme.TEXT_MUTED)

    if snap.fuel_rate_stable and snap.fuel_rate_kg_min > 0:
        detail_text = f"油耗 {snap.fuel_rate_kg_min:.0f}kg/min"
    else:
        detail_text = "油耗 --"

    altitude_text = f"高度 {int(snap.altitude_m)}m" if snap.altitude_m > 0 else "高度 --"
    return_detail_text = "返航 --"

    if snap.return_status != "unknown" and snap.return_fuel_needed_kg > 0:
        needed_text = f"需~{int(snap.return_fuel_needed_kg)}kg"
        if snap.fuel_initial_kg > 0:
            return_percent = (snap.return_fuel_needed_kg / snap.fuel_initial_kg) * 100
            needed_text += f" ({return_percent:.0f}%)"

        if snap.return_status == "safe":
            return_status = IconTextModel("ok", "充足", Theme.GREEN)
        elif snap.return_status == "warning":
            return_status = IconTextModel("warning", "注意", Theme.YELLOW)
        else:
            return_status = IconTextModel("danger", "不足!", Theme.RED)
        return_detail_text = f"返航 {needed_text}"
    elif snap.friendly_distance_km > 0:
        return_status = IconTextModel(None, "↻ 估算中", Theme.TEXT_MUTED)
        return_detail_text = f"返航距离 {snap.friendly_distance_km:.0f}km"
    else:
        return_status = IconTextModel(None, "无机场", Theme.TEXT_MUTED)
        return_detail_text = "返航无机场数据"

    return FuelDisplayModel(
        main_text=main_text,
        main_fg=main_fg,
        time=time,
        return_status=return_status,
        detail_text=detail_text,
        altitude_text=altitude_text,
        return_detail_text=return_detail_text,
    )


def _format_release_distance(dist_m: float) -> str:
    if dist_m > 1000:
        return f"{dist_m / 1000:.2f}km"
    if dist_m > 100:
        return f"{int(dist_m)}m"
    return f"{dist_m:.0f}m"


def build_bombing_display_model(snap: Any) -> BombingDisplayModel:
    bomb_label_text = f"炸弹: {BombConfig.format_bomb_name(snap.bomb_name)} (点击更换)"
    bomb_data = BombConfig.get_bomb_data(snap.bomb_name) or {}
    prediction_kind = str(bomb_data.get("prediction_kind", "freefall") or "freefall")

    if snap.bombing_valid:
        bomb_range_km = snap.bomb_range_m / 1000.0
        trajectory_label = "高阻" if prediction_kind == "high_drag" else "弹道"
        trajectory_text = f"{trajectory_label}: {bomb_range_km:.2f}km"
        trajectory_fg = Theme.TEXT_DIM
        flight_label = "直落" if prediction_kind == "high_drag" else "飞行"
        flight_text = f"{flight_label}: {snap.bomb_flight_time:.1f}s"
        flight_fg = Theme.TEXT_DIM

        status = snap.release_status
        dist_str = _format_release_distance(snap.release_distance_m)
        if status == "ready":
            release = IconTextModel("bomb", "投弹", Theme.GREEN)
            release_detail_text = f"时间 {snap.time_to_release:.2f}s，距离 {dist_str}"
        elif status == "approaching":
            release = IconTextModel("clock", "接近", Theme.YELLOW)
            release_detail_text = f"时间 {snap.time_to_release:.1f}s，距离 {dist_str}"
        elif status == "passed":
            release = IconTextModel("danger", "已飞过", Theme.RED)
            release_detail_text = f"偏离 {dist_str}"
        elif status == "too_far":
            release = IconTextModel("aim", "过远", Theme.TEXT_DIM)
            release_detail_text = f"距离 {dist_str}，预计 {snap.time_to_release:.0f}s"
        else:
            release = IconTextModel("clock", "计算中", Theme.TEXT_MUTED)
            release_detail_text = "等待稳定数据"
    else:
        unavailable_reason = str(getattr(snap, "bombing_unavailable_reason", "") or "").strip()
        if unavailable_reason == "guided_glide":
            trajectory_text = "弹道: 不适用"
            trajectory_fg = Theme.TEXT_MUTED
            flight_text = "飞行: 制导/滑翔"
            flight_fg = Theme.TEXT_MUTED
            release = IconTextModel("aim", "未辅助", Theme.YELLOW)
            release_detail_text = "使用武器自身引导，不显示释放点"
        elif unavailable_reason == "release_mach_limit":
            trajectory_text = "弹道: 超限"
            trajectory_fg = Theme.TEXT_MUTED
            flight_text = "飞行: 不计算"
            flight_fg = Theme.TEXT_MUTED
            mach = getattr(snap, "overspeed_current_mach", None)
            mach_text = f"M{float(mach):.2f}" if mach is not None else "M≥1.00"
            release = IconTextModel("danger", "不可投", Theme.RED)
            release_detail_text = f"{mach_text} 超过投放限制，减速后再投"
        else:
            trajectory_text = "弹道: -- km"
            trajectory_fg = Theme.TEXT_MUTED
            flight_text = "飞行: -- s"
            flight_fg = Theme.TEXT_MUTED
            if snap.on_ground:
                release = IconTextModel("aircraft", "请起飞", Theme.TEXT_MUTED)
                release_detail_text = "起飞后开始计算"
            elif snap.altitude_m <= 50:
                release = IconTextModel("climb", "请爬升", Theme.TEXT_MUTED)
                release_detail_text = "高度超过 50m 后开始计算"
            elif not snap.has_target:
                release = IconTextModel("aim", "无目标战区", Theme.TEXT_MUTED)
                release_detail_text = "选择或接近目标战区"
            else:
                release = IconTextModel(None, "↻ 请对准目标", Theme.TEXT_MUTED)
                release_detail_text = "进入释放航线后显示距离和时间"

    return BombingDisplayModel(
        bomb_label_text=bomb_label_text,
        trajectory_text=trajectory_text,
        trajectory_fg=trajectory_fg,
        flight_text=flight_text,
        flight_fg=flight_fg,
        release=release,
        release_detail_text=release_detail_text,
    )


def build_speed_strip_model(snap: Any) -> SpeedStripModel:
    speed_level = str(getattr(snap, "overspeed_level", "unknown") or "unknown")
    speed_ratio = _safe_float(getattr(snap, "overspeed_ratio", 0.0))
    current_ias = _safe_float(getattr(snap, "overspeed_current_ias_kmh", 0.0))
    current_mach = getattr(snap, "overspeed_current_mach", None)
    limit_ias = _safe_float(getattr(snap, "overspeed_limit_kmh", 0.0))
    limit_mach = _safe_float(getattr(snap, "overspeed_limit_mach", 0.0))
    matched = bool(getattr(snap, "overspeed_match", False))
    reason = str(getattr(snap, "overspeed_reason", "") or "")
    aircraft_type_name = format_aircraft_type_label(
        str(getattr(snap, "aircraft_type_name", "") or "")
    )
    display_ratio = _compute_overspeed_fill_ratio(snap, speed_ratio)

    if speed_level == "critical":
        state_text = "超速危险"
        state_fg = Theme.RED
        fill_color = Theme.RED
    elif speed_level == "warning":
        state_text = "接近极限"
        state_fg = Theme.YELLOW
        fill_color = Theme.YELLOW
    elif speed_level == "caution":
        state_text = "高速预警"
        state_fg = Theme.ORANGE
        fill_color = Theme.ORANGE
    elif reason == "limit_missing":
        state_text = "阈值缺失"
        state_fg = Theme.TEXT_MUTED
        fill_color = Theme.TEXT_MUTED
    elif matched:
        state_text = "速度安全"
        state_fg = Theme.GREEN
        fill_color = Theme.GREEN
    else:
        state_text = "速度监视"
        state_fg = Theme.TEXT_MUTED
        fill_color = Theme.TEXT_MUTED

    if matched:
        if limit_ias > 0.0:
            value_text = f"IAS {current_ias:.0f}/{limit_ias:.0f}"
        elif current_ias > 0.0:
            value_text = f"IAS {current_ias:.0f}"
        else:
            value_text = "IAS --"
    else:
        value_text = f"IAS {current_ias:.0f}" if current_ias > 0.0 else "IAS --"

    model_parts = [aircraft_type_name]
    if current_mach is not None and limit_mach > 0.0:
        model_parts.append(f"M{float(current_mach):.2f}/{limit_mach:.2f}")
    elif reason == "limit_missing":
        model_parts.append("阈值缺失")
    elif not matched:
        model_parts.append("阈值未匹配")
    model_text = "  |  ".join(part for part in model_parts if part)

    model_fg = Theme.TEXT if speed_level in ("warning", "critical") else Theme.TEXT_DIM
    value_fg = state_fg if speed_level in ("caution", "warning", "critical") else Theme.TEXT_DIM
    return SpeedStripModel(
        level=speed_level,
        state_text=state_text,
        state_fg=state_fg,
        model_text=model_text,
        model_fg=model_fg,
        value_text=value_text,
        value_fg=value_fg,
        fill_color=fill_color if matched else Theme.TEXT_MUTED,
        fill_ratio=max(0.0, min(1.0, display_ratio if matched else 0.0)),
    )


def build_speed_history_header_model(snap: Any, speed_level: str) -> SpeedHistoryHeaderModel:
    phase_name = str(getattr(getattr(snap, "phase", None), "name", "") or "")
    if snap.api_down:
        phase_text = "8111 离线"
        phase_fg = Theme.YELLOW
    elif phase_name == "ALIVE" and not snap.on_ground:
        phase_text = "飞行中"
        phase_fg = Theme.GREEN if speed_level not in ("warning", "critical") else Theme.YELLOW
    elif phase_name == "ALIVE":
        phase_text = "地面待命"
        phase_fg = Theme.TEXT_DIM
    elif phase_name == "LOSS_PENDING":
        phase_text = "状态切换中"
        phase_fg = Theme.YELLOW
    else:
        phase_text = "等待进入战局"
        phase_fg = Theme.TEXT_MUTED

    aircraft_text = format_aircraft_type_label(str(getattr(snap, "aircraft_type_name", "") or ""))
    return SpeedHistoryHeaderModel(
        phase_text=phase_text,
        phase_fg=phase_fg,
        hint_text=f"计时和导航已隐藏，当前机型：{aircraft_text}",
    )
