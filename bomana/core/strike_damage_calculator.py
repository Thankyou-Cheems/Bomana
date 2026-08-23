"""Truthful EC target durability and weapon-count calculations.

Hangar estimated base damage is evaluated from bundled splash-curve
parameters and per-weapon BLK inputs. The gameparams HP↔TNT coefficient
is retained only as a labelled non-hangar reference.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from bomana.core.hangar_base_damage import (
    evaluate_hangar_base_damage,
    hangar_reward_ui_value,
)
from bomana.core.strike_encyclopedia import (
    AirportDurabilityTier,
    StrikeEncyclopedia,
    WeaponReference,
)

TargetKind = Literal["bombing_point", "airport_module"]
MissionMode = Literal["planes", "heli"]
AirportModule = Literal["airfield", "storage", "parking", "dwelling"]

_ECONOMIC_RANK_MAX = 41
_EVIDENCE_BY_MODEL = {
    "splash_tnte_curve": "exact_static_splash_curve",
    "napalm_splash_fire": "exact_static_napalm_splash_fire",
    "nuclear_yield": "exact_static_nuclear_yield",
}


class StrikeDamageCalculatorError(ValueError):
    """Raised when a calculator request cannot describe a supported EC target."""


@dataclass(frozen=True)
class _WeaponQuantity:
    damage: float
    evidence_kind: str
    reduced_for_armor: bool
    tnte_kg: float


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
    hangar_reward_ui_for_destroy: float | None
    reduced_for_armor: bool | None


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
        fire_count = None if quantity is None else required_weapon_count(fire_hp, quantity.damage)
        destroy_count = (
            None if quantity is None else required_weapon_count(target_hp, quantity.damage)
        )
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
            damage_per_hit_mission_hp=None if quantity is None else quantity.damage,
            weapon_count=destroy_count,
            fire_trigger_weapon_count=fire_count,
            quantity_evidence_kind="native_unknown" if quantity is None else quantity.evidence_kind,
            quantity_is_exact=quantity is not None,
            quantity_message=_quantity_message(weapon, quantity, airport=False),
            hangar_reward_ui_for_destroy=_reward_for_destroy(
                self._encyclopedia, quantity, destroy_count
            ),
            reduced_for_armor=None if quantity is None else quantity.reduced_for_armor,
        )

    def _quantity_for_weapon(self, weapon: WeaponReference) -> _WeaponQuantity | None:
        breakdown = evaluate_hangar_base_damage(
            self._encyclopedia.bombing_zone_splash,
            weapon.hangar_inputs(),
        )
        if breakdown is None or breakdown.damage <= 0.0:
            return None
        return _WeaponQuantity(
            damage=breakdown.damage,
            evidence_kind=_EVIDENCE_BY_MODEL[breakdown.model],
            reduced_for_armor=breakdown.reduced_for_armor,
            tnte_kg=breakdown.tnte_kg,
        )

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
        destroy_count = (
            None if quantity is None else required_weapon_count(target_hp, quantity.damage)
        )
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
            damage_per_hit_mission_hp=None if quantity is None else quantity.damage,
            weapon_count=destroy_count,
            fire_trigger_weapon_count=None,
            quantity_evidence_kind="native_unknown" if quantity is None else quantity.evidence_kind,
            quantity_is_exact=quantity is not None,
            quantity_message=_quantity_message(weapon, quantity, airport=True),
            hangar_reward_ui_for_destroy=_reward_for_destroy(
                self._encyclopedia, quantity, destroy_count
            ),
            reduced_for_armor=None if quantity is None else quantity.reduced_for_armor,
        )


def _reward_for_destroy(
    encyclopedia: StrikeEncyclopedia,
    quantity: _WeaponQuantity | None,
    destroy_count: int | None,
) -> float | None:
    if quantity is None or destroy_count is None:
        return None
    return hangar_reward_ui_value(
        encyclopedia.bombing_zone_splash,
        quantity.damage * destroy_count,
    )


def _quantity_message(
    weapon: WeaponReference,
    quantity: _WeaponQuantity | None,
    *,
    airport: bool,
) -> str:
    if quantity is None:
        return (
            "该武器缺少溅射公式所需的装药、燃烧弹 splash/fire 或核弹 yield 输入，无法给出精确枚数。"
        )
    if weapon.mission_damage_model == "napalm_splash_fire":
        core = (
            "燃烧弹按 splash.damage 对 25 mm 战区装甲的欠穿抑制，再加上 "
            "fireDamage×lifeTime×napalmDamageMult。"
        )
    elif weapon.mission_damage_model == "nuclear_yield":
        core = "核弹按 explosive.blkx 的 yieldToExplosionParameters 查表。"
    elif quantity.reduced_for_armor:
        core = "按 TNT 当量查溅射曲线后，因穿深不足 25 mm 乘以 restrainExplosionDamage=0.6。"
    else:
        core = "按 explosiveMass×strengthEquivalent 在 explosive.blkx 溅射曲线上线性插值。"
    if airport:
        return core + "大厅该数字标的是对战区；机场模块套用同一 splash HP，并计入生活区回血。"
    return core + "满额命中；燃烧阈值为参数推断。"


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
