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


def overspeed_focus_ratio(value: float) -> float:
    """Map the useful 65%-105% near-limit band across the visible strip."""

    return max(0.0, min(1.0, (_safe_float(value) - 0.65) / 0.40))


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
        main_text = f"油量 {int(snap.fuel_kg)}kg / {snap.fuel_percent:.0f}%"
        if snap.fuel_percent <= FuelConfig.DANGER_PERCENT:
            main_fg = Theme.RED
        elif snap.fuel_percent <= FuelConfig.WARNING_PERCENT:
            main_fg = Theme.YELLOW
        else:
            main_fg = Theme.TEXT
    else:
        main_text = "油量 -- kg / --%"
        main_fg = Theme.TEXT_MUTED

    remaining_time_text = _format_fuel_remaining_time(
        getattr(snap, "fuel_remaining_time_min", None)
    )
    if remaining_time_text:
        time = IconTextModel("clock", f"余 {remaining_time_text}", Theme.TEXT)
    else:
        time = IconTextModel("clock", "余 --", Theme.TEXT_MUTED)

    if snap.fuel_rate_stable and snap.fuel_rate_kg_min > 0:
        fuel_rate_text = f"油耗 {snap.fuel_rate_kg_min:.0f}kg/min"
    else:
        fuel_rate_text = "油耗 --"

    altitude_value_text = f"高度 {int(snap.altitude_m)}m" if snap.altitude_m > 0 else "高度 --"
    altitude_text = ""
    return_detail_text = "返航 --"
    friendly_distance_text = (
        f" · {snap.friendly_distance_km:.0f}km" if snap.friendly_distance_km > 0 else ""
    )

    if snap.return_status != "unknown" and snap.return_fuel_needed_kg > 0:
        needed_text = f"需 {int(snap.return_fuel_needed_kg)}kg"
        if snap.fuel_initial_kg > 0:
            return_percent = (snap.return_fuel_needed_kg / snap.fuel_initial_kg) * 100
            needed_text += f" ({return_percent:.0f}%)"

        if snap.return_status == "safe":
            return_status = IconTextModel("ok", "返航足", Theme.GREEN)
        elif snap.return_status == "warning":
            return_status = IconTextModel("warning", "返航紧", Theme.YELLOW)
        else:
            return_status = IconTextModel("danger", "返航不足", Theme.RED)
        return_detail_text = f"返航 {needed_text}{friendly_distance_text}"
    elif snap.friendly_distance_km > 0:
        return_status = IconTextModel(None, "返航估算", Theme.TEXT_MUTED)
        return_detail_text = f"返航估算中 · {snap.friendly_distance_km:.0f}km"
    else:
        return_status = IconTextModel(None, "无机场", Theme.TEXT_MUTED)
        return_detail_text = "返航无机场数据"

    return_summary = return_detail_text.replace("返航 ", "返航", 1)
    main_text = f"{main_text} · {fuel_rate_text} · {altitude_value_text} · {return_summary}"

    return FuelDisplayModel(
        main_text=main_text,
        main_fg=main_fg,
        time=time,
        return_status=return_status,
        detail_text="",
        altitude_text=altitude_text,
        return_detail_text="",
    )


def _format_release_distance(dist_m: float) -> str:
    if dist_m > 1000:
        return f"{dist_m / 1000:.2f}km"
    if dist_m > 100:
        return f"{int(dist_m)}m"
    return f"{dist_m:.0f}m"


def _short_label(text: str, *, fallback: str, limit: int = 14) -> str:
    cleaned = " ".join(str(text or "").strip().split())
    if not cleaned:
        cleaned = fallback
    if len(cleaned) > limit:
        return cleaned[: limit - 3] + "..."
    return cleaned


_WEAPON_ROLE_LABELS = {
    "aam": "AAM",
    "agm": "AGM",
    "bomb": "炸弹",
}

_WEAPON_SOURCE_LABELS = {
    "manual": "手选",
    "8111": "8111",
    "unknown": "来源未知",
}


