from types import SimpleNamespace

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

    assert model.main_text == "油量 420kg / 18%"
    assert model.main_fg == Theme.YELLOW
    assert model.time.text == "余 12:34"
    assert model.return_status.icon == "warning"
    assert model.return_status.text == "返航紧"
    assert model.detail_text == "油耗 38kg/min · 高度 1234m"
    assert model.altitude_text == ""
    assert model.return_detail_text == "返航 需 250kg (50%) · 35km"


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

    assert model.bomb_label_text == "炸弹 FAB-100 · 点击更换"
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


def test_format_aircraft_type_label_handles_empty_and_long_names() -> None:
    assert format_aircraft_type_label("") == "机型未识别"
    assert format_aircraft_type_label("su_27") == "su 27"
    assert (
        format_aircraft_type_label("abcdefghijklmnopqrstuvwxyz123456")
        == "abcdefghijklmnopqrstuvwxy..."
    )
