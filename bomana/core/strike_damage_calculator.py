"""Truthful EC target durability and weapon-count calculations.

Ordinary HE bombs convert TNT equivalent through the desktop gameparams
HP-to-tons coefficient. Napalm and missing transfer functions stay unlabeled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from bomana.core.strike_encyclopedia import (
    AirportDurabilityTier,
    StrikeEncyclopedia,
    WeaponReference,
)

TargetKind = Literal["bombing_point", "airport_module"]
MissionMode = Literal["planes", "heli"]
AirportModule = Literal["airfield", "storage", "parking", "dwelling"]

_ECONOMIC_RANK_MAX = 41


class StrikeDamageCalculatorError(ValueError):
    """Raised when a calculator request cannot describe a supported EC target."""


@dataclass(frozen=True)
class StrikeDamageResult:
    room_max_br: float
    balance_level: int
    balance_level_range: tuple[int, int]
    target_kind: TargetKind
    airport_module: AirportModule | None
    mission_mode: MissionMode | None
    target_mission_hp: float
    target_evidence_kind: str
    fire_remaining_hp_reference: float | None
    direct_damage_to_fire_reference: float | None
    fire_speed_parameter: float | None
    fire_depletion_seconds_reference: float | None
    fire_tail_evidence_kind: str | None
    respawn_seconds: float | None
    repair_base_hp: float | None
    repair_per_visit: float | None
    repair_evidence_kind: str | None
    weapon: WeaponReference
    damage_per_hit_mission_hp: float | None
    weapon_count: int | None
    fire_trigger_weapon_count: int | None
    quantity_evidence_kind: str
    quantity_is_exact: bool
    quantity_message: str


def room_max_br_from_balance_level(balance_level: int) -> float:
    """Apply the current GUI's rank/3+1 display formula."""

    if isinstance(balance_level, bool) or not 0 <= balance_level <= _ECONOMIC_RANK_MAX:
        raise StrikeDamageCalculatorError("invalid_balance_level")
    return round(balance_level / 3.0 + 1.0, 1)


def valid_room_max_brs() -> tuple[float, ...]:
    """Return the current display BR values backed by ranks 0 through 41."""

    return tuple(room_max_br_from_balance_level(rank) for rank in range(_ECONOMIC_RANK_MAX + 1))


def balance_level_from_room_max_br(room_max_br: float) -> int:
    """Resolve a room's displayed maximum BR to its exact descriptor maxRank."""

    if isinstance(room_max_br, bool) or not isinstance(room_max_br, (int, float)):
        raise StrikeDamageCalculatorError("invalid_room_max_br")
    value = float(room_max_br)
    for rank, display_br in enumerate(valid_room_max_brs()):
        if abs(value - display_br) < 1e-6:
            return rank
    raise StrikeDamageCalculatorError("invalid_room_max_br")


_KG_PER_TON = 1000.0


def mission_hp_from_tnte_kg(tnte_kg: float, hp_to_tnt_equivalent_tons: float) -> float:
    """Convert TNT-equivalent kilograms to mission HP using the gameparams coefficient."""

    if isinstance(tnte_kg, bool) or not isinstance(tnte_kg, (int, float)):
        raise StrikeDamageCalculatorError("invalid_tnte_kg")
    if isinstance(hp_to_tnt_equivalent_tons, bool) or not isinstance(
        hp_to_tnt_equivalent_tons, (int, float)
    ):
        raise StrikeDamageCalculatorError("invalid_tnt_conversion")
    mass = float(tnte_kg)
    tons_per_hp = float(hp_to_tnt_equivalent_tons)
    kg_per_hp = tons_per_hp * _KG_PER_TON
    if mass < 0.0 or kg_per_hp <= 0.0:
        raise StrikeDamageCalculatorError("invalid_tnt_conversion")
    return mass / kg_per_hp


