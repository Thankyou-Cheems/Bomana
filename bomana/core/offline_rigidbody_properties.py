"""Derive solver properties from the compact offline rigid-body catalog."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Final

OFFLINE_RIGIDBODY_PROPERTY_SCHEMA_VERSION: Final = 2
OFFLINE_RIGIDBODY_PROPERTY_PROFILE_ID: Final = "offline_rigidbody_v2"
OFFLINE_DEFAULT_AXIAL_COEFFICIENT: Final = 0.2
OFFLINE_DEFAULT_NORMAL_COEFFICIENT: Final = 2.2
OFFLINE_DEFAULT_NORMAL_AOA_LIMIT: Final = 1.0
OFFLINE_DEFAULT_AOA_DRAG_COEFFICIENT: Final = 9.0
OFFLINE_DEFAULT_LIFT_AREA_SCALE: Final = 1.0


class OfflineRigidbodyPropertyError(ValueError):
    """Raised when a catalog record cannot form solver properties."""


@dataclass(frozen=True, slots=True)
class OfflineRigidbodyProperties:
    """Complete derived property block consumed by the solver."""

    schema_version: int
    mass_kg: float
    diameter_m: float
    length_m: float
    frontal_area_m2: float
    lateral_area_m2: float
    stabilizer_lever_m: float
    inertia_x_kg_m2: float
    inertia_y_kg_m2: float
    inertia_z_kg_m2: float
    axial_coefficient: float
    normal_coefficient: float
    normal_aoa_limit: float
    aoa_drag_coefficient: float
    rotational_damping_x: float
    rotational_damping_y: float
    rotational_damping_z: float
    rotational_reference_m4: float

    def to_solver_payload(self) -> dict[str, int | float]:
        """Return the neutral payload embedded in one runtime record."""

        return asdict(self)


def _number(
    values: Mapping[str, Any],
    key: str,
    *,
    default: float | None = None,
    positive: bool = False,
) -> float:
    if key not in values:
        if default is None:
            raise OfflineRigidbodyPropertyError(
                f"missing offline rigid-body field: {key}"
            )
        return default
    try:
        result = float(values[key])
    except (TypeError, ValueError) as exc:
        raise OfflineRigidbodyPropertyError(
            f"invalid offline rigid-body field: {key}"
        ) from exc
    if not math.isfinite(result) or (positive and result <= 0.0):
        raise OfflineRigidbodyPropertyError(
            f"invalid offline rigid-body field: {key}"
        )
    return result


def derive_offline_rigidbody_properties(
    values: Mapping[str, Any],
) -> OfflineRigidbodyProperties:
    """Derive areas, inertia, and damping from compact catalog primitives."""

    mass = _number(values, "mass_kg", positive=True)
    diameter = _number(values, "diameter_m", positive=True)
    length = _number(values, "length_m", positive=True)
    lift_area_scale = _number(
        values,
        "lift_area_scale",
        default=OFFLINE_DEFAULT_LIFT_AREA_SCALE,
        positive=True,
    )
    stabilizer_lever = _number(values, "stabilizer_lever_m")
    axial_coefficient = _number(
        values,
        "axial_coefficient",
        default=OFFLINE_DEFAULT_AXIAL_COEFFICIENT,
        positive=True,
    )
    normal_coefficient = _number(
        values,
        "normal_coefficient",
        default=OFFLINE_DEFAULT_NORMAL_COEFFICIENT,
    )
    normal_aoa_limit = _number(
        values,
        "normal_aoa_limit",
        default=OFFLINE_DEFAULT_NORMAL_AOA_LIMIT,
        positive=True,
    )
    aoa_drag_coefficient = _number(
        values,
        "aoa_drag_coefficient",
        default=OFFLINE_DEFAULT_AOA_DRAG_COEFFICIENT,
    )

    radius = diameter / 2.0
    if 5.0 * length > radius:
        inertia_x = mass * radius**2
        inertia_y = mass * (length**2 + 3.0 * radius**2) / 12.0
    else:
        inertia_x = 0.4 * mass * radius**2
        inertia_y = 0.2 * mass * (radius**2 + length**2 / 4.0)
    frontal_area = math.pi * diameter**2 / 4.0

    return OfflineRigidbodyProperties(
        schema_version=OFFLINE_RIGIDBODY_PROPERTY_SCHEMA_VERSION,
        mass_kg=mass,
        diameter_m=diameter,
        length_m=length,
        frontal_area_m2=frontal_area,
        lateral_area_m2=0.3 * lift_area_scale * length * diameter,
        stabilizer_lever_m=stabilizer_lever,
        inertia_x_kg_m2=inertia_x,
        inertia_y_kg_m2=inertia_y,
        inertia_z_kg_m2=inertia_y,
        axial_coefficient=axial_coefficient,
        normal_coefficient=normal_coefficient,
        normal_aoa_limit=normal_aoa_limit,
        aoa_drag_coefficient=aoa_drag_coefficient,
        rotational_damping_x=1.0,
        rotational_damping_y=1.0,
        rotational_damping_z=1.0,
        rotational_reference_m4=length**2 * frontal_area,
    )


def offline_rigidbody_property_profile() -> dict[str, int | str]:
    """Return the public schema identity for generated catalogs."""

    return {
        "schema_version": OFFLINE_RIGIDBODY_PROPERTY_SCHEMA_VERSION,
        "profile_id": OFFLINE_RIGIDBODY_PROPERTY_PROFILE_ID,
    }


__all__ = [
    "OFFLINE_DEFAULT_AOA_DRAG_COEFFICIENT",
    "OFFLINE_DEFAULT_AXIAL_COEFFICIENT",
    "OFFLINE_DEFAULT_LIFT_AREA_SCALE",
    "OFFLINE_DEFAULT_NORMAL_AOA_LIMIT",
    "OFFLINE_DEFAULT_NORMAL_COEFFICIENT",
    "OFFLINE_RIGIDBODY_PROPERTY_PROFILE_ID",
    "OFFLINE_RIGIDBODY_PROPERTY_SCHEMA_VERSION",
    "OfflineRigidbodyProperties",
    "OfflineRigidbodyPropertyError",
    "derive_offline_rigidbody_properties",
    "offline_rigidbody_property_profile",
]
