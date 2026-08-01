from bomana.ui.dialog_presenter import (
    build_panel_option_specs,
    format_aircraft_override_label,
    format_overspeed_override_summary,
)


def test_panel_option_specs_follow_feature_flags() -> None:
    specs = build_panel_option_specs(
        enable_ccrp=False,
        enable_zones=True,
        enable_airfields=False,
        enable_fuel=True,
        enable_checklist=False,
    )

    assert [spec.key for spec in specs] == [
        "show_zones",
        "show_fuel",
        "show_speed",
        "speed_history_mode",
    ]
    assert specs[0].label == "战区导航"
    assert specs[-1].description == "隐藏计时和其他扩展面板，切换为仅速度提醒的专用界面"


def test_overspeed_override_summary_formats_preview() -> None:
    overrides = {
        "su_27": object(),
        "f_16c_block_50": object(),
        "mig_29": object(),
        "f_15e": object(),
        "mirage_2000": object(),
    }

    assert format_aircraft_override_label("f_16c_block_50") == "f 16c block 50"
    assert format_aircraft_override_label("") == "未知机型"
    assert format_overspeed_override_summary({}) == "当前没有机型覆盖，所有飞机使用全局阈值。"
    assert format_overspeed_override_summary(overrides) == (
        "已配置 5 个机型覆盖：f 15e, f 16c block 50, mig 29, mirage 2000 等 5 个机型"
    )