def format_weapon_selection_label(
    display_name: str,
    role: str,
    selection_source: str,
) -> str:
    """Format the clickable first row shared by CCRP and envelope estimates."""
    name = _short_label(display_name, fallback="未选择武器", limit=28)
    role_label = _WEAPON_ROLE_LABELS.get(str(role or "").strip().lower(), "武器")
    source_label = _WEAPON_SOURCE_LABELS.get(
        str(selection_source or "").strip().lower(),
        "来源未知",
    )
    return f"{name} · {role_label} · {source_label}"


def _weapon_selection_label_from_snapshot(snap: Any) -> str:
    reason = str(getattr(snap, "weapon_reason", "") or "").strip().lower()
    if reason == "catalog_unavailable":
        return format_weapon_selection_label("武器目录不可用", "", "unknown")
    display_name = str(getattr(snap, "weapon_display_name", "") or "").strip()
    if not display_name:
        bomb_name = str(getattr(snap, "bomb_name", "") or "")
        display_name = BombConfig.format_bomb_name(bomb_name) if bomb_name else ""
    role = str(getattr(snap, "weapon_role", "") or "").strip().lower()
    if not role:
        weapon_status = str(getattr(snap, "weapon_status", "") or "").strip().lower()
        if not weapon_status or weapon_status == "ccrp":
            role = "bomb"
    selection_source = (
        str(getattr(snap, "weapon_selection_source", "") or "").strip().lower() or "manual"
    )
    return format_weapon_selection_label(display_name, role, selection_source)


def _is_ccrp_weapon_snapshot(snap: Any) -> bool:
    status = str(getattr(snap, "weapon_status", "") or "").strip().lower()
    role = str(getattr(snap, "weapon_role", "") or "").strip().lower()
    control = str(getattr(snap, "weapon_control", "") or "").strip().lower()
    if status:
        return status == "ccrp"
    if role == "bomb" and control == "unguided":
        return True

    # Older/debug snapshots do not carry weapon fields. Keep their established
    # CCRP rendering instead of turning a compatible fixture into an unknown weapon.
    has_weapon_identity = bool(
        status
        or role
        or control
        or str(getattr(snap, "weapon_id", "") or "").strip()
        or str(getattr(snap, "weapon_display_name", "") or "").strip()
    )
    return not has_weapon_identity


def _format_weapon_distance(distance_m: float) -> str:
    distance_m = max(0.0, distance_m)
    if distance_m >= 1000.0:
        return f"{distance_m / 1000.0:.1f}km"
    return f"{distance_m:.0f}m"


def _format_weapon_range(min_range_m: float, max_range_m: float) -> str:
    min_range_m = max(0.0, min_range_m)
    max_range_m = max(0.0, max_range_m)
    if max_range_m <= 0.0:
        return "估算窗 --"
    if max_range_m >= 1000.0:
        return f"估算窗 {min_range_m / 1000.0:.1f}–{max_range_m / 1000.0:.1f}km"
    return f"估算窗 {min_range_m:.0f}–{max_range_m:.0f}m"


def _format_aam_aspect_range(rear_range_m: float, head_range_m: float) -> str:
    rear_range_m = max(0.0, rear_range_m)
    head_range_m = max(0.0, head_range_m)
    if rear_range_m >= 1000.0 and head_range_m >= 1000.0:
        return f"尾/迎 {rear_range_m / 1000.0:.1f}/{head_range_m / 1000.0:.1f}km"
    return (
        f"尾 {_format_weapon_distance(rear_range_m)} / 迎 {_format_weapon_distance(head_range_m)}"
    )


