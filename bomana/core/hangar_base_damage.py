"""Hangar estimated-base-damage formula from static splash parameters.

The hangar UI sums per-weapon ``weaponDamage``. Those values are not a
hand table: they come from ``explosive.blkx`` splash curves, the
``bombing_zone`` armor class, explicit napalm splash/fire blocks, and
nuclear yield rows. Weapon BLK fields are the only per-bomb inputs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_SCHEMA = "bomana_bombing_zone_splash/v1"


class HangarBaseDamageError(ValueError):
    """Raised when splash-model inputs cannot evaluate hangar base damage."""


@dataclass(frozen=True)
class BombingZoneSplashModel:
    schema: str
    armor_thickness_mm: float
    restrain_explosion_damage: float
    napalm_damage_mult: float
    explosive_mass_to_damage: tuple[tuple[float, float], ...]
    explosive_mass_to_penetration: tuple[tuple[float, float], ...]
    nuclear_yield_to_damage: tuple[tuple[float, float], ...]
    reward_preset_dmg_min: float
    reward_preset_dmg_max: float
    bombing_reward_modifier: float
    fighter_bombing_reward_mul: float
    prem_bombing_reward_mul: float
    reward_ui_decoration: float
    reward_piecewise_linear: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class HangarDamageInputs:
    explosive_mass_kg: float
    strength_equivalent: float
    splash_damage: float | None = None
    splash_penetration: float | None = None
    splash_damage_type: str = ""
    fire_damage: float | None = None
    fire_life_time: float | None = None
    nuclear_yield_kt: float | None = None
    mission_damage_model: str = "splash_tnte_curve"


@dataclass(frozen=True)
class HangarDamageBreakdown:
    damage: float
    model: str
    tnte_kg: float
    penetration_mm: float | None
    reduced_for_armor: bool


def interpolate_piecewise(points: Sequence[tuple[float, float]], value: float) -> float:
    """Linear interpolation on a sorted piecewise table, clamped at the ends."""

    if len(points) < 2:
        raise HangarBaseDamageError("invalid_piecewise_table")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise HangarBaseDamageError("invalid_interpolation_value")
    x = float(value)
    if x <= points[0][0]:
        return float(points[0][1])
    if x >= points[-1][0]:
        return float(points[-1][1])
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        if x0 <= x <= x1:
            if x1 == x0:
                return float(y1)
            return float(y0) + (x - x0) * (float(y1) - float(y0)) / (x1 - x0)
    return float(points[-1][1])


def _curve(raw: object, label: str) -> tuple[tuple[float, float], ...]:
    if not isinstance(raw, list) or len(raw) < 2:
        raise HangarBaseDamageError(f"invalid_{label}")
    points: list[tuple[float, float]] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise HangarBaseDamageError(f"invalid_{label}")
        x, y = item
        if isinstance(x, bool) or isinstance(y, bool):
            raise HangarBaseDamageError(f"invalid_{label}")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            raise HangarBaseDamageError(f"invalid_{label}")
        if not math.isfinite(float(x)) or not math.isfinite(float(y)):
            raise HangarBaseDamageError(f"invalid_{label}")
        points.append((float(x), float(y)))
    points.sort(key=lambda pair: pair[0])
    return tuple(points)


def _number(raw: object, label: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
        raise HangarBaseDamageError(f"invalid_{label}")
    return float(raw)


def load_splash_model(payload: Mapping[str, Any]) -> BombingZoneSplashModel:
    """Parse the bundled bombing-zone splash parameter file."""

    if payload.get("schema") != _SCHEMA:
        raise HangarBaseDamageError("unsupported_splash_schema")
    armor = payload.get("armor")
    if not isinstance(armor, Mapping):
        raise HangarBaseDamageError("invalid_armor")
    reward = payload.get("reward")
    if not isinstance(reward, Mapping):
        raise HangarBaseDamageError("invalid_reward")
    return BombingZoneSplashModel(
        schema=_SCHEMA,
        armor_thickness_mm=_number(armor.get("armor_thickness_mm"), "armor_thickness_mm"),
        restrain_explosion_damage=_number(
            armor.get("restrain_explosion_damage"), "restrain_explosion_damage"
        ),
        napalm_damage_mult=_number(armor.get("napalm_damage_mult"), "napalm_damage_mult"),
        explosive_mass_to_damage=_curve(
            payload.get("explosive_mass_to_damage"), "explosive_mass_to_damage"
        ),
        explosive_mass_to_penetration=_curve(
            payload.get("explosive_mass_to_penetration"), "explosive_mass_to_penetration"
        ),
        nuclear_yield_to_damage=_curve(
            payload.get("nuclear_yield_to_damage"), "nuclear_yield_to_damage"
        ),
        reward_preset_dmg_min=_number(reward.get("preset_dmg_min"), "preset_dmg_min"),
        reward_preset_dmg_max=_number(reward.get("preset_dmg_max"), "preset_dmg_max"),
        bombing_reward_modifier=_number(
            reward.get("bombing_reward_modifier"), "bombing_reward_modifier"
        ),
        fighter_bombing_reward_mul=_number(
            reward.get("fighter_bombing_reward_mul"), "fighter_bombing_reward_mul"
        ),
        prem_bombing_reward_mul=_number(
            reward.get("prem_bombing_reward_mul"), "prem_bombing_reward_mul"
        ),
        reward_ui_decoration=_number(reward.get("ui_decoration"), "ui_decoration"),
        reward_piecewise_linear=_curve(reward.get("piecewise_linear"), "piecewise_linear"),
    )


def _apply_underpenetration(
    base: float, penetration_mm: float, model: BombingZoneSplashModel
) -> tuple[float, bool]:
    if penetration_mm >= model.armor_thickness_mm:
        return base, False
    scale = (penetration_mm / model.armor_thickness_mm) * model.restrain_explosion_damage
    return base * scale, True


def evaluate_hangar_base_damage(
    model: BombingZoneSplashModel,
    inputs: HangarDamageInputs,
) -> HangarDamageBreakdown | None:
    """Return hangar estimated bombing-zone damage for one warhead, or None."""

    kind = inputs.mission_damage_model
    if kind == "nuclear_yield":
        yield_kt = inputs.nuclear_yield_kt
        if yield_kt is None or yield_kt <= 0.0:
            return None
        for listed_yield, damage in model.nuclear_yield_to_damage:
            if math.isclose(listed_yield, float(yield_kt), rel_tol=0.0, abs_tol=1e-9):
                return HangarDamageBreakdown(
                    damage=damage,
                    model=kind,
                    tnte_kg=0.0,
                    penetration_mm=None,
                    reduced_for_armor=False,
                )
        return None

    if kind == "napalm_splash_fire":
        splash = inputs.splash_damage
        pen = inputs.splash_penetration
        fire = inputs.fire_damage
        life = inputs.fire_life_time
        if (
            splash is None
            or pen is None
            or fire is None
            or life is None
            or splash <= 0.0
            or pen < 0.0
            or fire < 0.0
            or life < 0.0
        ):
            return None
        instant, reduced = _apply_underpenetration(float(splash), float(pen), model)
        fire_bonus = float(fire) * float(life) * model.napalm_damage_mult
        return HangarDamageBreakdown(
            damage=instant + fire_bonus,
            model=kind,
            tnte_kg=max(0.0, inputs.explosive_mass_kg * inputs.strength_equivalent),
            penetration_mm=float(pen),
            reduced_for_armor=reduced,
        )

    if kind != "splash_tnte_curve":
        return None
    mass = inputs.explosive_mass_kg
    strength = inputs.strength_equivalent
    if mass <= 0.0 or strength <= 0.0:
        return None
    tnte = mass * strength
    base = interpolate_piecewise(model.explosive_mass_to_damage, tnte)
    penetration = interpolate_piecewise(model.explosive_mass_to_penetration, tnte)
    damage, reduced = _apply_underpenetration(base, penetration, model)
    return HangarDamageBreakdown(
        damage=damage,
        model=kind,
        tnte_kg=tnte,
        penetration_mm=penetration,
        reduced_for_armor=reduced,
    )


def hangar_reward_multiplier(
    model: BombingZoneSplashModel,
    weapon_damage: float,
    *,
    is_fighter: bool = False,
    is_premium: bool = False,
) -> float:
    """Hangar ``getPresetRewardMul`` before the UI ×10 decoration."""

    damage = float(weapon_damage)
    if damage <= 0.0:
        return 1.0
    if damage >= model.reward_piecewise_linear[0][0]:
        return interpolate_piecewise(model.reward_piecewise_linear, damage)
    span = model.reward_preset_dmg_max - model.reward_preset_dmg_min
    scale = (
        1.0 + (model.bombing_reward_modifier - 1.0) * (damage - model.reward_preset_dmg_min) / span
    )
    multiplier = scale * model.reward_preset_dmg_min / damage
    multiplier = min(multiplier, 1.0)
    if is_premium:
        multiplier *= model.prem_bombing_reward_mul
    if is_fighter:
        multiplier *= model.fighter_bombing_reward_mul
    return multiplier


def hangar_reward_ui_value(
    model: BombingZoneSplashModel,
    weapon_damage: float,
    *,
    is_fighter: bool = False,
    is_premium: bool = False,
) -> float:
    """Value shown as ``对战区收益系数``, one decimal in the hangar."""

    return (
        hangar_reward_multiplier(
            model,
            weapon_damage,
            is_fighter=is_fighter,
            is_premium=is_premium,
        )
        * model.reward_ui_decoration
    )


__all__ = [
    "BombingZoneSplashModel",
    "HangarBaseDamageError",
    "HangarDamageBreakdown",
    "HangarDamageInputs",
    "evaluate_hangar_base_damage",
    "hangar_reward_multiplier",
    "hangar_reward_ui_value",
    "interpolate_piecewise",
    "load_splash_model",
]
