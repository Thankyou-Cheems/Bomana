import math

import pytest

from bomana.core.release_state import target_track_geometry, update_release_track
from bomana.core.state import MapInfo, ZoneNavigationState


def _map_info() -> MapInfo:
    return MapInfo(
        valid=True,
        map_min=[0.0, 0.0],
        map_max=[10_000.0, 10_000.0],
    )


def test_causal_track_recovers_world_velocity_and_heading() -> None:
    nav = ZoneNavigationState()
    map_info = _map_info()
    base = 100.0
    for index in range(4):
        elapsed = index * 0.05
        update_release_track(
            nav,
            normalized_x=(5_000.0 + 100.0 * elapsed) / 10_000.0,
            normalized_y=(10_000.0 - (5_000.0 + 200.0 * elapsed)) / 10_000.0,
            map_info=map_info,
            now=base + elapsed,
        )

    assert nav.release_track_valid
    assert nav.release_velocity_x_ms == pytest.approx(100.0)
    assert nav.release_velocity_z_ms == pytest.approx(200.0)
    assert nav.release_ground_speed_ms == pytest.approx(math.hypot(100.0, 200.0))
    assert nav.release_track_heading_deg == pytest.approx(26.565051177)
    assert nav.release_track_residual_m < 1e-8


def test_track_projects_latest_observation_to_common_solution_time() -> None:
    nav = ZoneNavigationState()
    map_info = _map_info()
    base = 100.0
    estimate = None
    for index in range(4):
        elapsed = index * 0.05
        estimate = update_release_track(
            nav,
            normalized_x=(5_000.0 + 100.0 * elapsed) / 10_000.0,
            normalized_y=(10_000.0 - (5_000.0 + 200.0 * elapsed)) / 10_000.0,
            map_info=map_info,
            sample_time=base + elapsed,
            solution_time=base + (0.18 if index == 3 else elapsed),
        )

    assert estimate is not None
    assert estimate.valid
    assert estimate.sample_time == pytest.approx(100.15)
    assert estimate.solution_time == pytest.approx(100.18)
    assert estimate.sample_age_s == pytest.approx(0.03)
    assert estimate.world_x_m == pytest.approx(5_018.0)
    assert estimate.world_z_m == pytest.approx(5_036.0)


def test_track_fit_caps_history_to_latest_four_samples_during_a_turn() -> None:
    nav = ZoneNavigationState()
    map_info = _map_info()
    base = 100.0
    positions = (
        (0.00, 4_900.0, 4_900.0),
        (0.05, 5_005.0, 5_010.0),
        (0.10, 5_010.0, 5_020.0),
        (0.15, 5_015.0, 5_030.0),
        (0.20, 5_020.0, 5_040.0),
    )
    estimate = None
    for elapsed, world_x, world_z in positions:
        estimate = update_release_track(
            nav,
            normalized_x=world_x / 10_000.0,
            normalized_y=(10_000.0 - world_z) / 10_000.0,
            map_info=map_info,
            now=base + elapsed,
        )

    assert estimate is not None
    assert estimate.valid
    assert estimate.sample_count == 4
    assert estimate.sample_span_s == pytest.approx(0.15)
    assert estimate.velocity_x_ms == pytest.approx(100.0)
    assert estimate.velocity_z_ms == pytest.approx(200.0)


def test_nominal_10hz_track_accepts_small_timestamp_jitter() -> None:
    nav = ZoneNavigationState()
    map_info = _map_info()
    base = 100.0
    estimate = None
    for elapsed in (0.0, 0.101, 0.202):
        estimate = update_release_track(
            nav,
            normalized_x=(5_000.0 + 100.0 * elapsed) / 10_000.0,
            normalized_y=(10_000.0 - (5_000.0 + 200.0 * elapsed)) / 10_000.0,
            map_info=map_info,
            now=base + elapsed,
        )

    assert estimate is not None
    assert estimate.valid
    assert estimate.sample_count == 3
    assert estimate.sample_span_s == pytest.approx(0.202)
    assert estimate.velocity_x_ms == pytest.approx(100.0)
    assert estimate.velocity_z_ms == pytest.approx(200.0)


def test_body_heading_rate_is_diagnostic_and_does_not_rotate_track() -> None:
    nav = ZoneNavigationState()
    map_info = _map_info()
    base = 100.0
    for index, heading_deg in enumerate((0.0, 1.0, 2.0, 3.0)):
        elapsed = index * 0.05
        heading_rad = math.radians(heading_deg)
        update_release_track(
            nav,
            normalized_x=5_000.0 / 10_000.0,
            normalized_y=(10_000.0 - (5_000.0 + 200.0 * elapsed)) / 10_000.0,
            map_info=map_info,
            now=base + elapsed,
            body_direction_x=math.sin(heading_rad),
            body_direction_y=-math.cos(heading_rad),
        )

    assert nav.release_track_valid
    assert nav.release_velocity_x_ms == pytest.approx(0.0, abs=1e-8)
    assert nav.release_velocity_z_ms == pytest.approx(200.0)
    assert nav.release_body_heading_rate_available
    assert nav.release_body_heading_rate_deg_s == pytest.approx(20.0)


def test_duplicate_map_frame_is_not_appended_and_expires_at_age_limit() -> None:
    nav = ZoneNavigationState()
    map_info = _map_info()
    base = 100.0
    for index in range(4):
        elapsed = index * 0.05
        update_release_track(
            nav,
            normalized_x=(5_000.0 + 100.0 * elapsed) / 10_000.0,
            normalized_y=(10_000.0 - (5_000.0 + 200.0 * elapsed)) / 10_000.0,
            map_info=map_info,
            sample_time=base + elapsed,
            solution_time=base + elapsed,
        )
    sample_count = len(nav.release_track_samples)

    estimate = update_release_track(
        nav,
        normalized_x=5_015.0 / 10_000.0,
        normalized_y=(10_000.0 - 5_030.0) / 10_000.0,
        map_info=map_info,
        sample_time=100.15,
        solution_time=100.31,
    )

    assert len(nav.release_track_samples) == sample_count
    assert not estimate.valid
    assert estimate.sample_time == pytest.approx(100.15)
    assert estimate.sample_age_s == pytest.approx(0.16)
    assert not nav.release_track_valid


def test_target_geometry_uses_along_and_cross_track_components() -> None:
    nav = ZoneNavigationState(
        release_track_valid=True,
        release_world_x_m=5_000.0,
        release_world_z_m=5_000.0,
        release_velocity_x_ms=0.0,
        release_velocity_z_ms=200.0,
        release_ground_speed_ms=200.0,
    )

    geometry = target_track_geometry(
        nav,
        target_x=5_050.0 / 10_000.0,
        target_y=(10_000.0 - 6_000.0) / 10_000.0,
        map_info=_map_info(),
    )

    assert geometry is not None
    assert geometry.distance_m == pytest.approx(math.hypot(50.0, 1_000.0))
    assert geometry.along_track_m == pytest.approx(1_000.0)
    assert geometry.cross_track_m == pytest.approx(-50.0)


def test_missing_map_info_fails_closed_and_clears_track() -> None:
    nav = ZoneNavigationState(
        release_track_valid=True,
        release_ground_speed_ms=200.0,
        ground_speed=0.002,
    )

    estimate = update_release_track(
        nav,
        normalized_x=0.5,
        normalized_y=0.5,
        map_info=MapInfo(valid=False),
        now=1.0,
    )

    assert not estimate.valid
    assert not nav.release_track_valid
    assert nav.release_ground_speed_ms == 0.0
    assert nav.ground_speed == 0.0