def _format_weapon_target(snap: Any) -> str:
    kind = str(getattr(snap, "weapon_target_kind", "") or "").strip().lower()
    name = str(getattr(snap, "weapon_target_name", "") or "").strip()
    kind_label = {
        "poi": "POI",
        "zone": "战区",
        "aircraft": "空中目标",
        "enemy_aircraft": "空中目标",
        "air": "空中目标",
        "ground": "地面目标",
    }.get(kind, "目标")

    if name:
        short_name = _short_label(name, fallback=kind_label, limit=12)
        if short_name.casefold() != kind_label.casefold():
            kind_label = f"{kind_label} {short_name}"

    target_distance_m = _safe_float(getattr(snap, "weapon_target_distance_m", 0.0))
    if target_distance_m > 0.0:
        return f"{kind_label} {_format_weapon_distance(target_distance_m)}"
    return f"{kind_label} --"


def _format_weapon_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 10.0:
        return f"{seconds:.1f}s"
    return f"{seconds:.0f}s"


def _weapon_quality_text(quality: str) -> str:
    quality = str(quality or "").strip().lower()
    if quality in {"two_dimensional", "two-dimensional", "2d"}:
        return "二维参考"
    if quality == "conservative":
        return "保守参考"
    if quality == "experimental":
        return "推测参考"
    if quality in {"degraded", "coarse"}:
        return "粗略参考"
    return ""


def _weapon_model_text(model: str, reason: str) -> str:
    model = str(model or "").strip().lower()
    reason = str(reason or "").strip().lower()
    if reason == "datamine_guidance_envelope":
        return "官方包线"
    if reason in {"foxthree_compatible_glide", "foxthree_compatible_glide_unavailable"}:
        return "推测替代"
    if reason == "glide_envelope_unavailable" and model == "strict_official":
        return "无替代模型"
    if reason in {"powered_point_mass_2d", "aam_2d_max_only"}:
        return "二维回退"
    if reason == "guided_ballistic_conservative":
        return "保守估算"
    return ""


def _weapon_status_presentation(status: str) -> IconTextModel:
    presentations = {
        "unknown_weapon": IconTextModel("warning", "武器未知", Theme.YELLOW),
        "catalog_unavailable": IconTextModel("danger", "目录不可用", Theme.RED),
        "incompatible": IconTextModel("danger", "不兼容", Theme.RED),
        "no_target": IconTextModel("aim", "无目标", Theme.TEXT_MUTED),
        "insufficient_data": IconTextModel("clock", "数据不足", Theme.TEXT_MUTED),
        "too_close": IconTextModel("warning", "过近", Theme.YELLOW),
        "out_of_range": IconTextModel("aim", "过远", Theme.YELLOW),
        "align": IconTextModel("aim", "请对准", Theme.YELLOW),
        "in_envelope": IconTextModel("ok", "估算窗内", Theme.GREEN),
        "within_ballistic_reference": IconTextModel("aim", "弹道参考内", Theme.YELLOW),
        "beyond_ballistic_reference": IconTextModel("aim", "弹道参考外", Theme.YELLOW),
        "within_2d_max_only": IconTextModel("aim", "二维上限内", Theme.YELLOW),
        "within_all_aspect_reference": IconTextModel("aim", "全向参考内", Theme.YELLOW),
        "within_aspect_reference": IconTextModel("aim", "当前航向内", Theme.YELLOW),
        "head_on_only_reference": IconTextModel("aim", "仅迎头可达", Theme.YELLOW),
        "beyond_envelope_reference": IconTextModel("aim", "超出表参考", Theme.YELLOW),
        "within_experimental_reference": IconTextModel("aim", "实验参考内", Theme.YELLOW),
        "beyond_experimental_reference": IconTextModel("aim", "实验参考外", Theme.YELLOW),
        "solver_error": IconTextModel("danger", "解算失败", Theme.RED),
    }
    return presentations.get(status, IconTextModel("clock", "等待估算", Theme.TEXT_MUTED))