def required_weapon_count(target_mission_hp: float, damage_per_hit_mission_hp: float) -> int:
    """Return the smallest integer of full hits that covers the requested HP."""

    if (
        isinstance(target_mission_hp, bool)
        or isinstance(damage_per_hit_mission_hp, bool)
        or not isinstance(target_mission_hp, (int, float))
        or not isinstance(damage_per_hit_mission_hp, (int, float))
    ):
        raise StrikeDamageCalculatorError("invalid_weapon_count_inputs")
    hp = float(target_mission_hp)
    damage = float(damage_per_hit_mission_hp)
    if hp <= 0.0 or damage <= 0.0:
        raise StrikeDamageCalculatorError("invalid_weapon_count_inputs")
    return max(1, math.ceil(hp / damage - 1e-9))


def airport_repair_per_visit(
    tier: AirportDurabilityTier,
    *,
    dwelling_remaining_hp: float,
) -> float:
    """Evaluate the static living-quarters repair script for one airport visit."""

    maximum = tier.auxiliary_module_mission_hp
    remaining = float(dwelling_remaining_hp)
    if not 0.0 <= remaining <= maximum:
        raise StrikeDamageCalculatorError("invalid_dwelling_remaining_hp")
    if remaining == 0.0 or remaining == maximum:
        return 0.0
    percent = (remaining + 1.0) * 100.0 / maximum
    slowdown = min(100.0 / percent, 10.0)
    return tier.repair_base_hp / slowdown


