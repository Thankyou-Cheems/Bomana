#!/usr/bin/env python3
"""Extract aircraft-mounted air-to-ground warheads for the EC quantity calculator.

The fire-control catalog skips unguided rockets because they are not CCRP
targets. This extractor keeps bombs, rockets, and AGMs, and records the
weapon-BLK inputs the hangar splash formula consumes. It does not copy
per-weapon hangar ``weaponDamage`` tables.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from datamine_utils import (
    WEAPON_LOCALIZATION_FILE,
    read_datamine_version,
    read_git_commit,
    read_git_commit_timestamp_utc,
    read_git_remote,
    require_clean_git_checkout,
)
from weapon_fire_control_extractor import (
    DataminePathIndex,
    _classify_role,
    _clean_text,
    _collect_aircraft_mounts,
    _display_names,
    _load_localization,
    _nominal_number,
    _resolve_mount,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "bomana/data/strike_weapon_damage.json"
DEFAULT_SPLASH_OUTPUT = ROOT / "bomana/data/bombing_zone_splash.json"
EXPLOSIVE_REL = Path("aces.vromfs.bin_u/gamedata/damage_model/explosive.blkx")
ARMOR_REL = Path("aces.vromfs.bin_u/gamedata/flightmodels/dm/armorclasses.blkx")
WARPOINTS_REL = Path("char.vromfs.bin_u/config/warpoints.blkx")
_SCHEMA = "bomana_strike_weapon_damage/v1"
_SPLASH_SCHEMA = "bomana_bombing_zone_splash/v1"
_NAPALM_STRENGTH_LIMIT = 0.01
_SMOKE_TYPES = {"smoke_composition"}
_WIKI_TNTE_KG = {
    "us_500lb_mk_82_ldgp": 117.6,
    "us_1000lb_mk_83_ldgp": 272.4,
    "su_fab_500m_62t": 340.8,
}


def _load_explosive_types(datamine_root: Path, commit: str) -> tuple[dict[str, float], str, bytes]:
    path = datamine_root / EXPLOSIVE_REL
    if path.is_file():
        raw = path.read_bytes()
    else:
        raw = subprocess.check_output(
            ["git", "-C", str(datamine_root), "show", f"{commit}:{EXPLOSIVE_REL.as_posix()}"]
        )
    payload = json.loads(raw.decode("utf-8"))
    types = payload.get("explosiveTypes")
    if not isinstance(types, dict) or not types:
        raise RuntimeError("explosive.blkx is missing explosiveTypes")
    strengths: dict[str, float] = {}
    for name, body in types.items():
        if not isinstance(name, str) or not isinstance(body, dict):
            continue
        value = body.get("strengthEquivalent")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        strengths[name] = float(value)
    if not strengths:
        raise RuntimeError("explosive.blkx has no strengthEquivalent entries")
    return strengths, EXPLOSIVE_REL.as_posix(), raw


def _kind_for(source_section: str, triggers: set[str], role: str) -> str | None:
    if role == "aam" or "aam" in triggers:
        return None
    if source_section == "bomb":
        return "bomb"
    if "atgm" in triggers:
        return "missile"
    if source_section == "rocket":
        return "rocket"
    return None


def _git_json(datamine_root: Path, commit: str, relative: Path) -> tuple[dict[str, Any], bytes]:
    path = datamine_root / relative
    if path.is_file():
        raw = path.read_bytes()
    else:
        raw = subprocess.check_output(
            ["git", "-C", str(datamine_root), "show", f"{commit}:{relative.as_posix()}"]
        )
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{relative.as_posix()} is not a JSON object")
    return payload, raw


def _piecewise_points(curve: object) -> list[list[float]]:
    if not isinstance(curve, dict):
        raise RuntimeError("piecewise curve must be an object")
    points: list[list[float]] = []
    for value in curve.values():
        if isinstance(value, list) and len(value) == 2:
            x, y = value
            if isinstance(x, bool) or isinstance(y, bool):
                continue
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                points.append([float(x), float(y)])
    if len(points) < 2:
        raise RuntimeError("piecewise curve is too short")
    points.sort(key=lambda pair: pair[0])
    return points


def extract_splash_model(datamine_root: Path, commit: str, version: str) -> dict[str, Any]:
    """Export the hangar splash/reward input parameters, not per-weapon damage."""

    explosive, explosive_bytes = _git_json(datamine_root, commit, EXPLOSIVE_REL)
    armor, _armor_bytes = _git_json(datamine_root, commit, ARMOR_REL)
    warpoints, _warpoints_bytes = _git_json(datamine_root, commit, WARPOINTS_REL)
    splash = explosive.get("explosiveTypeToSplashParams")
    if not isinstance(splash, dict):
        raise RuntimeError("explosive.blkx is missing explosiveTypeToSplashParams")
    bombing_zone = armor.get("bombing_zone")
    if not isinstance(bombing_zone, dict):
        raise RuntimeError("armorclasses.blkx is missing bombing_zone")
    yields: list[list[float]] = []
    yield_table = explosive.get("yieldToExplosionParameters")
    if isinstance(yield_table, dict):
        for body in yield_table.values():
            if not isinstance(body, dict):
                continue
            listed_yield = body.get("yield")
            damage = body.get("damage")
            if isinstance(listed_yield, bool) or isinstance(damage, bool):
                continue
            if isinstance(listed_yield, (int, float)) and isinstance(damage, (int, float)):
                yields.append([float(listed_yield), float(damage)])
    yields.sort(key=lambda pair: pair[0])
    muls = warpoints.get("BombingRewardMultipliers")
    if not isinstance(muls, dict):
        raise RuntimeError("warpoints.blkx is missing BombingRewardMultipliers")
    piecewise = muls.get("piecewiseLinearTable")
    piecewise_points: list[list[float]] = []
    if isinstance(piecewise, dict):
        raw_points = piecewise.get("v")
        if isinstance(raw_points, list):
            for item in raw_points:
                if isinstance(item, list) and len(item) == 2:
                    x, y = item
                    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                        piecewise_points.append([float(x), float(y)])
    return {
        "schema": _SPLASH_SCHEMA,
        "provenance": {
            "datamine_version": version,
            "datamine_commit": commit,
            "source_repo": read_git_remote(datamine_root) or "",
            "explosive_source": EXPLOSIVE_REL.as_posix(),
            "explosive_sha256": hashlib.sha256(explosive_bytes).hexdigest().upper(),
            "armor_source": ARMOR_REL.as_posix(),
            "warpoints_source": WARPOINTS_REL.as_posix(),
            "gui_source": "gui.vromfs.bin_u/globals/econweaponutils.nut",
        },
        "armor": {
            "class_name": "bombing_zone",
            "armor_thickness_mm": float(bombing_zone["armorThickness"]),
            "restrain_explosion_damage": float(bombing_zone["restrainExplosionDamage"]),
            "napalm_damage_mult": float(bombing_zone["napalmDamageMult"]),
        },
        "explosive_mass_to_damage": _piecewise_points(splash["explosiveMassToDamage"]),
        "explosive_mass_to_penetration": _piecewise_points(splash["explosiveMassToPenetration"]),
        "nuclear_yield_to_damage": yields,
        "reward": {
            "preset_dmg_min": float(muls["presetDmgMin"]),
            "preset_dmg_max": float(muls["presetDmgMax"]),
            "bombing_reward_modifier": float(muls["bombingRewardModifier"]),
            "fighter_bombing_reward_mul": float(muls["fighterBombingRewardMul"]),
            "prem_bombing_reward_mul": float(muls["premBombingRewardMul"]),
            "ui_decoration": 10.0,
            "piecewise_linear": piecewise_points,
        },
    }


def _optional_positive(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number <= 0.0:
        return None
    return number


def _damage_model(
    explosive_type: str,
    explosive_mass: float,
    strength: float | None,
    *,
    splash: dict[str, Any] | None,
    fire: dict[str, Any] | None,
    nuclear_yield_kt: float | None,
) -> str:
    if nuclear_yield_kt is not None:
        return "nuclear_yield"
    splash_type = _clean_text((splash or {}).get("damageType")).casefold()
    if (
        splash_type == "napalm"
        or explosive_type.casefold() == "napalm"
        or (strength is not None and strength <= _NAPALM_STRENGTH_LIMIT)
    ):
        if (
            splash
            and fire
            and _optional_positive(splash.get("damage")) is not None
            and splash.get("penetration") is not None
            and _optional_positive(fire.get("damage")) is not None
            and _optional_positive(fire.get("lifeTime")) is not None
        ):
            return "napalm_splash_fire"
        return "native_unknown"
    if explosive_type.casefold() in _SMOKE_TYPES:
        return "native_unknown"
    if not explosive_type or strength is None or explosive_mass <= 0.0:
        return "native_unknown"
    return "splash_tnte_curve"


def extract_catalog(datamine_root: Path, *, require_clean: bool = True) -> dict[str, Any]:
    datamine_root = datamine_root.resolve()
    if require_clean:
        require_clean_git_checkout(datamine_root)
    commit = read_git_commit(datamine_root)
    version = read_datamine_version(datamine_root)
    if len(commit) != 40 or not version:
        raise RuntimeError("datamine version and commit are required")

    strengths, explosive_source, explosive_bytes = _load_explosive_types(datamine_root, commit)
    path_index = DataminePathIndex(datamine_root)
    mounts, unresolved = _collect_aircraft_mounts(datamine_root, path_index)
    grouped: dict[Path, list] = defaultdict(list)
    for mount in mounts:
        if mount.trigger == "aam":
            continue
        terminal = _resolve_mount(
            mount,
            datamine_root=datamine_root,
            path_index=path_index,
            unresolved=unresolved,
        )
        if terminal is not None:
            grouped[terminal.source_path].append(terminal)

    localization = _load_localization(datamine_root / WEAPON_LOCALIZATION_FILE)
    weapons: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_path in sorted(grouped):
        terminals = grouped[source_path]
        first = terminals[0]
        section = first.source_data[first.source_section]
        if not isinstance(section, dict):
            continue
        triggers = {terminal.trigger for terminal in terminals}
        role = _classify_role(triggers, first.source_section, section)
        kind = _kind_for(first.source_section, triggers, role)
        if kind is None:
            continue
        weapon_id = source_path.stem
        if weapon_id in seen:
            raise RuntimeError(f"duplicate weapon id: {weapon_id}")
        seen.add(weapon_id)
        explosive_type = _clean_text(section.get("explosiveType"))
        explosive_mass = _nominal_number(section.get("explosiveMass"))
        mass = _nominal_number(section.get("mass"))
        strength = strengths.get(explosive_type)
        splash = section.get("splash") if isinstance(section.get("splash"), dict) else None
        fire = section.get("fireDamage") if isinstance(section.get("fireDamage"), dict) else None
        nuclear_yield_kt = _optional_positive(section.get("yield"))
        model = _damage_model(
            explosive_type,
            explosive_mass,
            strength,
            splash=splash,
            fire=fire,
            nuclear_yield_kt=nuclear_yield_kt,
        )
        display_name, display_name_zh = _display_names(source_path, section, localization)
        weapons.append(
            {
                "weapon_id": weapon_id,
                "kind": kind,
                "display_name": display_name,
                "display_name_zh": display_name_zh,
                "mass_kg": mass,
                "explosive_type": explosive_type,
                "raw_explosive_mass_kg": explosive_mass,
                "tnte_reference_kg": _WIKI_TNTE_KG.get(weapon_id),
                "strength_equivalent": 0.0 if strength is None else strength,
                "mission_damage_model": model,
                "splash_damage": None if splash is None else splash.get("damage"),
                "splash_penetration": None if splash is None else splash.get("penetration"),
                "splash_damage_type": ""
                if splash is None
                else _clean_text(splash.get("damageType")),
                "fire_damage": None if fire is None else fire.get("damage"),
                "fire_life_time": None if fire is None else fire.get("lifeTime"),
                "nuclear_yield_kt": nuclear_yield_kt,
            }
        )

    weapons.sort(key=lambda item: (item["kind"], item["display_name_zh"], item["weapon_id"]))
    counts = {"bomb": 0, "rocket": 0, "missile": 0}
    for item in weapons:
        counts[str(item["kind"])] += 1
    return {
        "schema": _SCHEMA,
        "provenance": {
            "datamine_version": version,
            "datamine_commit": commit,
            "source_repo": read_git_remote(datamine_root) or "",
            "generated_at_utc": read_git_commit_timestamp_utc(datamine_root)
            or "1970-01-01T00:00:00Z",
            "explosive_source": explosive_source,
            "explosive_sha256": hashlib.sha256(explosive_bytes).hexdigest().upper(),
        },
        "summary": {
            "weapon_count": len(weapons),
            "bomb_count": counts["bomb"],
            "rocket_count": counts["rocket"],
            "missile_count": counts["missile"],
            "unresolved_references": sorted(unresolved),
        },
        "weapons": weapons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("datamine_root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--splash-output", type=Path, default=DEFAULT_SPLASH_OUTPUT)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    datamine_root = Path(args.datamine_root)
    payload = extract_catalog(datamine_root, require_clean=not args.allow_dirty)
    commit = payload["provenance"]["datamine_commit"]
    version = payload["provenance"]["datamine_version"]
    splash = extract_splash_model(datamine_root.resolve(), commit, version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.splash_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.splash_output.write_text(
        json.dumps(splash, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = payload["summary"]
    print(
        "wrote",
        args.output,
        "weapons=",
        summary["weapon_count"],
        "bombs=",
        summary["bomb_count"],
        "rockets=",
        summary["rocket_count"],
        "missiles=",
        summary["missile_count"],
    )
    print("wrote", args.splash_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
