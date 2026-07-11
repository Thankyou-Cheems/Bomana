"""Lock-aware scheduling helpers for weapon fire-control estimates."""

from __future__ import annotations

import math
from typing import Any

from bomana.config.settings import WeaponBallisticModelConfig, ZoneConfig
from bomana.core.state import GameState, Phase, TelemetryData, WeaponTarget
from bomana.core.weapon_catalog import WeaponCatalog, get_weapon_catalog
from bomana.core.weapon_solver import (
    ALIGN_TOLERANCE_DEG,
    QUALITY_NONE,
    STATUS_CCRP,
    STATUS_INCOMPATIBLE,
    STATUS_INSUFFICIENT_DATA,
    STATUS_NO_TARGET,
    STATUS_SOLVER_ERROR,
    STATUS_UNKNOWN_WEAPON,
    WeaponSolution,
    WeaponSolver,
    uses_existing_ccrp,
)

CALCULATION_INTERVAL_S = 0.2
_NUMERIC_PARSE_ERRORS = (TypeError, ValueError)


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except _NUMERIC_PARSE_ERRORS:
        return default
    return result if math.isfinite(result) else default


def _selection_token(catalog: WeaponCatalog) -> tuple[str, str]:
    snapshot = getattr(catalog, "selection_snapshot", None)
    if callable(snapshot):
        weapon_id, source, _weapon = snapshot()
        return weapon_id, source
    return catalog.selected_weapon_id, catalog.selection_source


def _selection_snapshot(
    catalog: WeaponCatalog,
) -> tuple[str, str, dict[str, Any] | None]:
    snapshot = getattr(catalog, "selection_snapshot", None)
    if callable(snapshot):
        return snapshot()
    selected_id, source = _selection_token(catalog)
    return selected_id, source, catalog.get(selected_id)


def _target_token(target: WeaponTarget | None) -> tuple[Any, ...] | None:
    if target is None:
        return None
    return (
        target.id,
        target.kind,
        target.name,
        target.distance_m,
        target.relative_deg,
        target.altitude_m,
        target.aspect_cosine,
    )


def _precomputed(status: str, reason: str, target: WeaponTarget | None) -> WeaponSolution:
    return WeaponSolution(
        status=status,
        quality=QUALITY_NONE,
        model=WeaponBallisticModelConfig.selected_model,
        reason=reason,
        target_kind=target.kind if target else "",
        target_name=target.name if target else "",
        target_distance_m=max(0.0, target.distance_m) if target else 0.0,
    )


def prepare_weapon_calculation(
    state: GameState,
    tel: TelemetryData,
    now: float,
    *,
    player_present: bool,
    target: WeaponTarget | None = None,
    catalog: WeaponCatalog | None = None,
    selection_snapshot: tuple[str, str, dict[str, Any] | None] | None = None,
    ccrp_supported: bool = True,
) -> dict[str, Any] | None:
    """Copy calculation inputs while the caller holds the game-state lock."""

    catalog = catalog or get_weapon_catalog()
    previous_target = state.weapon_target
    state.weapon_target = target
    current_air_target = bool(target is not None and target.kind == "aircraft")
    previous_air_target = bool(previous_target is not None and previous_target.kind == "aircraft")
    target_presence_changed = (previous_target is None) != (target is None)
    if (
        not current_air_target
        and not previous_air_target
        and not target_presence_changed
        and state.last_weapon_calc_time > 0.0
        and (now - state.last_weapon_calc_time) < CALCULATION_INTERVAL_S
    ):
        return None
    state.last_weapon_calc_time = now

    selected_id, source, weapon = selection_snapshot or _selection_snapshot(catalog)
    compatible = bool(weapon and tel.type_name and catalog.compatible(selected_id, tel.type_name))
    precomputed: WeaponSolution | None = None

    if weapon is None:
        precomputed = _precomputed(STATUS_UNKNOWN_WEAPON, "weapon_not_in_catalog", target)
    elif not tel.type_name or not tel.ind_ok:
        precomputed = _precomputed(
            STATUS_INSUFFICIENT_DATA,
            "aircraft_identity_unavailable",
            target,
        )
    elif not compatible:
        precomputed = _precomputed(
            STATUS_INCOMPATIBLE,
            "weapon_not_compatible_with_aircraft",
            target,
        )
    elif uses_existing_ccrp(weapon) and not ccrp_supported:
        precomputed = _precomputed(
            STATUS_INSUFFICIENT_DATA,
            "ccrp_physics_unavailable",
            target,
        )
    elif uses_existing_ccrp(weapon):
        precomputed = _precomputed(STATUS_CCRP, "existing_ccrp", target)
    elif (
        state.phase != Phase.ALIVE
        or not player_present
        or not tel.state_resp_ok
        or tel.is_on_ground
    ):
        precomputed = _precomputed(
            STATUS_INSUFFICIENT_DATA,
            "airborne_telemetry_unavailable",
            target,
        )
    elif target is None:
        precomputed = _precomputed(STATUS_NO_TARGET, "target_unavailable", None)

    tas_mps = _finite_float(tel.tas_kmh) / 3.6
    ground_speed_mps = _finite_float(state.zone_nav.ground_speed) * ZoneConfig.DISTANCE_SCALE * 1000
    ias_mps = _finite_float(tel.ias_kmh) / 3.6
    launch_speed_mps = next(
        (speed for speed in (tas_mps, ground_speed_mps, ias_mps) if speed >= 10.0),
        0.0,
    )
    ground_closing_speed_mps: float | None = None
    if (
        target is not None
        and target.kind in {"zone", "poi", "ground"}
        and ground_speed_mps > 0.0
        and abs(target.relative_deg) <= ALIGN_TOLERANCE_DEG
    ):
        closing_speed = ground_speed_mps * math.cos(math.radians(target.relative_deg))
        if closing_speed > 0.0:
            ground_closing_speed_mps = closing_speed

    return {
        "selection_token": (selected_id, source),
        "model_token": WeaponBallisticModelConfig.selected_model,
        "target_token": _target_token(target),
        "weapon": weapon,
        "compatible": compatible,
        "launch_altitude_m": _finite_float(tel.altitude_m, default=-1.0),
        "launch_speed_mps": launch_speed_mps,
        "launch_mach": (_finite_float(tel.mach, default=-1.0) if tel.mach is not None else None),
        "ground_closing_speed_mps": ground_closing_speed_mps,
        "target": target,
        "precomputed": precomputed,
    }


