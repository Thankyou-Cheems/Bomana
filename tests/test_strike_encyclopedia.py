from __future__ import annotations

import pytest

from bomana.core.strike_encyclopedia import (
    load_strike_encyclopedia,
    project_airfield_scene,
)


def test_default_encyclopedia_exposes_source_backed_zone_tiers_and_four_layouts() -> None:
    encyclopedia = load_strike_encyclopedia()

    assert [tier.balance_level_range for tier in encyclopedia.bombing_point_tiers] == [
        (0, 3),
        (4, 7),
        (8, 11),
        (12, 16),
        (17, 20),
        (21, 50),
    ]
    assert [tier.planes_mission_hp for tier in encyclopedia.bombing_point_tiers] == [
        4_000.0,
        6_000.0,
        10_000.0,
        16_000.0,
        22_000.0,
        25_900.0,
    ]
    assert [tier.heli_mission_hp for tier in encyclopedia.bombing_point_tiers] == [
        400.0,
        600.0,
        1_000.0,
        1_600.0,
        2_200.0,
        2_590.0,
    ]
    assert [tier.auxiliary_module_mission_hp for tier in encyclopedia.airport_tiers] == [
        12_000.0,
        34_000.0,
        48_000.0,
        100_000.0,
        120_000.0,
        160_000.0,
    ]
    assert encyclopedia.practical_references[0].evidence_kind == "official_wiki_reference"
    assert encyclopedia.practical_references[0].weapon_count == 6
    assert encyclopedia.practical_references[0].total_tnte_reference_kg == pytest.approx(1634.4)
    assert encyclopedia.practical_references[0].is_mission_damage_formula is False
    assert encyclopedia.bombing_point_behavior.hp_fire_mult == pytest.approx(0.1)
    assert encyclopedia.bombing_point_behavior.fire_speed == pytest.approx(0.03)
    assert encyclopedia.bombing_point_behavior.respawn_seconds == pytest.approx(240.0)
    assert encyclopedia.airport_behavior.has_fire_tail is False
    assert encyclopedia.airport_behavior.repair_timing_kind == "per_airfield_repair_visit"
    assert encyclopedia.bombing_zone_tnt_conversion.hp_to_tnt_equivalent_tons == pytest.approx(
        0.000125
    )
    mk83 = next(
        weapon
        for weapon in encyclopedia.weapon_references
        if weapon.weapon_id == "us_1000lb_mk_83_ldgp"
    )
    assert mk83.strength_equivalent == pytest.approx(1.35)
    assert mk83.mission_damage_model == "tnt_equivalent"
    mk77 = next(
        weapon
        for weapon in encyclopedia.weapon_references
        if weapon.weapon_id == "us_500lb_mk77_mod4"
    )
    assert mk77.mission_damage_model == "unsupported_napalm"
    assert [layout.layout_id for layout in encyclopedia.airfield_layouts] == [
        "long_3200",
        "layout_a_1670",
        "layout_b_1635",
        "layout_c_1635",
    ]


def test_long_runway_layout_and_scene_come_from_exact_module_rectangles() -> None:
    encyclopedia = load_strike_encyclopedia()
    layout = encyclopedia.airfield_layouts[0]
    modules = {module.module_id: module for module in layout.modules}

    assert layout.runway_length_m == pytest.approx(3200.0)
    assert modules["airfield"].width_m == pytest.approx(120.0)
    assert modules["storage"].start_xz == pytest.approx((1700.0, 200.0))
    assert modules["storage"].end_xz == pytest.approx((1150.0, 200.0))
    assert modules["parking"].start_xz == pytest.approx((-90.0, 15.0))
    assert modules["parking"].end_xz == pytest.approx((-930.0, 15.0))
    assert modules["dwelling"].start_xz == pytest.approx((400.0, 110.0))
    assert modules["dwelling"].end_xz == pytest.approx((0.0, 110.0))

    scene = project_airfield_scene(layout, width=720, height=380)

    assert [shape.module_id for shape in scene.shapes] == [
        "airfield",
        "storage",
        "parking",
        "dwelling",
    ]
    assert all(
        0.0 <= x <= scene.width and 0.0 <= y <= scene.height
        for shape in scene.shapes
        for x, y in shape.points
    )
    assert scene.disclaimer == "离线静态模块几何 · 非服务器命中框"


def test_airfield_scene_uses_the_same_north_up_handedness_as_navigation() -> None:
    layout = load_strike_encyclopedia().airfield_layouts[0]
    scene = project_airfield_scene(layout, width=720, height=380)
    shapes = {shape.module_id: shape for shape in scene.shapes}

    def center(points: tuple[tuple[float, float], ...]) -> tuple[float, float]:
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    runway = shapes["airfield"]
    runway_start = center((runway.points[0], runway.points[3]))
    runway_end = center((runway.points[1], runway.points[2]))
    runway_center = center(runway.points)
    storage_center = center(shapes["storage"].points)
    side_sign = (runway_end[0] - runway_start[0]) * (storage_center[1] - runway_center[1]) - (
        runway_end[1] - runway_start[1]
    ) * (storage_center[0] - runway_center[0])

    # Navigation maps world +Z toward smaller screen Y.  For the locked 3200 m
    # template this places storage on the positive signed side of start -> end.
    assert side_sign > 0.0
