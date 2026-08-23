#!/usr/bin/env python3
"""Export the public EC quantity-calculator catalog for bomana.ruikang.wang."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bomana.core.hangar_base_damage import evaluate_hangar_base_damage  # noqa: E402
from bomana.core.strike_damage_calculator import valid_room_max_brs  # noqa: E402
from bomana.core.strike_encyclopedia import load_strike_encyclopedia  # noqa: E402
from bomana.metadata import __version__  # noqa: E402

DEFAULT_OUTPUT = ROOT / "docs" / "ec-calculator.json"
_SCHEMA = "bomana_web_ec_calculator/v1"
_TARGETS = (
    {
        "id": "bombing_point_planes",
        "label": "战区基地（空战）",
        "kind": "bombing_point",
        "mode": "planes",
        "has_fire": True,
    },
    {
        "id": "bombing_point_heli",
        "label": "战区基地（直升机）",
        "kind": "bombing_point",
        "mode": "heli",
        "has_fire": True,
    },
    {
        "id": "airport_airfield",
        "label": "机场跑道",
        "kind": "airport_module",
        "module": "airfield",
        "has_fire": False,
    },
    {
        "id": "airport_storage",
        "label": "机场油库 / 储存区",
        "kind": "airport_module",
        "module": "storage",
        "has_fire": False,
    },
    {
        "id": "airport_parking",
        "label": "机场停机 / 维修区",
        "kind": "airport_module",
        "module": "parking",
        "has_fire": False,
    },
    {
        "id": "airport_dwelling",
        "label": "机场生活区",
        "kind": "airport_module",
        "module": "dwelling",
        "has_fire": False,
    },
)


def _weapon_row(encyclopedia: Any, weapon: Any) -> dict[str, Any]:
    breakdown = evaluate_hangar_base_damage(
        encyclopedia.bombing_zone_splash,
        weapon.hangar_inputs(),
    )
    return {
        "id": weapon.weapon_id,
        "kind": weapon.kind,
        "name": weapon.display_name,
        "name_zh": weapon.display_name_zh,
        "mass_kg": weapon.mass_kg,
        "explosive_type": weapon.explosive_type,
        "explosive_mass_kg": weapon.raw_explosive_mass_kg,
        "strength_equivalent": weapon.strength_equivalent,
        "model": weapon.mission_damage_model,
        "hangar_damage": None if breakdown is None else breakdown.damage,
        "reduced_for_armor": None if breakdown is None else breakdown.reduced_for_armor,
    }


def build_web_catalog() -> dict[str, Any]:
    encyclopedia = load_strike_encyclopedia()
    splash = encyclopedia.bombing_zone_splash
    return {
        "schema": _SCHEMA,
        "app_version": __version__,
        "hp_fire_mult": encyclopedia.bombing_point_behavior.hp_fire_mult,
        "reward": {
            "preset_dmg_min": splash.reward_preset_dmg_min,
            "preset_dmg_max": splash.reward_preset_dmg_max,
            "bombing_reward_modifier": splash.bombing_reward_modifier,
            "fighter_bombing_reward_mul": splash.fighter_bombing_reward_mul,
            "ui_decoration": splash.reward_ui_decoration,
            "piecewise_linear": [list(point) for point in splash.reward_piecewise_linear],
        },
        "disclaimer": encyclopedia.disclaimer,
        "br_values": [f"{value:.1f}" for value in valid_room_max_brs()],
        "targets": list(_TARGETS),
        "bombing_point_tiers": [
            {
                "balance_level": list(tier.balance_level_range),
                "planes_mission_hp": tier.planes_mission_hp,
                "heli_mission_hp": tier.heli_mission_hp,
            }
            for tier in encyclopedia.bombing_point_tiers
        ],
        "airport_tiers": [
            {
                "balance_level": list(tier.balance_level_range),
                "auxiliary_module_mission_hp": tier.auxiliary_module_mission_hp,
                "runway_mission_hp": tier.runway_mission_hp,
            }
            for tier in encyclopedia.airport_tiers
        ],
        "weapons": [_weapon_row(encyclopedia, weapon) for weapon in encyclopedia.weapon_references],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_web_catalog()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("wrote", args.output, "weapons=", len(payload["weapons"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
