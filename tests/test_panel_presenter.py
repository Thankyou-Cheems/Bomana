from pathlib import Path
from types import SimpleNamespace

import pytest

from bomana.ui import panel_presenter
from bomana.ui.panel_presenter import (
    build_bombing_display_model,
    build_fuel_display_model,
    build_speed_history_header_model,
    build_speed_strip_model,
    format_aircraft_type_label,
)
from bomana.ui.theme import Theme


def test_fuel_display_model_formats_return_warning() -> None:
    snap = SimpleNamespace(
        fuel_kg=420.0,
        fuel_percent=18.0,
        fuel_remaining_time_min=12 + (34 / 60),
        fuel_rate_stable=True,
        fuel_rate_kg_min=38.4,
        altitude_m=1234.0,
        return_status="warning",
        return_fuel_needed_kg=250.0,
        fuel_initial_kg=500.0,
        friendly_distance_km=35.0,
    )

    model = build_fuel_display_model(snap)

    assert model.main_text == (
        "油量 420kg / 18% · 油耗 38kg/min · 高度 1234m · 返航需 250kg (50%) · 35km"
    )
    assert model.main_fg == Theme.YELLOW
    assert model.time.text == "余 12:34"
    assert model.return_status.icon == "warning"
    assert model.return_status.text == "返航油量临界"
    assert model.detail_text == ""
    assert model.altitude_text == ""
    assert model.return_detail_text == ""


def test_bombing_display_model_ready_state(monkeypatch) -> None:
    monkeypatch.setattr(panel_presenter.BombConfig, "format_bomb_name", lambda _name: "FAB-100")
    monkeypatch.setattr(panel_presenter.BombConfig, "get_bomb_data", lambda _name: {})
    snap = SimpleNamespace(
        bomb_name="su_fab100",
        bombing_valid=True,
        bomb_range_m=1420.0,
        bomb_flight_time=3.6,
        release_status="ready",
        release_distance_m=95.0,
        time_to_release=0.42,
        target_zone_distance_m=1420.0,
        has_bombing_target=True,
        bombing_target_kind="zone",
        bombing_target_name="战区 #1",
    )

    model = build_bombing_display_model(snap)

    assert model.bomb_label_text == "FAB-100 · 炸弹 · 点击切换"
    assert model.trajectory_text == "目标 战区 #1 1.42km · 弹道 1.42km · 飞行 3.6s"
    assert model.flight_text == ""
    assert model.release.icon == "bomb"
    assert model.release.text == "投弹"
    assert model.release.fg == Theme.GREEN
    assert model.release_detail_text == "战区窗口 0.42s / 95m"


def test_bombing_display_model_marks_poi_target(monkeypatch) -> None:
    monkeypatch.setattr(panel_presenter.BombConfig, "format_bomb_name", lambda _name: "FAB-100")
    monkeypatch.setattr(panel_presenter.BombConfig, "get_bomb_data", lambda _name: {})
    snap = SimpleNamespace(
        bomb_name="su_fab100",
        bombing_valid=True,
        bomb_range_m=1420.0,
        bomb_flight_time=3.6,
        release_status="approaching",
        release_distance_m=950.0,
        time_to_release=4.2,
        target_zone_distance_m=2375.0,
        has_bombing_target=True,
        bombing_target_kind="poi",
        bombing_target_name="Convoy marker",
    )

    model = build_bombing_display_model(snap)

    assert model.trajectory_text == "目标 POI Convoy marker 2.38km · 弹道 1.42km · 飞行 3.6s"
    assert model.trajectory_fg == Theme.YELLOW
    assert model.release.text == "接近"
    assert model.release_detail_text == "POI窗口 4.2s / 950m"