class StrikeDamageCalculator:
    """Map one room/target/weapon request to evidence-labelled EC outputs."""

    def __init__(self, encyclopedia: StrikeEncyclopedia):
        self._encyclopedia = encyclopedia
        self._weapons = {weapon.weapon_id: weapon for weapon in encyclopedia.weapon_references}

    @staticmethod
    def _tier_for_balance_level(tiers: tuple, balance_level: int):
        for tier in tiers:
            start, end = tier.balance_level_range
            if start <= balance_level <= end:
                return tier
        raise StrikeDamageCalculatorError("missing_balance_level_tier")

    def calculate(
        self,
        *,
        room_max_br: float,
        target_kind: TargetKind,
        weapon_id: str,
        mission_mode: MissionMode = "planes",
        airport_module: AirportModule | None = None,
        dwelling_remaining_hp: float | None = None,
    ) -> StrikeDamageResult:
        balance_level = balance_level_from_room_max_br(room_max_br)
        weapon = self._weapons.get(weapon_id)
        if weapon is None:
            raise StrikeDamageCalculatorError("unknown_weapon")

        if target_kind == "bombing_point":
            return self._bombing_point_result(
                room_max_br=float(room_max_br),
                balance_level=balance_level,
                mission_mode=mission_mode,
                weapon=weapon,
            )
        if target_kind == "airport_module":
            if airport_module not in {"airfield", "storage", "parking", "dwelling"}:
                raise StrikeDamageCalculatorError("invalid_airport_module")
            return self._airport_result(
                room_max_br=float(room_max_br),
                balance_level=balance_level,
                module=airport_module,
                weapon=weapon,
                dwelling_remaining_hp=dwelling_remaining_hp,
            )
        raise StrikeDamageCalculatorError("invalid_target_kind")

    def _bombing_point_result(
        self,
        *,
        room_max_br: float,
        balance_level: int,
        mission_mode: MissionMode,
        weapon: WeaponReference,
    ) -> StrikeDamageResult:
        if mission_mode not in {"planes", "heli"}:
            raise StrikeDamageCalculatorError("invalid_mission_mode")
        tier = self._tier_for_balance_level(self._encyclopedia.bombing_point_tiers, balance_level)
        target_hp = tier.planes_mission_hp if mission_mode == "planes" else tier.heli_mission_hp
        behavior = self._encyclopedia.bombing_point_behavior
        quantity = self._quantity_for_weapon(weapon)
        fire_hp = target_hp * (1.0 - behavior.hp_fire_mult)
        fire_count = None if quantity is None else required_weapon_count(fire_hp, quantity[0])
        destroy_count = None if quantity is None else required_weapon_count(target_hp, quantity[0])
        return StrikeDamageResult(
            room_max_br=room_max_br,
            balance_level=balance_level,
            balance_level_range=tier.balance_level_range,
            target_kind="bombing_point",
            airport_module=None,
            mission_mode=mission_mode,
            target_mission_hp=target_hp,
            target_evidence_kind="exact_static_hp",
            fire_remaining_hp_reference=target_hp * behavior.hp_fire_mult,
            direct_damage_to_fire_reference=fire_hp,
            fire_speed_parameter=behavior.fire_speed,
            fire_depletion_seconds_reference=behavior.depletion_seconds_reference,
            fire_tail_evidence_kind=behavior.fire_tail_evidence_kind,
            respawn_seconds=behavior.respawn_seconds,
            repair_base_hp=None,
            repair_per_visit=None,
            repair_evidence_kind=None,
            weapon=weapon,
            damage_per_hit_mission_hp=None if quantity is None else quantity[0],
            weapon_count=destroy_count,
            fire_trigger_weapon_count=fire_count,
            quantity_evidence_kind="native_unknown" if quantity is None else quantity[1],
            quantity_is_exact=quantity is not None,
            quantity_message=(
                "Mk 77 / napalm 不走 HP↔TNT 当量公式，无法给出精确枚数。"
                if quantity is None
                else "按桌面 gameparams 的 HP↔TNT 当量、满额命中计算；燃烧阈值为参数推断。"
            ),
        )

    def _quantity_for_weapon(self, weapon: WeaponReference) -> tuple[float, str] | None:
        if weapon.mission_damage_model != "tnt_equivalent":
            return None
        conversion = self._encyclopedia.bombing_zone_tnt_conversion
        tnte_kg = weapon.raw_explosive_mass_kg * weapon.strength_equivalent
        damage = mission_hp_from_tnte_kg(tnte_kg, conversion.hp_to_tnt_equivalent_tons)
        return damage, conversion.evidence_kind

    def _airport_result(
        self,
        *,
        room_max_br: float,
        balance_level: int,
        module: AirportModule,
        weapon: WeaponReference,
        dwelling_remaining_hp: float | None,
    ) -> StrikeDamageResult:
        tier = self._tier_for_balance_level(self._encyclopedia.airport_tiers, balance_level)
        target_hp = (
            tier.runway_mission_hp if module == "airfield" else tier.auxiliary_module_mission_hp
        )
        repair = (
            None
            if dwelling_remaining_hp is None
            else airport_repair_per_visit(
                tier,
                dwelling_remaining_hp=dwelling_remaining_hp,
            )
        )
        quantity = self._quantity_for_weapon(weapon)
        destroy_count = None if quantity is None else required_weapon_count(target_hp, quantity[0])
        return StrikeDamageResult(
            room_max_br=room_max_br,
            balance_level=balance_level,
            balance_level_range=tier.balance_level_range,
            target_kind="airport_module",
            airport_module=module,
            mission_mode=None,
            target_mission_hp=target_hp,
            target_evidence_kind="exact_static_hp",
            fire_remaining_hp_reference=None,
            direct_damage_to_fire_reference=None,
            fire_speed_parameter=None,
            fire_depletion_seconds_reference=None,
            fire_tail_evidence_kind=None,
            respawn_seconds=None,
            repair_base_hp=tier.repair_base_hp,
            repair_per_visit=repair,
            repair_evidence_kind=self._encyclopedia.airport_behavior.repair_evidence_kind,
            weapon=weapon,
            damage_per_hit_mission_hp=None if quantity is None else quantity[0],
            weapon_count=destroy_count,
            fire_trigger_weapon_count=None,
            quantity_evidence_kind="native_unknown" if quantity is None else quantity[1],
            quantity_is_exact=quantity is not None,
            quantity_message=(
                "Mk 77 / napalm 不走 HP↔TNT 当量公式，无法给出精确枚数。"
                if quantity is None
                else (
                    "按桌面 gameparams 的 HP↔TNT 当量、满额命中计算；"
                    "机场模块没有 90% 燃烧尾段，连续投弹时生活区仍可能回血。"
                )
            ),
        )


__all__ = [
    "AirportModule",
    "MissionMode",
    "StrikeDamageCalculator",
    "StrikeDamageCalculatorError",
    "StrikeDamageResult",
    "TargetKind",
    "airport_repair_per_visit",
    "balance_level_from_room_max_br",
    "mission_hp_from_tnte_kg",
    "required_weapon_count",
    "room_max_br_from_balance_level",
    "valid_room_max_brs",
]
