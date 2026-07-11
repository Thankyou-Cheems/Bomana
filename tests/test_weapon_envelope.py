"""Tests for Datamine conditional guided-weapon envelope interpolation."""

from __future__ import annotations

import copy

import pytest

from bomana.core.weapon_envelope import (
    REASON_INVALID_SHAPE,
    REASON_MISSING_FIELD,
    REASON_UNAVAILABLE_CELL,
    interpolate_aspect,
    interpolate_aspect_endpoints,
    interpolate_envelope,
)


def _aim120c5_envelope() -> dict:
    """AIM-120C-5 anchors from us_aim_120c_5.blkx."""

    return {
        # A deliberately conflicting top-level cap proves that rangeMax cells
        # are initial target distances and are not clamped by maxDistance.
        "max_distance_m": 15_000.0,
        "tables": [
            {
                "table": "table0",
                "altitude_m": 1_000.0,
                "fighter_mach": [0.9, 1.2],
                "target_mach": [0.9, 0.9],
                "target_mach2_mult": -1.0,
                "range_min_m": [435.591, 1_241.39, 530.966, 1_311.7],
                "range_max_m": [8_267.21, 62_713.2, 9_677.12, 67_499.2],
                "time_max_s": [25.4585, 93.0981, 26.5746, 97.3432],
            },
            {
                "table": "table1",
                "altitude_m": 5_000.0,
                "fighter_mach": [0.9, 1.2],
                "target_mach": [0.9, 0.9],
                "target_mach2_mult": -1.0,
                "range_min_m": [548.949, 1_247.15, 632.025, 1_288.37],
                "range_max_m": [13_562.0, 81_819.2, 15_747.1, 92_218.4],
                "time_max_s": [39.0833, 70.3742, 41.1873, 118.921],
            },
            {
                "table": "table2",
                "altitude_m": 10_000.0,
                "fighter_mach": [0.9, 1.2],
                "target_mach": [0.9, 0.9],
                "target_mach2_mult": -1.0,
                "range_min_m": [913.146, 2_079.19, 884.301, 2_260.35],
                "range_max_m": [31_951.9, 107_881.0, 45_065.3, 114_953.0],
                "time_max_s": [86.772, 120.0, 113.982, 120.0],
            },
            {
                "table": "table3",
                "altitude_m": 15_000.0,
                "fighter_mach": [0.9, 1.2],
                "target_mach": [0.9, 0.9],
                "target_mach2_mult": -1.0,
                "range_min_m": [1_145.36, 2_747.53, 1_099.82, 2_754.71],
                "range_max_m": [60_447.3, 119_063.0, 67_602.2, 126_389.0],
                "time_max_s": [120.0, 120.0, 120.0, 120.0],
            },
        ],
    }


def _interpolate(envelope: dict, **overrides) -> object:
    values = {
        "field": "range_max_m",
        "altitude_m": 5_000.0,
        "fighter_mach": 0.9,
        "target_radial_mach": -0.9,
    }
    values.update(overrides)
    return interpolate_envelope(envelope, **values)


def test_aim120c5_head_on_anchor_exposes_eighty_kilometre_range() -> None:
    envelope = _aim120c5_envelope()

    head_on = _interpolate(envelope)
    tail_chase = _interpolate(envelope, target_radial_mach=0.9)
    endpoints = interpolate_aspect_endpoints(
        envelope,
        field="range_max_m",
        altitude_m=5_000.0,
        fighter_mach=0.9,
    )

    assert head_on.available
    assert head_on.value == pytest.approx(81_819.2)
    assert tail_chase.value == pytest.approx(13_562.0)
    assert endpoints.available
    assert endpoints.head_on.value == pytest.approx(81_819.2)
    assert endpoints.head_on.target_radial_mach == pytest.approx(-0.9)
    assert endpoints.tail_chase.value == pytest.approx(13_562.0)
    assert endpoints.tail_chase.target_radial_mach == pytest.approx(0.9)