def _weapon_fallback_detail(status: str, role: str, reason: str = "") -> str:
    if status == "catalog_unavailable":
        return "武器目录不可用"
    if status == "unknown_weapon":
        return "请选择武器"
    if status == "incompatible":
        return "请更换兼容武器"
    if status == "no_target":
        if role == "aam":
            return "未发现可用空中目标"
        return "请选择 POI 或战区"
    if status == "insufficient_data":
        if reason == "glide_envelope_unavailable":
            return "无官方包线，未应用替代模型"
        if reason == "foxthree_compatible_glide_unavailable":
            return "替代模型缺少必要参数"
        if reason == "conditional_propulsion_unsupported":
            return "条件推进数据不足"
        return "等待高度与速度"
    if status == "too_close":
        return "目标过近"
    if status == "out_of_range":
        return "目标超出估算窗"
    if status == "align":
        return "对准目标后更新"
    if status == "within_ballistic_reference":
        return "仅重力/阻力弹道参考，未计滑翔增程"
    if status == "beyond_ballistic_reference":
        return "超出弹道参考，不代表超出滑翔能力"
    if status in {"within_experimental_reference", "beyond_experimental_reference"}:
        return "推测替代，仅供参考"
    if status == "within_2d_max_only":
        return "二维最大射程参考"
    if status in {
        "within_all_aspect_reference",
        "within_aspect_reference",
        "head_on_only_reference",
        "beyond_envelope_reference",
    }:
        return "官方条件包线参考"
    if status == "solver_error":
        return "暂时无法生成武器估算"
    return ""


def _build_weapon_solution_display_model(snap: Any) -> BombingDisplayModel:
    status = str(getattr(snap, "weapon_status", "") or "").strip().lower()
    reason = str(getattr(snap, "weapon_reason", "") or "").strip().lower()
    if reason == "catalog_unavailable":
        status = "catalog_unavailable"
    role = str(getattr(snap, "weapon_role", "") or "").strip().lower()
    compatible = bool(getattr(snap, "weapon_selection_compatible", True))
    solution_valid = bool(getattr(snap, "weapon_solution_valid", False))
    usable_statuses = {
        "in_envelope",
        "within_ballistic_reference",
        "beyond_ballistic_reference",
        "within_2d_max_only",
        "within_all_aspect_reference",
        "within_aspect_reference",
        "head_on_only_reference",
        "beyond_envelope_reference",
        "within_experimental_reference",
        "beyond_experimental_reference",
    }
    if status in usable_statuses and not compatible:
        status = "incompatible"
    elif status in usable_statuses and not solution_valid:
        status = "insufficient_data"

    release = _weapon_status_presentation(status)
    min_range_m = _safe_float(getattr(snap, "weapon_min_range_m", 0.0))
    max_range_m = _safe_float(getattr(snap, "weapon_max_range_m", 0.0))
    rear_range_m = _safe_float(getattr(snap, "weapon_rear_range_m", 0.0))
    head_range_m = _safe_float(getattr(snap, "weapon_head_range_m", 0.0))
    if status in {"within_ballistic_reference", "beyond_ballistic_reference"}:
        range_text = (
            f"弹道参考约 {_format_weapon_distance(max_range_m)}"
            if max_range_m > 0.0
            else "弹道参考 --"
        )
    elif status in {"within_experimental_reference", "beyond_experimental_reference"}:
        range_text = (
            f"滑翔参考约 {_format_weapon_distance(max_range_m)}"
            if max_range_m > 0.0
            else "滑翔参考 --"
        )
    elif role == "aam" and rear_range_m > 0.0 and head_range_m > 0.0:
        range_text = _format_aam_aspect_range(rear_range_m, head_range_m)
    elif role == "aam" and max_range_m > 0.0:
        range_text = f"二维最大约 {_format_weapon_distance(max_range_m)}"
    else:
        range_text = _format_weapon_range(min_range_m, max_range_m)
    trajectory_text = f"{_format_weapon_target(snap)} · {range_text}"

    detail_parts: list[str] = []
    time_to_target_s = _safe_float(getattr(snap, "weapon_time_to_target_s", 0.0))
    time_to_window_s = _safe_float(getattr(snap, "weapon_time_to_window_s", 0.0))
    if status == "out_of_range" and time_to_window_s > 0.0:
        detail_parts.append(f"距估算窗约 {_format_weapon_time(time_to_window_s)}")
    elif status == "beyond_ballistic_reference" and time_to_window_s > 0.0:
        detail_parts.append(f"距弹道参考约 {_format_weapon_time(time_to_window_s)}")
    elif status == "beyond_experimental_reference" and time_to_window_s > 0.0:
        detail_parts.append(f"距滑翔参考约 {_format_weapon_time(time_to_window_s)}")
    elif status != "align" and time_to_target_s > 0.0:
        detail_parts.append(f"飞行约 {_format_weapon_time(time_to_target_s)}")

    if role == "aam" and reason == "datamine_guidance_envelope":
        aspect = getattr(snap, "weapon_target_aspect_cosine", None)
        if aspect is not None and max_range_m > 0.0:
            detail_parts.append(f"当前航向约 {_format_weapon_distance(max_range_m)}")
        detail_parts.append("条件表参考 · 目标速率/高差未知")
    elif role == "aam" and max_range_m > 0.0:
        detail_parts.append("仅二维最大射程，未计目标速度、高差与迎尾角")
    elif status == "within_ballistic_reference":
        detail_parts.append("仅重力/阻力弹道参考，未计滑翔增程")
    elif status == "beyond_ballistic_reference":
        detail_parts.append("仅超出弹道参考，不代表超出滑翔能力")
    elif reason == "foxthree_compatible_glide":
        detail_parts.append("等效升阻比/能量高度参考，未模拟舵面与自动驾驶")

    quality_text = ""
    if status in {
        "too_close",
        "out_of_range",
        "align",
        "in_envelope",
        "within_ballistic_reference",
        "beyond_ballistic_reference",
        "within_2d_max_only",
        "within_all_aspect_reference",
        "within_aspect_reference",
        "head_on_only_reference",
        "beyond_envelope_reference",
        "within_experimental_reference",
        "beyond_experimental_reference",
    }:
        quality_text = _weapon_quality_text(str(getattr(snap, "weapon_quality", "") or ""))
    model_text = _weapon_model_text(
        str(getattr(snap, "weapon_model", "") or ""),
        reason,
    )
    timing_text = next((part for part in detail_parts if "s" in part), "")
    compact_details = [part for part in (timing_text, model_text, quality_text) if part]
    flight_text = " · ".join(compact_details) or _weapon_fallback_detail(status, role, reason)

    highlighted_statuses = usable_statuses | {"align"}

    return BombingDisplayModel(
        bomb_label_text=_weapon_selection_label_from_snapshot(snap),
        trajectory_text=trajectory_text,
        trajectory_fg=release.fg if status in highlighted_statuses else Theme.TEXT_DIM,
        flight_text=flight_text,
        flight_fg=release.fg if status in highlighted_statuses else Theme.TEXT_MUTED,
        release=release,
        release_detail_text="",
    )


