"""Versioned offline iron-bomb model metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from bomana.core.offline_rigidbody_properties import (
    OFFLINE_DEFAULT_AXIAL_COEFFICIENT,
)
from bomana.core.offline_rigidbody_solver import OfflineRigidbodySolverProperties

OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID: Final = "offline_rigidbody_projection_v2"
OFFLINE_RIGIDBODY_UNAVAILABLE_MODEL_ID: Final = "offline_rigidbody_unavailable"

OFFLINE_STEP_SECONDS: Final = 1.0 / 48.0
OFFLINE_GRAVITY_MS2: Final = 9.81

RUNTIME_INPUT_SOURCES: Final = (
    "manual_selected_weapon_rigidbody_properties",
    "8111_release_altitude_tas_vy_ias_aoa",
    "8111_map_position_history",
    "8111_map_target_coordinates",
    "offline_terrain_heightmap",
    "offline_ballistic_model",
)


@dataclass(frozen=True, slots=True)
class OfflineBallisticsModel:
    """Resolved production model for one selected bomb."""

    model_id: str
    category: str
    quality: str
    supported: bool
    unavailable_reason: str = ""
    validation_weapon_id: str = ""
    step_seconds: float = OFFLINE_STEP_SECONDS
    gravity_ms2: float = OFFLINE_GRAVITY_MS2
    axial_coefficient: float = OFFLINE_DEFAULT_AXIAL_COEFFICIENT
    effective_axial_coefficient: float = OFFLINE_DEFAULT_AXIAL_COEFFICIENT
    coefficient_source: str = "offline_rigidbody_catalog"
    rigidbody_projection_enabled: bool = False
    runtime_input_sources: tuple[str, ...] = RUNTIME_INPUT_SOURCES


def resolve_offline_ballistics_model(
    bomb_params: dict[str, Any] | None,
) -> OfflineBallisticsModel:
    """Resolve a static, offline-only model from selected weapon metadata."""

    params = bomb_params if isinstance(bomb_params, dict) else {}
    prediction_kind = str(params.get("prediction_kind") or "").strip().lower()
    if prediction_kind == "freefall":
        properties = OfflineRigidbodySolverProperties.from_static(params)
        if properties is None:
            return OfflineBallisticsModel(
                model_id=OFFLINE_RIGIDBODY_UNAVAILABLE_MODEL_ID,
                category="freefall",
                quality="unavailable",
                supported=False,
                unavailable_reason="offline_rigidbody_properties_unavailable",
            )
        return OfflineBallisticsModel(
            model_id=OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID,
            category="freefall",
            quality="offline_rigidbody_8111_projection",
            supported=True,
            axial_coefficient=properties.axial_coefficient,
            effective_axial_coefficient=properties.axial_coefficient,
            coefficient_source="offline_rigidbody_catalog",
            rigidbody_projection_enabled=True,
        )

    reason = (
        "offline_high_drag_unavailable"
        if prediction_kind == "high_drag"
        else prediction_kind or "unsupported"
    )
    return OfflineBallisticsModel(
        model_id=OFFLINE_RIGIDBODY_UNAVAILABLE_MODEL_ID,
        category=prediction_kind or "unsupported",
        quality="unavailable",
        supported=False,
        unavailable_reason=reason,
    )


__all__ = [
    "OFFLINE_DEFAULT_AXIAL_COEFFICIENT",
    "OFFLINE_GRAVITY_MS2",
    "OFFLINE_STEP_SECONDS",
    "OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID",
    "OFFLINE_RIGIDBODY_UNAVAILABLE_MODEL_ID",
    "OfflineBallisticsModel",
    "RUNTIME_INPUT_SOURCES",
    "resolve_offline_ballistics_model",
]