def test_bombing_display_model_explains_mach_limit(monkeypatch) -> None:
    monkeypatch.setattr(panel_presenter.BombConfig, "format_bomb_name", lambda _name: "FAB-100")
    monkeypatch.setattr(panel_presenter.BombConfig, "get_bomb_data", lambda _name: {})
    snap = SimpleNamespace(
        bomb_name="su_fab100",
        bombing_valid=False,
        bombing_unavailable_reason="release_mach_limit",
        overspeed_current_mach=1.08,
        on_ground=False,
        altitude_m=500.0,
        has_target=True,
    )

    model = build_bombing_display_model(snap)

    assert model.trajectory_text == "目标 战区 · 超马赫限制"
    assert model.flight_text == ""
    assert model.release.icon == "danger"
    assert model.release.text == "不可投"
    assert model.release.fg == Theme.RED
    assert model.release_detail_text == "M1.08 超过投放限制，减速后再投"


def _weapon_snapshot(**overrides):
    values = {
        "weapon_id": "agm_65d",
        "weapon_display_name": "AGM-65D",
        "weapon_role": "agm",
        "weapon_control": "guided",
        "weapon_planform": "normal",
        "weapon_selection_source": "manual",
        "weapon_selection_compatible": True,
        "weapon_solution_valid": True,
        "weapon_status": "in_envelope",
        "weapon_quality": "two_dimensional",
        "weapon_reason": "",
        "weapon_target_kind": "poi",
        "weapon_target_name": "",
        "weapon_target_distance_m": 12_400.0,
        "weapon_min_range_m": 600.0,
        "weapon_max_range_m": 18_600.0,
        "weapon_rear_range_m": 0.0,
        "weapon_head_range_m": 0.0,
        "weapon_target_aspect_cosine": None,
        "weapon_time_to_target_s": 28.0,
        "weapon_time_to_window_s": 0.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_weapon_solution_model_uses_compact_estimate_wording() -> None:
    model = build_bombing_display_model(_weapon_snapshot())

    assert model.bomb_label_text == "AGM-65D · AGM · 点击切换"
    assert model.trajectory_text == "POI 12.4km · 估算窗 0.6–18.6km"
    assert model.flight_text == "飞行约 28s"
    assert model.release.icon == "ok"
    assert model.release.text == "进入发射包线"
    assert model.release.fg == Theme.GREEN
    assert model.release_detail_text == ""


def test_powered_fallback_does_not_claim_the_foxthree_glide_model() -> None:
    model = build_bombing_display_model(
        _weapon_snapshot(
            weapon_model="foxthree_compatible",
            weapon_reason="powered_point_mass_2d",
        )
    )

    assert model.flight_text == "飞行约 28s"
    assert "FoxThree" not in model.flight_text


def test_weapon_solution_model_never_shows_countdown_while_aligning() -> None:
    model = build_bombing_display_model(
        _weapon_snapshot(
            weapon_status="align",
            weapon_solution_valid=False,
            weapon_time_to_window_s=6.4,
        )
    )

    assert model.release.text == "调整航向"
    assert model.flight_text == "调整航向后更新解算"
    assert "6.4s" not in model.flight_text
    assert "距估算窗" not in model.flight_text
    rendered = " ".join(
        (model.bomb_label_text, model.trajectory_text, model.flight_text, model.release.text)
    )
    assert "LOCK" not in rendered.upper()
    assert "NEZ" not in rendered.upper()
    assert "授权" not in rendered


def test_glide_solution_explains_why_the_iron_bomb_surrogate_is_disabled() -> None:
    model = build_bombing_display_model(
        _weapon_snapshot(
            weapon_id="us_gbu_39",
            weapon_display_name="GBU-39/B",
            weapon_role="bomb",
            weapon_planform="glide",
            weapon_status="insufficient_data",
            weapon_solution_valid=False,
            weapon_quality="none",
            weapon_model="strict_official",
            weapon_reason="glide_envelope_unavailable",
            weapon_max_range_m=0.0,
            weapon_time_to_target_s=0.0,
        )
    )

    assert model.release.text == "数据不足"
    assert model.release.fg == Theme.TEXT_MUTED
    assert model.trajectory_text == "POI 12.4km · 估算窗 --"
    assert model.flight_text == "无官方包线，未应用替代模型"


def test_glide_unavailable_state_does_not_claim_out_of_range() -> None:
    model = build_bombing_display_model(
        _weapon_snapshot(
            weapon_id="us_gbu_53",
            weapon_display_name="GBU-53/B",
            weapon_role="bomb",
            weapon_planform="glide",
            weapon_status="insufficient_data",
            weapon_solution_valid=False,
            weapon_quality="none",
            weapon_model="strict_official",
            weapon_reason="glide_envelope_unavailable",
            weapon_max_range_m=0.0,
            weapon_time_to_target_s=0.0,
            weapon_time_to_window_s=0.0,
        )
    )

    assert model.release.text == "数据不足"
    assert "未应用替代模型" in model.flight_text
    assert "过远" not in model.release.text


def test_foxthree_compatible_glide_is_an_experimental_reference_not_a_green_cue() -> None:
    model = build_bombing_display_model(
        _weapon_snapshot(
            weapon_id="us_gbu_39",
            weapon_display_name="GBU-39/B",
            weapon_role="bomb",
            weapon_planform="glide",
            weapon_status="within_experimental_reference",
            weapon_solution_valid=True,
            weapon_quality="experimental",
            weapon_model="foxthree_compatible",
            weapon_reason="foxthree_compatible_glide",
            weapon_max_range_m=32_500.0,
            weapon_time_to_target_s=42.0,
        )
    )

    assert model.release.text == "推测射程内"
    assert model.release.fg == Theme.YELLOW
    assert model.trajectory_text == "POI 12.4km · 滑翔参考约 32.5km"
    assert model.flight_text == "飞行约 42s"


def test_experimental_glide_reference_still_requires_valid_compatible_solution() -> None:
    invalid = build_bombing_display_model(
        _weapon_snapshot(
            weapon_status="within_experimental_reference",
            weapon_solution_valid=False,
            weapon_quality="experimental",
            weapon_model="foxthree_compatible",
            weapon_reason="foxthree_compatible_glide",
            weapon_max_range_m=20_000.0,
        )
    )
    incompatible = build_bombing_display_model(
        _weapon_snapshot(
            weapon_status="beyond_experimental_reference",
            weapon_solution_valid=True,
            weapon_selection_compatible=False,
            weapon_quality="experimental",
            weapon_model="foxthree_compatible",
            weapon_reason="foxthree_compatible_glide",
            weapon_max_range_m=20_000.0,
        )
    )

    assert invalid.release.text == "数据不足"
    assert incompatible.release.text == "不兼容"


def test_aam_solution_states_2d_max_limitations_and_never_turns_green() -> None:
    model = build_bombing_display_model(
        _weapon_snapshot(
            weapon_id="us_aim9l",
            weapon_display_name="AIM-9L",
            weapon_role="aam",
            weapon_target_kind="aircraft",
            weapon_target_name="Hostile",
            weapon_target_distance_m=50.0,
            weapon_min_range_m=0.0,
            weapon_status="within_2d_max_only",
            weapon_reason="aam_2d_max_only",
            weapon_time_to_target_s=0.0,
        )
    )

    assert model.trajectory_text == "空中目标 Hostile 50m · 二维最大约 18.6km"
    assert model.release.text == "最大射程内"
    assert model.release.fg == Theme.YELLOW
    assert model.release.icon != "ok"
    assert model.flight_text == ""


def test_aam_datamine_envelope_shows_tail_head_and_current_aspect_reference() -> None:
    model = build_bombing_display_model(
        _weapon_snapshot(
            weapon_id="us_aim_120c_5",
            weapon_display_name="AIM-120C-5",
            weapon_role="aam",
            weapon_target_kind="aircraft",
            weapon_target_name="Fighter",
            weapon_target_distance_m=80_000.0,
            weapon_min_range_m=1247.15,
            weapon_max_range_m=81_819.2,
            weapon_rear_range_m=13_562.0,
            weapon_head_range_m=81_819.2,
            weapon_target_aspect_cosine=-1.0,
            weapon_status="within_aspect_reference",
            weapon_model="foxthree_compatible",
            weapon_reason="datamine_guidance_envelope",
            weapon_time_to_target_s=0.0,
        )
    )

    assert model.trajectory_text == "空中目标 Fighter 80.0km · 尾/迎 13.6/81.8km"
    assert model.release.text == "当前交战态势可达"
    assert model.release.fg == Theme.YELLOW
    assert model.release.icon != "ok"
    assert model.flight_text == ""
    assert "FoxThree" not in model.flight_text


def test_conditional_propulsion_failure_explains_fail_closed_state() -> None:
    model = build_bombing_display_model(
        _weapon_snapshot(
            weapon_status="insufficient_data",
            weapon_solution_valid=False,
            weapon_reason="conditional_propulsion_unsupported",
            weapon_time_to_target_s=0.0,
            weapon_max_range_m=0.0,
        )
    )

    assert model.release.text == "数据不足"
    assert model.flight_text == "条件推进数据不足"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("incompatible", "不兼容"),
        ("no_target", "无目标"),
        ("insufficient_data", "数据不足"),
        ("too_close", "低于最小射程"),
        ("out_of_range", "超出射程"),
    ],
)
def test_weapon_solution_model_distinguishes_unavailable_states(
    status: str,
    expected: str,
) -> None:
    model = build_bombing_display_model(
        _weapon_snapshot(
            weapon_status=status,
            weapon_solution_valid=False,
            weapon_time_to_target_s=0.0,
            weapon_time_to_window_s=0.0,
        )
    )

    assert model.release.text == expected
    assert model.flight_text


