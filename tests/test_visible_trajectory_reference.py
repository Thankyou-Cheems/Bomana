"""Behavioral coverage for player-visible trajectory reference loading/matching."""

import pytest

from bomana.core.visible_trajectory_reference import (
    find_visible_trajectory_reference,
    load_visible_trajectory_references,
)


def test_visible_gbu31_observations_preserve_conditions_and_ui_precision() -> None:
    references = load_visible_trajectory_references()
    by_id = {reference.id: reference for reference in references}

    level = by_id["wt-2.57.1.33-f15e-gbu31-level-target-10km"]
    ground = by_id["wt-2.57.1.33-f15e-gbu31-ground-target-10km"]

    assert level.game_version == ground.game_version == "2.57.1.33"
    assert level.source_kind == ground.source_kind == "player_visible_war_thunder_ui"
    assert not level.runtime_reference
    assert not level.target_reached_observed
    assert ground.runtime_reference
    assert ground.target_reached_observed
    assert ground.launch_altitude_m == 3000.0
    assert ground.launch_speed_mps == 250.0
    assert ground.target_altitude_m == 100.0
    assert ground.verified_reach_m == 10000.0
    assert ground.points[-1].flight_time_s == 49.85
    assert ground.points[-1].x_m == 9986.0
    assert ground.points[-1].y_m == 113.0


def test_visible_reference_interpolates_only_along_the_observed_curve() -> None:
    reference = next(
        item for item in load_visible_trajectory_references() if item.runtime_reference
    )

    assert reference.time_at_horizontal_distance(0.0) == 0.0
    assert reference.time_at_horizontal_distance(1953.0) == pytest.approx(8.14)
    assert reference.time_at_horizontal_distance(5034.0) == pytest.approx(22.38)
    assert reference.time_at_horizontal_distance(5000.0) == pytest.approx(22.2229, abs=0.001)
    assert reference.time_at_horizontal_distance(10000.0) == pytest.approx(49.85)


def test_visible_reference_match_is_ground_only_and_stays_near_captured_conditions() -> None:
    common = {
        "launch_altitude_m": 3000.0,
        "launch_speed_mps": 250.0,
        "target_altitude_m": None,
        "target_kind": "zone",
    }

    match = find_visible_trajectory_reference("us_2000lb_gbu31_usaf", **common)
    assert match is not None
    assert match.id == "wt-2.57.1.33-f15e-gbu31-ground-target-10km"
    assert (
        find_visible_trajectory_reference(
            "us_2000lb_gbu31_usaf",
            **(common | {"launch_altitude_m": 3101.0}),
        )
        is None
    )
    assert (
        find_visible_trajectory_reference(
            "us_2000lb_gbu31_usaf",
            **(common | {"launch_speed_mps": 261.0}),
        )
        is None
    )
    assert (
        find_visible_trajectory_reference(
            "us_2000lb_gbu31_usaf",
            **(common | {"target_altitude_m": 251.0}),
        )
        is None
    )
    assert (
        find_visible_trajectory_reference(
            "us_2000lb_gbu31_usaf",
            **(common | {"target_kind": "aircraft"}),
        )
        is None
    )