def test_aspect_api_maps_tail_head_and_side_on_each_row() -> None:
    envelope = _aim120c5_envelope()

    tail = interpolate_aspect(
        envelope,
        field="range_max_m",
        altitude_m=5_000.0,
        fighter_mach=0.9,
        aspect_cosine=1.0,
    )
    head = interpolate_aspect(
        envelope,
        field="range_max_m",
        altitude_m=5_000.0,
        fighter_mach=0.9,
        aspect_cosine=-1.0,
    )
    side = interpolate_aspect(
        envelope,
        field="range_max_m",
        altitude_m=5_000.0,
        fighter_mach=0.9,
        aspect_cosine=0.0,
    )

    assert tail.value == pytest.approx(13_562.0)
    assert head.value == pytest.approx(81_819.2)
    assert side.value == pytest.approx((13_562.0 + 81_819.2) / 2.0)


def test_interpolation_order_covers_target_fighter_and_altitude_midpoints() -> None:
    envelope = _aim120c5_envelope()

    fighter_midpoint = _interpolate(envelope, fighter_mach=1.05)
    altitude_midpoint = _interpolate(envelope, altitude_m=7_500.0)
    three_dimensional_midpoint = _interpolate(
        envelope,
        altitude_m=7_500.0,
        fighter_mach=1.05,
        target_radial_mach=0.0,
    )

    assert fighter_midpoint.value == pytest.approx((81_819.2 + 92_218.4) / 2.0)
    assert altitude_midpoint.value == pytest.approx((81_819.2 + 107_881.0) / 2.0)
    assert three_dimensional_midpoint.value == pytest.approx(62_899.7375)


def test_all_axes_clamp_to_endpoints_without_extrapolation() -> None:
    envelope = _aim120c5_envelope()

    below_altitude_fast_fighter_closing = _interpolate(
        envelope,
        altitude_m=-10_000.0,
        fighter_mach=99.0,
        target_radial_mach=-99.0,
    )
    above_altitude_slow_fighter_receding = _interpolate(
        envelope,
        altitude_m=99_000.0,
        fighter_mach=-99.0,
        target_radial_mach=99.0,
    )
    aspect_above_one = interpolate_aspect(
        envelope,
        field="range_max_m",
        altitude_m=5_000.0,
        fighter_mach=0.9,
        aspect_cosine=50.0,
    )

    assert below_altitude_fast_fighter_closing.value == pytest.approx(67_499.2)
    assert above_altitude_slow_fighter_receding.value == pytest.approx(60_447.3)
    assert aspect_above_one.value == pytest.approx(13_562.0)


def test_zero_cell_is_not_crossed_but_unrelated_endpoint_remains_usable() -> None:
    envelope = _aim120c5_envelope()
    envelope["tables"][1]["range_max_m"][1] = 0.0

    crossing = _interpolate(envelope, target_radial_mach=0.0)
    positive_endpoint = _interpolate(envelope, target_radial_mach=0.9)
    endpoints = interpolate_aspect_endpoints(
        envelope,
        field="range_max_m",
        altitude_m=5_000.0,
        fighter_mach=0.9,
    )

    assert not crossing.available
    assert crossing.reason == REASON_UNAVAILABLE_CELL
    assert positive_endpoint.available
    assert positive_endpoint.value == pytest.approx(13_562.0)
    assert endpoints.tail_chase.available
    assert not endpoints.head_on.available


def test_missing_and_malformed_cells_return_machine_readable_unavailable() -> None:
    malformed = _aim120c5_envelope()
    malformed["tables"][1]["range_max_m"].pop()
    missing = _aim120c5_envelope()

    malformed_result = _interpolate(malformed)
    missing_result = _interpolate(missing, field="range_max_dogfight_m")
    malformed_root = interpolate_envelope(
        None,
        field="range_max_m",
        altitude_m=0.0,
        fighter_mach=0.0,
        target_radial_mach=0.0,
    )

    assert not malformed_result.available
    assert malformed_result.reason == REASON_INVALID_SHAPE
    assert not missing_result.available
    assert missing_result.reason == REASON_MISSING_FIELD
    assert not malformed_root.available


