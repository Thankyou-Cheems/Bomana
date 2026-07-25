import math

import pytest

from bomana.core.atmosphere import (
    DAGOR_ATMOSPHERE_MODEL_ID,
    dagor_air_density,
    dagor_air_density_ratio,
    dagor_air_temperature_kelvin,
    dagor_speed_of_sound,
    dagor_temperature_ratio,
    estimate_dagor_sea_level_density,
)


@pytest.mark.parametrize(
    ("altitude_m", "expected_ratio"),
    (
        (-400.0, 1.0389442094136063),
        (0.0, 1.0),
        (1_000.0, 0.907534353119),
        (3_000.0, 0.742407445039),
        (5_000.0, 0.601434499375),
        (10_000.0, 0.3376625899999999),
        (18_300.0, 0.09489826017499992),
        (20_000.0, 0.08683190806012493),
    ),
)
def test_dagor_density_curve_matches_versioned_offline_values(
    altitude_m: float,
    expected_ratio: float,
) -> None:
    assert DAGOR_ATMOSPHERE_MODEL_ID == "dagor_gamephys_atmosphere_v2"
    assert dagor_air_density_ratio(altitude_m) == pytest.approx(expected_ratio, abs=1e-15)


def test_ias_tas_ratio_recovers_mission_sea_level_density() -> None:
    world_altitude_m = 3_869.0
    expected_rho0 = 1.184
    tas_kmh = 973.0
    local_density = dagor_air_density(world_altitude_m, expected_rho0)
    ias_kmh = tas_kmh * math.sqrt(local_density / 1.225)

    estimate = estimate_dagor_sea_level_density(
        ias_kmh=ias_kmh,
        tas_kmh=tas_kmh,
        world_altitude_m=world_altitude_m,
    )

    assert estimate == pytest.approx(expected_rho0, abs=1e-12)


@pytest.mark.parametrize(
    ("altitude_m", "expected_ratio", "expected_sound_ms"),
    (
        (0.0, 1.0, 341.20305039668096),
        (5_000.0, 0.8869400840864375, 321.3364907339452),
        (10_000.0, 0.776715096517, 300.7071664526919),
    ),
)
def test_temperature_and_sound_speed_match_versioned_offline_polynomial(
    altitude_m: float,
    expected_ratio: float,
    expected_sound_ms: float,
) -> None:
    assert dagor_temperature_ratio(altitude_m) == pytest.approx(expected_ratio)
    assert dagor_air_temperature_kelvin(altitude_m) == pytest.approx(288.16 * expected_ratio)
    assert dagor_speed_of_sound(altitude_m) == pytest.approx(expected_sound_ms)


@pytest.mark.parametrize(
    ("ias_kmh", "tas_kmh", "altitude_m"),
    (
        (0.0, 800.0, 1_000.0),
        (800.0, 0.0, 1_000.0),
        (float("nan"), 800.0, 1_000.0),
        (800.0, 800.0, float("inf")),
    ),
)
def test_invalid_8111_density_inputs_use_caller_fallback(
    ias_kmh: float,
    tas_kmh: float,
    altitude_m: float,
) -> None:
    assert (
        estimate_dagor_sea_level_density(
            ias_kmh=ias_kmh,
            tas_kmh=tas_kmh,
            world_altitude_m=altitude_m,
        )
        is None
    )