def _format_bombing_target(snap: Any) -> tuple[str, str, str, bool]:
    has_target = bool(
        getattr(snap, "has_bombing_target", False) or getattr(snap, "has_target", False)
    )
    kind = str(getattr(snap, "bombing_target_kind", "") or "").strip().lower()
    if not kind and getattr(snap, "has_target", False):
        kind = "zone"

    distance_m = _safe_float(getattr(snap, "target_zone_distance_m", 0.0))
    distance_text = f" {_format_release_distance(distance_m)}" if distance_m > 0 else ""

    if not has_target:
        return "--", Theme.TEXT_MUTED, "目标", False

    if kind == "poi":
        name = _short_label(
            str(getattr(snap, "bombing_target_name", "") or ""),
            fallback="兴趣点",
        )
        return f"POI {name}{distance_text}", Theme.YELLOW, "POI", True

    name = _short_label(
        str(getattr(snap, "bombing_target_name", "") or ""),
        fallback="战区",
    )
    return f"{name}{distance_text}", Theme.TEXT_DIM, "战区", True


def build_bombing_display_model(snap: Any) -> BombingDisplayModel:
    if not _is_ccrp_weapon_snapshot(snap):
        return _build_weapon_solution_display_model(snap)

    bomb_label_text = _weapon_selection_label_from_snapshot(snap)
    bomb_data = BombConfig.get_bomb_data(snap.bomb_name) or {}
    prediction_kind = str(bomb_data.get("prediction_kind", "freefall") or "freefall")
    target_text, target_fg, target_short, has_bombing_target = _format_bombing_target(snap)

    if snap.bombing_valid:
        bomb_range_km = snap.bomb_range_m / 1000.0
        trajectory_label = "高阻" if prediction_kind == "high_drag" else "弹道"
        flight_label = "直落" if prediction_kind == "high_drag" else "飞行"
        trajectory_text = (
            f"目标 {target_text} · {trajectory_label} {bomb_range_km:.2f}km"
            f" · {flight_label} {snap.bomb_flight_time:.1f}s"
        )
        trajectory_fg = target_fg
        flight_text = ""
        flight_fg = Theme.TEXT_DIM

        status = snap.release_status
        dist_str = _format_release_distance(snap.release_distance_m)
        if status == "ready":
            release = IconTextModel("bomb", "投弹", Theme.GREEN)
            release_detail_text = f"{target_short}窗口 {snap.time_to_release:.2f}s / {dist_str}"
        elif status == "approaching":
            release = IconTextModel("clock", "接近", Theme.YELLOW)
            release_detail_text = f"{target_short}窗口 {snap.time_to_release:.1f}s / {dist_str}"
        elif status == "passed":
            release = IconTextModel("danger", "已飞过", Theme.RED)
            release_detail_text = f"已过{target_short}释放点 {dist_str}"
        elif status == "too_far":
            release = IconTextModel("aim", "过远", Theme.TEXT_DIM)
            release_detail_text = f"{target_short}释放点 {dist_str} / {snap.time_to_release:.0f}s"
        else:
            release = IconTextModel("clock", "计算中", Theme.TEXT_MUTED)
            release_detail_text = "等待稳定数据"
    else:
        unavailable_reason = str(getattr(snap, "bombing_unavailable_reason", "") or "").strip()
        if unavailable_reason == "guided_glide":
            trajectory_text = f"目标 {target_text} · 武器自导/滑翔"
            trajectory_fg = Theme.TEXT_MUTED
            flight_text = ""
            flight_fg = Theme.TEXT_MUTED
            release = IconTextModel("aim", "未辅助", Theme.YELLOW)
            release_detail_text = "不显示CCRP释放点"
        elif unavailable_reason == "release_mach_limit":
            trajectory_text = f"目标 {target_text} · 超马赫限制"
            trajectory_fg = Theme.TEXT_MUTED
            flight_text = ""
            flight_fg = Theme.TEXT_MUTED
            mach = getattr(snap, "overspeed_current_mach", None)
            mach_text = f"M{float(mach):.2f}" if mach is not None else "M≥1.00"
            release = IconTextModel("danger", "不可投", Theme.RED)
            release_detail_text = f"{mach_text} 超过投放限制，减速后再投"
        else:
            trajectory_text = f"目标 {target_text} · 弹道 --"
            trajectory_fg = Theme.TEXT_MUTED
            flight_text = ""
            flight_fg = Theme.TEXT_MUTED
            if snap.on_ground:
                release = IconTextModel("aircraft", "请起飞", Theme.TEXT_MUTED)
                release_detail_text = "起飞后开始计算"
            elif snap.altitude_m <= 50:
                release = IconTextModel("climb", "请爬升", Theme.TEXT_MUTED)
                release_detail_text = "高度 >50m 后计算"
            elif not has_bombing_target:
                release = IconTextModel("aim", "无投弹目标", Theme.TEXT_MUTED)
                release_detail_text = "朝向POI或战区后计算"
            else:
                release = IconTextModel(None, "对准目标", Theme.TEXT_MUTED)
                release_detail_text = "进入释放航线后显示窗口"

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
        fill_ratio=overspeed_focus_ratio(display_ratio) if matched else 0.0,
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