def test_generic_field_support_covers_range_min_and_time_max() -> None:
    envelope = _aim120c5_envelope()

    minimum = _interpolate(envelope, field="range_min_m")
    maximum_time = _interpolate(envelope, field="time_max_s")

    assert minimum.value == pytest.approx(1_247.15)
    assert maximum_time.value == pytest.approx(70.3742)


def test_each_fighter_row_uses_its_own_target_mach_axis() -> None:
    envelope = {
        "tables": [
            {
                "table": "table0",
                "altitude_m": 1_000.0,
                "fighter_mach": [1.0, 2.0],
                "target_mach": [0.5, 1.0],
                "target_mach2_mult": -1.0,
                "range_min_m": [1.0, 1.0, 1.0, 1.0],
                "range_max_m": [10.0, 100.0, 20.0, 200.0],
            }
        ]
    }

    signed_radial = interpolate_envelope(
        envelope,
        field="range_max_m",
        altitude_m=1_000.0,
        fighter_mach=1.5,
        target_radial_mach=-0.5,
    )
    head_on_geometry = interpolate_aspect(
        envelope,
        field="range_max_m",
        altitude_m=1_000.0,
        fighter_mach=1.5,
        aspect_cosine=-1.0,
    )
    endpoints = interpolate_aspect_endpoints(
        envelope,
        field="range_max_m",
        altitude_m=1_000.0,
        fighter_mach=1.5,
    )

    # Row 1 clamps to 100 at -0.5.  Row 2 interpolates to 155 at -0.5,
    # then fighter Mach interpolates those row results.
    assert signed_radial.value == pytest.approx(127.5)
    assert head_on_geometry.value == pytest.approx(150.0)
    assert endpoints.tail_chase.target_radial_mach == pytest.approx(0.75)
    assert endpoints.head_on.target_radial_mach == pytest.approx(-0.75)


def test_signed_target_mach_axis_can_store_head_on_in_the_first_cell() -> None:
    envelope = {
        "tables": [
            {
                "table": "table0",
                "altitude_m": 1500.0,
                "fighter_mach": [0.7, 1.0],
                "target_mach": [-0.7, -0.7],
                "target_mach2_mult": -1.0,
                "range_min_m": [3200.0, 1200.0, 3400.0, 1050.0],
                "range_max_m": [27000.0, 5500.0, 28000.0, 6500.0],
            }
        ]
    }

    endpoints = interpolate_aspect_endpoints(
        envelope,
        field="range_max_m",
        altitude_m=1500.0,
        fighter_mach=0.7,
    )
    tail = interpolate_aspect(
        envelope,
        field="range_max_m",
        altitude_m=1500.0,
        fighter_mach=0.7,
        aspect_cosine=1.0,
    )
    head = interpolate_aspect(
        envelope,
        field="range_max_m",
        altitude_m=1500.0,
        fighter_mach=0.7,
        aspect_cosine=-1.0,
    )

    assert endpoints.tail_chase.value == pytest.approx(5500.0)
    assert endpoints.head_on.value == pytest.approx(27000.0)
    assert tail.value == pytest.approx(5500.0)
    assert head.value == pytest.approx(27000.0)


def test_descending_fighter_mach_axis_preserves_row_cell_order() -> None:
    envelope = {
        "tables": [
            {
                "table": "table0",
                "altitude_m": 5000.0,
                "fighter_mach": [1.2, 0.9],
                "target_mach": [0.9, 0.9],
                "target_mach2_mult": -1.0,
                "range_min_m": [632.025, 1288.37, 548.949, 1247.15],
                "range_max_m": [15747.1, 92218.4, 13562.0, 81819.2],
            }
        ]
    }

    endpoints = interpolate_aspect_endpoints(
        envelope,
        field="range_max_m",
        altitude_m=5000.0,
        fighter_mach=0.9,
    )

    assert endpoints.tail_chase.value == pytest.approx(13562.0)
    assert endpoints.head_on.value == pytest.approx(81819.2)


def test_inputs_are_not_mutated() -> None:
    envelope = _aim120c5_envelope()
    before = copy.deepcopy(envelope)

    _interpolate(envelope, altitude_m=7_500.0, fighter_mach=1.05, target_radial_mach=0.0)

    assert envelope == before