def test_catalog_failure_stays_visible_after_snapshot_render() -> None:
    model = build_bombing_display_model(
        _weapon_snapshot(
            weapon_id="",
            weapon_display_name="",
            weapon_role="",
            weapon_control="",
            weapon_selection_source="unknown",
            weapon_selection_compatible=False,
            weapon_solution_valid=False,
            weapon_status="unknown_weapon",
            weapon_reason="catalog_unavailable",
            weapon_time_to_target_s=0.0,
        )
    )

    assert model.bomb_label_text == "武器目录不可用 · 武器 · 点击切换"
    assert model.release.text == "目录不可用"
    assert model.flight_text == "武器目录不可用"


def test_incompatible_unguided_bomb_does_not_show_ccrp_release_cue() -> None:
    model = build_bombing_display_model(
        _weapon_snapshot(
            weapon_id="us_mk_82",
            weapon_display_name="Mk 82",
            weapon_role="bomb",
            weapon_control="unguided",
            weapon_selection_compatible=False,
            weapon_solution_valid=False,
            weapon_status="incompatible",
            weapon_time_to_target_s=0.0,
        )
    )

    assert model.release.text == "不兼容"
    assert model.flight_text == "请更换兼容武器"


def test_missing_aircraft_identity_stays_data_shortage_not_incompatible() -> None:
    model = build_bombing_display_model(
        _weapon_snapshot(
            weapon_selection_compatible=False,
            weapon_solution_valid=False,
            weapon_status="insufficient_data",
            weapon_time_to_target_s=0.0,
        )
    )

    assert model.release.text == "数据不足"


