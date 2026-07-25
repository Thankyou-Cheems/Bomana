"""Versioned physical-atmosphere curves used by offline bomb ballistics.

Runtime density scaling is derived from official 8111 IAS/TAS telemetry when
possible.
"""

from __future__ import annotations

import math
from typing import Final

DAGOR_ATMOSPHERE_MODEL_ID: Final = "dagor_gamephys_atmosphere_v2"
DAGOR_STANDARD_DENSITY_KG_M3: Final = 1.225
DAGOR_MAX_POLYNOMIAL_ALTITUDE_M: Final = 18_300.0
DAGOR_DENSITY_COEFFICIENTS: Final = (
    1.0,
    -9.59387e-05,
    3.53118e-09,
    -5.83556e-14,
    2.28719e-19,
)
DAGOR_STANDARD_TEMPERATURE_K: Final = 288.16
DAGOR_SOUND_SPEED_FACTOR: Final = 20.1
DAGOR_TEMPERATURE_RATIO_COEFFICIENTS: Final = (
    1.0,
    -2.2771200747e-5,
    2.1806899342e-10,
    -5.7110396870e-14,
    3.9730601515e-18,
)

# Wide enough to retain plausible mission atmosphere overrides while rejecting
# missing, truncated, or nonsensical 8111 speed ratios.
MIN_ESTIMATED_SEA_LEVEL_DENSITY_KG_M3: Final = 0.70
MAX_ESTIMATED_SEA_LEVEL_DENSITY_KG_M3: Final = 1.60
MIN_DENSITY_ESTIMATE_SPEED_KMH: Final = 100.0


def dagor_air_density_ratio(world_altitude_m: float) -> float:
    """Return ``rho(h) / rho0`` for a Dagor world-Y altitude in metres.

    Dagor evaluates the fourth-order polynomial without clamping negative
    altitudes.  Above 18.3 km it freezes the polynomial and applies the
    engine's ``hMax / h`` tail.
    """

    altitude = float(world_altitude_m)
    if not math.isfinite(altitude):
        raise ValueError("world altitude must be finite")

    capped = min(altitude, DAGOR_MAX_POLYNOMIAL_ALTITUDE_M)
    c0, c1, c2, c3, c4 = DAGOR_DENSITY_COEFFICIENTS
    polynomial = (((c4 * capped + c3) * capped + c2) * capped + c1) * capped + c0
    high_altitude_tail = DAGOR_MAX_POLYNOMIAL_ALTITUDE_M / max(
        DAGOR_MAX_POLYNOMIAL_ALTITUDE_M,
        altitude,
    )
    return polynomial * high_altitude_tail


def dagor_air_density(
    world_altitude_m: float,
    sea_level_density_kg_m3: float = DAGOR_STANDARD_DENSITY_KG_M3,
) -> float:
    """Return physical air density in kg/m3 at a Dagor world-Y altitude."""

    sea_level_density = float(sea_level_density_kg_m3)
    if not math.isfinite(sea_level_density) or sea_level_density <= 0.0:
        raise ValueError("sea-level density must be positive and finite")
    return sea_level_density * dagor_air_density_ratio(world_altitude_m)


def dagor_temperature_ratio(world_altitude_m: float) -> float:
    """Return the versioned offline temperature-ratio polynomial."""

    altitude = float(world_altitude_m)
    if not math.isfinite(altitude):
        raise ValueError("world altitude must be finite")
    c0, c1, c2, c3, c4 = DAGOR_TEMPERATURE_RATIO_COEFFICIENTS
    return (((c4 * altitude + c3) * altitude + c2) * altitude + c1) * altitude + c0


def dagor_air_temperature_kelvin(world_altitude_m: float) -> float:
    """Return native-model air temperature in kelvin."""

    ratio = dagor_temperature_ratio(world_altitude_m)
    if ratio <= 0.0:
        raise ValueError("temperature ratio must be positive")
    return DAGOR_STANDARD_TEMPERATURE_K * ratio


def dagor_speed_of_sound(world_altitude_m: float) -> float:
    """Return the versioned offline speed of sound in metres per second."""

    return DAGOR_SOUND_SPEED_FACTOR * math.sqrt(dagor_air_temperature_kelvin(world_altitude_m))


def estimate_dagor_sea_level_density(
    *,
    ias_kmh: float,
    tas_kmh: float,
    world_altitude_m: float,
) -> float | None:
    """Infer Dagor ``rho0`` from official 8111 IAS/TAS telemetry.

    Dagor defines indicated speed as ``TAS * sqrt(rho / stdRho0)``.  Integer
    8111 speeds introduce only small quantisation noise; invalid or implausible
    samples return ``None`` so callers can use the standard atmosphere.
    """

    try:
        ias = float(ias_kmh)
        tas = float(tas_kmh)
        altitude = float(world_altitude_m)
    except TypeError, ValueError:
        return None
    if not all(math.isfinite(value) for value in (ias, tas, altitude)):
        return None
    if ias < MIN_DENSITY_ESTIMATE_SPEED_KMH or tas < MIN_DENSITY_ESTIMATE_SPEED_KMH:
        return None

    density_at_aircraft = DAGOR_STANDARD_DENSITY_KG_M3 * (ias / tas) ** 2
    density_ratio = dagor_air_density_ratio(altitude)
    if not math.isfinite(density_ratio) or density_ratio <= 0.0:
        return None
    estimate = density_at_aircraft / density_ratio
    if not (
        MIN_ESTIMATED_SEA_LEVEL_DENSITY_KG_M3 <= estimate <= MAX_ESTIMATED_SEA_LEVEL_DENSITY_KG_M3
    ):
        return None
    return estimate


__all__ = [
    "DAGOR_ATMOSPHERE_MODEL_ID",
    "DAGOR_DENSITY_COEFFICIENTS",
    "DAGOR_MAX_POLYNOMIAL_ALTITUDE_M",
    "DAGOR_SOUND_SPEED_FACTOR",
    "DAGOR_STANDARD_DENSITY_KG_M3",
    "DAGOR_STANDARD_TEMPERATURE_K",
    "DAGOR_TEMPERATURE_RATIO_COEFFICIENTS",
    "dagor_air_density",
    "dagor_air_density_ratio",
    "dagor_air_temperature_kelvin",
    "dagor_speed_of_sound",
    "dagor_temperature_ratio",
    "estimate_dagor_sea_level_density",
]