def compute_weapon_calculation(
    work: dict[str, Any],
    *,
    solver: WeaponSolver | None = None,
) -> dict[str, Any]:
    """Run the numerical estimate outside the game-state lock."""

    solution = work.get("precomputed")
    target = work.get("target")
    if not isinstance(solution, WeaponSolution):
        solver = solver or WeaponSolver()
        try:
            solution = solver.solve(
                work.get("weapon"),
                launch_altitude_m=work.get("launch_altitude_m", -1.0),
                launch_speed_mps=work.get("launch_speed_mps", 0.0),
                launch_mach=work.get("launch_mach"),
                ground_closing_speed_mps=work.get("ground_closing_speed_mps"),
                target_distance_m=(target.distance_m if isinstance(target, WeaponTarget) else None),
                target_relative_deg=(
                    target.relative_deg if isinstance(target, WeaponTarget) else 0.0
                ),
                target_kind=target.kind if isinstance(target, WeaponTarget) else "",
                target_name=target.name if isinstance(target, WeaponTarget) else "",
                target_altitude_m=(target.altitude_m if isinstance(target, WeaponTarget) else None),
                target_aspect_cosine=(
                    target.aspect_cosine if isinstance(target, WeaponTarget) else None
                ),
            )
        except Exception:
            solution = _precomputed(STATUS_SOLVER_ERROR, "solver_exception", target)

    return {
        "selection_token": work.get("selection_token"),
        "model_token": work.get("model_token"),
        "target_token": work.get("target_token"),
        "weapon": work.get("weapon"),
        "compatible": bool(work.get("compatible")),
        "solution": solution,
    }


def apply_weapon_calculation(
    state: GameState,
    result: dict[str, Any] | None,
    *,
    catalog: WeaponCatalog | None = None,
) -> bool:
    """Apply current work under lock; reject stale selection, model, or target."""

    catalog = catalog or get_weapon_catalog()
    if result is None:
        state.weapon_solution_valid = False
        state.weapon_status = STATUS_SOLVER_ERROR
        state.weapon_quality = QUALITY_NONE
        state.weapon_model = WeaponBallisticModelConfig.selected_model
        state.weapon_reason = "calculation_missing"
        return True
    if result.get("selection_token") != _selection_token(catalog):
        return False
    if result.get("model_token") != WeaponBallisticModelConfig.selected_model:
        return False
    if result.get("target_token") != _target_token(state.weapon_target):
        return False

    selected_id, source = result["selection_token"]
    weapon = result.get("weapon")
    solution = result.get("solution")
    if not isinstance(solution, WeaponSolution):
        solution = _precomputed(STATUS_SOLVER_ERROR, "invalid_solver_result", state.weapon_target)
    if solution.model != result.get("model_token"):
        return False
    weapon = weapon if isinstance(weapon, dict) else {}

    state.weapon_id = str(selected_id or "")
    state.weapon_display_name = str(
        weapon.get("display_name_zh") or weapon.get("display_name") or selected_id or ""
    )
    state.weapon_role = str(weapon.get("role") or "")
    state.weapon_control = str(weapon.get("control") or "")
    state.weapon_planform = str(weapon.get("planform") or "")
    state.weapon_model = solution.model
    state.weapon_selection_source = str(source or "unknown")
    state.weapon_selection_compatible = bool(result.get("compatible"))
    state.weapon_solution_valid = solution.valid
    state.weapon_status = solution.status
    state.weapon_quality = solution.quality
    state.weapon_reason = solution.reason
    state.weapon_target_kind = solution.target_kind
    state.weapon_target_name = solution.target_name
    state.weapon_target_distance_m = solution.target_distance_m
    state.weapon_min_range_m = solution.min_range_m
    state.weapon_max_range_m = solution.max_range_m
    state.weapon_rear_range_m = solution.rear_range_m
    state.weapon_head_range_m = solution.head_range_m
    state.weapon_target_aspect_cosine = solution.target_aspect_cosine
    state.weapon_time_to_target_s = solution.time_to_target_s
    state.weapon_time_to_window_s = solution.time_to_window_s
    return True


# Short aliases make the prepare/compute/apply contract explicit for callers.
prepare = prepare_weapon_calculation
compute = compute_weapon_calculation
apply = apply_weapon_calculation


__all__ = [
    "CALCULATION_INTERVAL_S",
    "apply",
    "apply_weapon_calculation",
    "compute",
    "compute_weapon_calculation",
    "prepare",
    "prepare_weapon_calculation",
]