def test_speed_strip_model_clamps_ratio_and_formats_aircraft() -> None:
    snap = SimpleNamespace(
        overspeed_level="warning",
        overspeed_ratio=0.91,
        overspeed_current_ias_kmh=980.0,
        overspeed_current_mach=1.1,
        overspeed_limit_kmh=1040.0,
        overspeed_limit_mach=0.88,
        overspeed_match=True,
        overspeed_reason="ias+mach",
        aircraft_type_name="very_long_aircraft_name_with_underscores",
    )

    model = build_speed_strip_model(snap)

    assert model.level == "warning"
    assert model.state_text == "接近极限"
    assert model.model_text == "very long aircraft name w...  |  M1.10/0.88"
    assert model.value_text == "IAS 980/1040"
    assert model.fill_color == Theme.YELLOW
    assert model.fill_ratio == 1.0


def test_speed_strip_expands_the_near_limit_band() -> None:
    snap = SimpleNamespace(
        overspeed_level="caution",
        overspeed_ratio=0.80,
        overspeed_current_ias_kmh=800.0,
        overspeed_current_mach=None,
        overspeed_limit_kmh=1000.0,
        overspeed_limit_mach=0.0,
        overspeed_match=True,
        overspeed_reason="ias",
        aircraft_type_name="test_plane",
    )

    model = build_speed_strip_model(snap)

    assert 0.0 < model.fill_ratio < 1.0
    caution, warning, critical = model.marker_ratios
    assert 0.0 < caution < warning < critical < 1.0


def test_speed_strip_keeps_progress_below_dynamic_zoom_trigger() -> None:
    low = build_speed_strip_model(
        SimpleNamespace(
            overspeed_level="safe",
            overspeed_ratio=0.20,
            overspeed_current_ias_kmh=200.0,
            overspeed_current_mach=None,
            overspeed_limit_kmh=1000.0,
            overspeed_limit_mach=0.0,
            overspeed_match=True,
            overspeed_reason="ias",
            aircraft_type_name="test_plane",
        )
    )
    trigger = build_speed_strip_model(
        SimpleNamespace(
            overspeed_level="safe",
            overspeed_ratio=panel_presenter.OverspeedConfig.CAUTION_RATIO * 0.70,
            overspeed_current_ias_kmh=658.0,
            overspeed_current_mach=None,
            overspeed_limit_kmh=1000.0,
            overspeed_limit_mach=0.0,
            overspeed_match=True,
            overspeed_reason="ias",
            aircraft_type_name="test_plane",
        )
    )

    assert low.fill_ratio > 0.0
    assert trigger.fill_ratio > low.fill_ratio


def test_speed_strip_dynamically_stretches_breakup_markers() -> None:
    def model(ratio: float):
        return build_speed_strip_model(
            SimpleNamespace(
                overspeed_level="safe",
                overspeed_ratio=ratio,
                overspeed_current_ias_kmh=ratio * 1000,
                overspeed_current_mach=None,
                overspeed_limit_kmh=1000.0,
                overspeed_limit_mach=0.0,
                overspeed_match=True,
                overspeed_reason="ias",
                aircraft_type_name="test_plane",
            )
        )

    before = model(0.50)
    focused = model(panel_presenter.OverspeedConfig.CAUTION_RATIO)
    before_span = before.marker_ratios[2] - before.marker_ratios[0]
    focused_span = focused.marker_ratios[2] - focused.marker_ratios[0]

    assert focused_span > before_span
    assert focused.viewport_min_ratio > before.viewport_min_ratio


def test_speed_history_header_model_uses_presented_aircraft_name() -> None:
    snap = SimpleNamespace(
        api_down=False,
        phase=SimpleNamespace(name="ALIVE"),
        on_ground=False,
        aircraft_type_name="f_16c_block_50",
    )

    model = build_speed_history_header_model(snap, "safe")

    assert model.phase_text == "飞行中"
    assert model.phase_fg == Theme.GREEN
    assert model.hint_text == "计时和导航已隐藏，当前机型：f 16c block 50"


def test_app_panel_copy_omits_legacy_ambiguous_terms() -> None:
    text = Path(panel_presenter.__file__).read_text(encoding="utf-8")
    for legacy in ("返航紧", "当前航向内", "手选", "官方包线 ·", "二维参考"):
        assert legacy not in text


def test_format_aircraft_type_label_handles_empty_and_long_names() -> None:
    assert format_aircraft_type_label("") == "机型未识别"
    assert format_aircraft_type_label("su_27") == "su 27"
    assert (
        format_aircraft_type_label("abcdefghijklmnopqrstuvwxyz123456")
        == "abcdefghijklmnopqrstuvwxy..."
    )
