#!/usr/bin/env python3
"""Generate Bomana's aircraft-reachable weapon fire-control catalog.

Classification is driven by aircraft mount triggers and structured weapon data.
Filenames are retained only as stable identifiers and provenance.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from .datamine_utils import (
        CONTAINERS_SUBDIR,
        FLIGHTMODELS_SUBDIR,
        ROCKETGUNS_SUBDIR,
        WEAPON_LOCALIZATION_FILE,
        WEAPONS_SUBDIR,
        load_json_schema,
        normalize_datamine_caliber_m,
        read_datamine_version,
        read_git_commit,
        read_git_remote,
        require_clean_git_checkout,
        require_datamine_dir,
        validate_json_schema,
    )
except ImportError:
    from datamine_utils import (
        CONTAINERS_SUBDIR,
        FLIGHTMODELS_SUBDIR,
        ROCKETGUNS_SUBDIR,
        WEAPON_LOCALIZATION_FILE,
        WEAPONS_SUBDIR,
        load_json_schema,
        normalize_datamine_caliber_m,
        read_datamine_version,
        read_git_commit,
        read_git_remote,
        require_clean_git_checkout,
        require_datamine_dir,
        validate_json_schema,
    )

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA_PATH = ROOT / "docs/specs/schemas/weapon-fire-control.schema.json"
DEFAULT_OUTPUT_PATH = ROOT / "bomana/data/weapon_fire_control.json"
_RELEVANT_TRIGGERS = {"aam", "atgm", "bombs", "guided bombs", "rockets"}
_GUIDED_TYPES = {"laser", "optical", "radar", "saclos", "sns"}
_ZERO_WIDTH = str.maketrans("", "", "\u200b\u200c\u200d\ufeff")


@dataclass(frozen=True)
class MountReference:
    """One aircraft path to a referenced weapon or container BLK."""

    aircraft: str
    trigger: str
    icon_type: str
    blk: str
    chain: tuple[str, ...]


@dataclass(frozen=True)
class TerminalReference:
    """One resolved aircraft-to-projectile reference chain."""

    aircraft: str
    trigger: str
    icon_type: str
    source_path: Path
    source_data: dict[str, Any]
    source_section: str
    chain: tuple[str, ...]


@dataclass(frozen=True)
class MotorStage:
    duration_s: float
    thrust_n: float
    mass_end_kg: float
    duration_pointer: str
    thrust_pointer: str | None
    mass_pointer: str
    extra_pointers: tuple[tuple[str, str], ...] = ()


class DataminePathIndex:
    """Case-insensitive resolver for BLK references in the JSON datamine."""

    def __init__(self, datamine_root: Path) -> None:
        self.datamine_root = datamine_root
        self.gamedata_root = datamine_root / "aces.vromfs.bin_u" / "gamedata"
        candidates = [
            require_datamine_dir(datamine_root, WEAPONS_SUBDIR),
            require_datamine_dir(datamine_root, FLIGHTMODELS_SUBDIR) / "weaponpresets",
        ]
        self._paths: dict[str, Path] = {}
        for directory in candidates:
            if not directory.exists():
                continue
            for path in sorted(directory.rglob("*.blkx")):
                key = path.relative_to(self.gamedata_root).as_posix().casefold()
                existing = self._paths.get(key)
                if existing is not None and existing != path:
                    raise RuntimeError(f"case-insensitive datamine path collision: {key}")
                self._paths[key] = path

    def resolve(self, reference: str) -> Path | None:
        normalized = reference.strip().replace("\\", "/").lstrip("./")
        while "//" in normalized:
            normalized = normalized.replace("//", "/")
        if normalized.casefold().startswith("gamedata/"):
            normalized = normalized[len("gamedata/") :]
        if normalized.casefold().endswith(".blk"):
            normalized += "x"
        elif not Path(normalized).suffix:
            normalized += ".blkx"
        return self._paths.get(normalized.casefold())


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _json_pointer(parts: tuple[str | int, ...]) -> str:
    escaped = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(escaped)


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Resolve one RFC 6901 pointer or raise when its provenance is stale."""
    if not pointer.startswith("/"):
        raise ValueError(f"invalid JSON pointer: {pointer}")
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            current = current[token]
        elif isinstance(current, list):
            current = current[int(token)]
        else:
            raise KeyError(pointer)
    return current


def _item_paths(
    value: Any, parts: tuple[str | int, ...]
) -> list[tuple[Any, tuple[str | int, ...]]]:
    if isinstance(value, list):
        return [(item, (*parts, index)) for index, item in enumerate(value)]
    if value is None:
        return []
    return [(value, parts)]


def _repo_relative(datamine_root: Path, path: Path) -> str:
    return path.relative_to(datamine_root).as_posix()


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _clean_text(value: Any) -> str:
    text = str(value or "").translate(_ZERO_WIDTH).replace("\t", " ")
    return " ".join(text.split())


def _normalized_trigger(value: Any) -> str:
    return _clean_text(value).casefold()


def _is_supported_weapon_reference(reference: str) -> bool:
    normalized = reference.replace("\\", "/").casefold()
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return any(
        marker in normalized
        for marker in (
            "/weapons/bombguns/",
            "/weapons/rocketguns/",
            "/weapons/containers/",
        )
    )


def _find_icon_type(value: Any) -> str:
    if isinstance(value, dict):
        icon_type = value.get("iconType")
        if isinstance(icon_type, str) and icon_type.strip():
            return icon_type.strip()
        for child in value.values():
            found = _find_icon_type(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_icon_type(child)
            if found:
                return found
    return ""


def _mount_from_weapon(
    *,
    aircraft: str,
    weapon: Any,
    pointer_parts: tuple[str | int, ...],
    source_file: str,
    icon_type: str,
    prefix: tuple[str, ...] = (),
) -> MountReference | None:
    if not isinstance(weapon, dict) or weapon.get("dummy") is True:
        return None
    blk = weapon.get("blk")
    if not isinstance(blk, str) or not blk.strip():
        return None
    if not _is_supported_weapon_reference(blk):
        return None
    trigger = _normalized_trigger(weapon.get("trigger"))
    if trigger not in _RELEVANT_TRIGGERS:
        return None
    hop = f"{source_file}#{_json_pointer(pointer_parts)}"
    return MountReference(
        aircraft=aircraft,
        trigger=trigger,
        icon_type=icon_type or _find_icon_type(weapon),
        blk=blk,
        chain=(*prefix, hop),
    )


def _collect_aircraft_mounts(
    datamine_root: Path,
    path_index: DataminePathIndex,
) -> tuple[list[MountReference], set[str]]:
    flightmodels_dir = require_datamine_dir(datamine_root, FLIGHTMODELS_SUBDIR)
    mounts: list[MountReference] = []
    unresolved: set[str] = set()

    for fm_path in sorted(flightmodels_dir.glob("*.blkx")):
        try:
            unit = _load_object(fm_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            unresolved.add(f"{_repo_relative(datamine_root, fm_path)}: invalid JSON ({exc})")
            continue
        if "WeaponSlots" not in unit and "weapon_presets" not in unit:
            continue

        aircraft = fm_path.stem.casefold()
        fm_source = _repo_relative(datamine_root, fm_path)
        inline_by_slot: dict[tuple[str, str], list[MountReference]] = defaultdict(list)
        slots = unit.get("WeaponSlots")
        if isinstance(slots, dict):
            slot_value = slots.get("WeaponSlot")
            for slot, slot_parts in _item_paths(
                slot_value,
                ("WeaponSlots", "WeaponSlot"),
            ):
                if not isinstance(slot, dict):
                    continue
                slot_id = str(slot.get("index", ""))
                preset_value = slot.get("WeaponPreset")
                for preset, preset_parts in _item_paths(
                    preset_value,
                    (*slot_parts, "WeaponPreset"),
                ):
                    if not isinstance(preset, dict):
                        continue
                    preset_name = _clean_text(preset.get("name"))
                    icon_type = _find_icon_type(preset)
                    for weapon, weapon_parts in _item_paths(
                        preset.get("Weapon"),
                        (*preset_parts, "Weapon"),
                    ):
                        mount = _mount_from_weapon(
                            aircraft=aircraft,
                            weapon=weapon,
                            pointer_parts=weapon_parts,
                            source_file=fm_source,
                            icon_type=icon_type,
                        )
                        if mount is None:
                            continue
                        mounts.append(mount)
                        if preset_name:
                            inline_by_slot[(slot_id, preset_name)].append(mount)

        presets = unit.get("weapon_presets")
        if not isinstance(presets, dict):
            continue
        for preset_entry, entry_parts in _item_paths(
            presets.get("preset"),
            ("weapon_presets", "preset"),
        ):
            if not isinstance(preset_entry, dict):
                continue
            preset_ref = preset_entry.get("blk")
            if not isinstance(preset_ref, str) or not preset_ref.strip():
                continue
            preset_path = path_index.resolve(preset_ref)
            entry_hop = f"{fm_source}#{_json_pointer((*entry_parts, 'blk'))}"
            if preset_path is None:
                unresolved.add(f"{entry_hop} -> {preset_ref}")
                continue
            preset_source = _repo_relative(datamine_root, preset_path)
            try:
                preset_data = _load_object(preset_path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                unresolved.add(f"{preset_source}: invalid JSON ({exc})")
                continue

            for selector, selector_parts in _item_paths(
                preset_data.get("Weapon"),
                ("Weapon",),
            ):
                if not isinstance(selector, dict):
                    continue
                direct = _mount_from_weapon(
                    aircraft=aircraft,
                    weapon=selector,
                    pointer_parts=selector_parts,
                    source_file=preset_source,
                    icon_type=_find_icon_type(selector),
                    prefix=(entry_hop,),
                )
                if direct is not None:
                    mounts.append(direct)
                    continue

                slot_id = str(selector.get("slot", ""))
                preset_name = _clean_text(selector.get("preset"))
                if not slot_id or not preset_name:
                    continue
                selected = inline_by_slot.get((slot_id, preset_name), ())
                selector_hop = f"{preset_source}#{_json_pointer(selector_parts)}"
                if not selected:
                    continue
                for base in selected:
                    mounts.append(
                        MountReference(
                            aircraft=base.aircraft,
                            trigger=base.trigger,
                            icon_type=base.icon_type,
                            blk=base.blk,
                            chain=(entry_hop, selector_hop, *base.chain),
                        )
                    )
    return mounts, unresolved


def _resolve_mount(
    mount: MountReference,
    *,
    datamine_root: Path,
    path_index: DataminePathIndex,
    unresolved: set[str],
) -> TerminalReference | None:
    current_ref = mount.blk
    chain = list(mount.chain)
    visited: set[Path] = set()

    while True:
        path = path_index.resolve(current_ref)
        if path is None:
            unresolved.add(f"{chain[-1]} -> {current_ref}")
            return None
        if path in visited:
            unresolved.add(f"{chain[-1]} -> {current_ref} (container cycle)")
            return None
        visited.add(path)
        source_file = _repo_relative(datamine_root, path)
        try:
            payload = _load_object(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            unresolved.add(f"{source_file}: invalid JSON ({exc})")
            return None

        if payload.get("container") is True:
            nested_ref = payload.get("blk")
            if not isinstance(nested_ref, str) or not nested_ref.strip():
                unresolved.add(f"{source_file}#/blk -> missing container reference")
                return None
            chain.append(f"{source_file}#/blk")
            current_ref = nested_ref
            continue

        for section in ("rocket", "bomb"):
            if isinstance(payload.get(section), dict):
                chain.append(f"{source_file}#/{section}")
                return TerminalReference(
                    aircraft=mount.aircraft,
                    trigger=mount.trigger,
                    icon_type=mount.icon_type,
                    source_path=path,
                    source_data=payload,
                    source_section=section,
                    chain=tuple(chain),
                )
        return None


def _nominal_number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float) and math.isfinite(value):
        return float(value)
    if isinstance(value, list) and value:
        return _nominal_number(value[0], default)
    return default


def _number_sequence(value: Any) -> list[tuple[float, int | None]]:
    if isinstance(value, list):
        result: list[tuple[float, int | None]] = []
        for index, item in enumerate(value):
            number = _nominal_number(item, math.nan)
            if math.isfinite(number):
                result.append((number, index))
        return result
    number = _nominal_number(value, math.nan)
    return [(number, None)] if math.isfinite(number) else []


def _motor_values(section: dict[str, Any], field: str) -> list[tuple[float, str]]:
    values: list[tuple[float, str]] = []
    for suffix in ("", "1"):
        key = f"{field}{suffix}"
        for number, index in _number_sequence(section.get(key)):
            pointer = f"{key}/{index}" if index is not None else key
            values.append((number, pointer))
    return values


def _extract_legacy_motor_stages(
    section_name: str,
    section: dict[str, Any],
) -> list[MotorStage]:
    durations = _motor_values(section, "timeFire")
    thrusts = _motor_values(section, "force")
    masses = _motor_values(section, "massEnd")
    stages: list[MotorStage] = []
    for index in range(min(len(durations), len(masses))):
        duration, duration_field = durations[index]
        mass_end, mass_field = masses[index]
        if duration <= 0 or mass_end <= 0:
            continue
        if index < len(thrusts):
            thrust, thrust_field = thrusts[index]
        else:
            thrust, thrust_field = 0.0, None
        stages.append(
            MotorStage(
                duration_s=duration,
                thrust_n=max(0.0, thrust),
                mass_end_kg=mass_end,
                duration_pointer=f"/{section_name}/{duration_field}",
                thrust_pointer=(
                    f"/{section_name}/{thrust_field}" if thrust_field is not None else None
                ),
                mass_pointer=f"/{section_name}/{mass_field}",
            )
        )
    return stages


def _numbered_blocks(
    value: dict[str, Any],
    prefix: str,
) -> list[tuple[int, str, dict[str, Any]]]:
    pattern = re.compile(rf"{re.escape(prefix)}(\d+)")
    blocks: list[tuple[int, str, dict[str, Any]]] = []
    for key, block in value.items():
        match = pattern.fullmatch(key)
        if match is not None and isinstance(block, dict):
            blocks.append((int(match.group(1)), key, block))
    return sorted(blocks)


def _replace_last_stage_mass(
    stages: list[MotorStage],
    mass_end_kg: float,
    pointer: str,
    label: str,
) -> None:
    if not stages:
        return
    previous = stages[-1]
    stages[-1] = MotorStage(
        duration_s=previous.duration_s,
        thrust_n=previous.thrust_n,
        mass_end_kg=mass_end_kg,
        duration_pointer=previous.duration_pointer,
        thrust_pointer=previous.thrust_pointer,
        mass_pointer=previous.mass_pointer,
        extra_pointers=(*previous.extra_pointers, (label, pointer)),
    )


def _extract_modern_motor_stages(
    section_name: str,
    section: dict[str, Any],
) -> list[MotorStage]:
    current_mass = _nominal_number(section.get("mass"))
    current_mass_pointer = f"/{section_name}/mass"
    stages: list[MotorStage] = []

    for _, propulsion_name, propulsion in _numbered_blocks(section, "propulsion"):
        propulsion_pointer = f"/{section_name}/{propulsion_name}"
        delay = _nominal_number(propulsion.get("fireDelay"))
        if delay > 0:
            stages.append(
                MotorStage(
                    duration_s=delay,
                    thrust_n=0.0,
                    mass_end_kg=current_mass,
                    duration_pointer=f"{propulsion_pointer}/fireDelay",
                    thrust_pointer=None,
                    mass_pointer=current_mass_pointer,
                )
            )

        for impulse_index, impulse_name, impulse in _numbered_blocks(propulsion, "impulse"):
            impulse_pointer = f"{propulsion_pointer}/{impulse_name}"
            mass_lost = max(0.0, _nominal_number(impulse.get("massLost")))
            next_mass = current_mass - mass_lost
            if current_mass <= 0 or next_mass <= 0:
                raise RuntimeError(
                    f"invalid modern propulsion mass boundary: {impulse_pointer}/massLost"
                )

            extra_pointers: list[tuple[str, str]] = []
            if "time" in impulse:
                duration = _nominal_number(impulse.get("time"))
                duration_pointer = f"{impulse_pointer}/time"
            else:
                mass_flow = _nominal_number(impulse.get("massFlow"))
                duration = mass_lost / mass_flow if mass_flow > 0 else 0.0
                duration_pointer = f"{impulse_pointer}/massLost"
                if "massFlow" in impulse:
                    extra_pointers.append(("duration_s.mass_flow", f"{impulse_pointer}/massFlow"))

            if "force" in impulse:
                thrust = max(0.0, _nominal_number(impulse.get("force")))
                thrust_pointer: str | None = f"{impulse_pointer}/force"
            else:
                mass_flow = _nominal_number(impulse.get("massFlow"))
                specific_impulse = _nominal_number(impulse.get("isp"))
                thrust = max(0.0, mass_flow * specific_impulse)
                thrust_pointer = f"{impulse_pointer}/massFlow" if "massFlow" in impulse else None
                if "isp" in impulse:
                    extra_pointers.append(("thrust_n.isp", f"{impulse_pointer}/isp"))

            mass_pointer = f"{impulse_pointer}/massLost"
            if duration <= 0:
                current_mass = next_mass
                current_mass_pointer = mass_pointer
                _replace_last_stage_mass(
                    stages,
                    current_mass,
                    mass_pointer,
                    f"mass_end_kg.instant_mass_lost_{impulse_index}",
                )
                continue

            stages.append(
                MotorStage(
                    duration_s=duration,
                    thrust_n=thrust,
                    mass_end_kg=next_mass,
                    duration_pointer=duration_pointer,
                    thrust_pointer=thrust_pointer,
                    mass_pointer=mass_pointer,
                    extra_pointers=tuple(extra_pointers),
                )
            )
            current_mass = next_mass
            current_mass_pointer = mass_pointer
    return stages


def _extract_motor_stages(section_name: str, section: dict[str, Any]) -> list[MotorStage]:
    if _numbered_blocks(section, "propulsion"):
        return _extract_modern_motor_stages(section_name, section)
    return _extract_legacy_motor_stages(section_name, section)


def _leaf_source_pointers(
    value: Any,
    *,
    parts: tuple[str | int, ...],
    key_prefix: str,
) -> dict[str, str]:
    pointers: dict[str, str] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            pointers.update(
                _leaf_source_pointers(
                    child,
                    parts=(*parts, key),
                    key_prefix=f"{key_prefix}.{key}",
                )
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            pointers.update(
                _leaf_source_pointers(
                    child,
                    parts=(*parts, index),
                    key_prefix=f"{key_prefix}.{index}",
                )
            )
    else:
        pointers[key_prefix] = _json_pointer(parts)
    return pointers


def _model_support_audit(
    section_name: str,
    section: dict[str, Any],
) -> tuple[list[str], dict[str, str]]:
    reasons: set[str] = set()
    pointers: dict[str, str] = {}
    guidance = section.get("guidance")
    guidance = guidance if isinstance(guidance, dict) else {}
    propulsion_autopilot = guidance.get("propulsionAutopilot")
    if isinstance(propulsion_autopilot, dict):
        code = "conditional_propulsion_autopilot"
        reasons.add(code)
        block_parts: tuple[str | int, ...] = (
            section_name,
            "guidance",
            "propulsionAutopilot",
        )
        pointers[f"model_unsupported.{code}"] = _json_pointer(block_parts)
        pointers.update(
            _leaf_source_pointers(
                propulsion_autopilot,
                parts=block_parts,
                key_prefix=f"model_unsupported.{code}",
            )
        )

    for _, factor_name, factor in _numbered_blocks(section, "propulsionFactor"):
        code = "variable_propulsion_factor"
        reasons.add(code)
        factor_parts: tuple[str | int, ...] = (section_name, factor_name)
        pointers[f"model_unsupported.{code}.{factor_name}"] = _json_pointer(factor_parts)
        pointers.update(
            _leaf_source_pointers(
                factor,
                parts=factor_parts,
                key_prefix=f"model_unsupported.{code}.{factor_name}",
            )
        )

    for _, propulsion_name, propulsion in _numbered_blocks(section, "propulsion"):
        for _, impulse_name, impulse in _numbered_blocks(propulsion, "impulse"):
            impulse_parts: tuple[str | int, ...] = (
                section_name,
                propulsion_name,
                impulse_name,
            )
            if "factorIndex" in impulse:
                code = "impulse_factor_index"
                reasons.add(code)
                pointers[f"model_unsupported.{code}.{propulsion_name}.{impulse_name}"] = (
                    _json_pointer((*impulse_parts, "factorIndex"))
                )
            if (
                "time" in impulse
                and _nominal_number(impulse.get("time")) == 0.0
                and _nominal_number(impulse.get("massLost")) > 0.0
            ):
                code = "instantaneous_mass_change"
                reasons.add(code)
                pointer_prefix = f"model_unsupported.{code}.{propulsion_name}.{impulse_name}"
                pointers[f"{pointer_prefix}.time"] = _json_pointer((*impulse_parts, "time"))
                pointers[f"{pointer_prefix}.mass_lost"] = _json_pointer(
                    (*impulse_parts, "massLost")
                )

    return sorted(reasons), pointers


def _finite_numbers(value: Any) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, int | float):
        return [float(value)] if math.isfinite(value) else []
    if isinstance(value, list):
        return [number for item in value for number in _finite_numbers(item)]
    return []


def _guidance_min_range_evidence(
    section_name: str,
    section: dict[str, Any],
    *,
    role: str,
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    if role != "aam":
        return None, {}
    guidance = section.get("guidance")
    if not isinstance(guidance, dict):
        return None, {}

    tables: list[dict[str, Any]] = []
    all_values: list[float] = []
    pointers: dict[str, str] = {}
    field_names = {
        "rangeMin": "range_min_m",
        "rangeMinDogfight": "range_min_dogfight_m",
    }
    for _, table_name, table in _numbered_blocks(guidance, "table"):
        table_payload: dict[str, Any] = {"table": table_name}
        for raw_name, output_name in field_names.items():
            values = _finite_numbers(table.get(raw_name))
            if not values:
                continue
            if any(value < 0 for value in values):
                raise RuntimeError(
                    f"negative AAM minimum range: /{section_name}/guidance/{table_name}/{raw_name}"
                )
            table_payload[output_name] = values
            all_values.extend(values)
            pointers[f"guidance_min_ranges.{table_name}.{output_name}"] = (
                f"/{section_name}/guidance/{table_name}/{raw_name}"
            )
        if len(table_payload) > 1:
            tables.append(table_payload)
    if not tables:
        return None, {}
    return {
        "tables": tables,
        "conservative_floor_m": min(all_values),
    }, pointers


def _classify_role(trigger_groups: set[str], section_name: str, section: dict[str, Any]) -> str:
    if "aam" in trigger_groups:
        return "aam"
    if "atgm" in trigger_groups:
        return "agm"
    if trigger_groups & {"guided bombs", "bombs"}:
        return "bomb"

    bullet_type = _clean_text(section.get("bulletType")).casefold()
    if "aam" in bullet_type:
        return "aam"
    if section_name == "bomb" or "bomb" in bullet_type:
        return "bomb"
    return "agm"


def _is_guided(
    section: dict[str, Any],
    trigger_groups: set[str],
    icon_types: set[str],
) -> bool:
    guidance_type = _clean_text(section.get("guidanceType")).casefold()
    guidance = section.get("guidance")
    if guidance_type in _GUIDED_TYPES or isinstance(guidance, dict) and bool(guidance):
        return True

    control_sensitivity = _nominal_number(section.get("controlSensitivity"))
    command_trigger = bool(trigger_groups & {"aam", "atgm", "guided bombs"})
    command_icon = any(
        "guided" in icon.casefold() or "missile_air_to_" in icon.casefold() for icon in icon_types
    )
    return control_sensitivity > 0.0 and (command_trigger or command_icon)


def _primary_seeker(guidance: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    for key in ("radarSeeker", "laserSeeker", "opticalSeeker"):
        value = guidance.get(key)
        if isinstance(value, dict):
            return key, value
    return "none", {}


def _classify_guidance(
    role: str,
    section: dict[str, Any],
    *,
    guided: bool,
) -> tuple[str, str, dict[str, Any]]:
    guidance_type = _clean_text(section.get("guidanceType")).casefold()
    guidance = section.get("guidance")
    guidance = guidance if isinstance(guidance, dict) else {}
    seeker_name, seeker = _primary_seeker(guidance)

    if not guided:
        return "none", "none", guidance
    if guidance_type == "radar" or seeker_name == "radarSeeker":
        kind = "radar_active" if seeker.get("active") is True else "radar_semi_active"
    elif guidance_type == "laser" or seeker_name == "laserSeeker":
        kind = "laser"
    elif guidance_type == "sns":
        kind = "ins_gnss"
        seeker_name = "inertial_navigation"
    elif guidance_type == "saclos" or "lineOfSightAutopilot" in guidance:
        kind = "saclos"
        if seeker_name == "none":
            seeker_name = "line_of_sight"
    elif guidance_type == "optical" or seeker_name == "opticalSeeker":
        signature = _clean_text(seeker.get("targetSignatureType")).casefold()
        kind = "ir" if signature == "infrared" or role == "aam" and not signature else "tv"
        if role == "bomb" and guidance.get("inertialNavigation") is True:
            kind = "mixed"
    else:
        kind = "unknown"
    return kind, seeker_name, guidance


def _guidance_payload(
    section_name: str,
    section: dict[str, Any],
    *,
    guided: bool,
) -> tuple[dict[str, Any], dict[str, str]]:
    if not guided:
        return {"type": "none", "seeker": "none"}, {}

    control_sensitivity = _nominal_number(section.get("controlSensitivity"))
    legacy_command = "guidanceType" not in section and control_sensitivity > 0.0
    guidance_type = (
        "legacy_command"
        if legacy_command
        else _clean_text(section.get("guidanceType")) or "structured"
    )
    guidance = section.get("guidance")
    guidance = guidance if isinstance(guidance, dict) else {}
    seeker_name, seeker = _primary_seeker(guidance)
    if guidance_type.casefold() == "sns" and seeker_name == "none":
        seeker_name = "inertial_navigation"
    elif guidance_type.casefold() == "saclos" and seeker_name == "none":
        seeker_name = "line_of_sight"
    elif legacy_command:
        seeker_name = "command"
    payload: dict[str, Any] = {"type": guidance_type, "seeker": seeker_name}
    pointers: dict[str, str] = {}
    if legacy_command:
        payload["control_sensitivity"] = control_sensitivity
        pointers["guidance.type"] = f"/{section_name}/controlSensitivity"
        pointers["guidance.control_sensitivity"] = f"/{section_name}/controlSensitivity"
    elif "guidanceType" in section:
        pointers["guidance.type"] = f"/{section_name}/guidanceType"

    seeker_fields = {
        "range_max_m": "rangeMax",
        "range_rear_m": "rangeBand0",
        "range_all_aspect_m": "rangeBand1",
        "lock_angle_max_deg": "lockAngleMax",
        "angle_max_deg": "angleMax",
    }
    for output_name, raw_name in seeker_fields.items():
        if raw_name not in seeker:
            continue
        payload[output_name] = max(0.0, _nominal_number(seeker[raw_name]))
        pointers[f"guidance.{output_name}"] = f"/{section_name}/guidance/{seeker_name}/{raw_name}"
    if "launchAngleMax" in guidance:
        payload["launch_angle_max_deg"] = max(
            0.0,
            _nominal_number(guidance["launchAngleMax"]),
        )
        pointers["guidance.launch_angle_max_deg"] = f"/{section_name}/guidance/launchAngleMax"
    autopilot = guidance.get("guidanceAutopilot")
    if isinstance(autopilot, dict) and "reqAccelMax" in autopilot:
        payload["autopilot_max_g"] = max(0.0, _nominal_number(autopilot["reqAccelMax"]))
        pointers["guidance.autopilot_max_g"] = (
            f"/{section_name}/guidance/guidanceAutopilot/reqAccelMax"
        )
    return payload, pointers


def _has_positive_sequence(value: Any) -> bool:
    return any(number > 0 for number, _ in _number_sequence(value))


def _classify_planform(
    role: str,
    guided: bool,
    source_data: dict[str, Any],
    section: dict[str, Any],
    icon_types: set[str],
) -> str:
    if role != "bomb":
        return "normal"
    glide_icon = any("glide_guided_bomb" in icon.casefold() for icon in icon_types)
    deployed_evidence = bool(_clean_text(source_data.get("mesh_deployed")))
    wing_evidence = (
        _nominal_number(section.get("wingAreaMult")) > 0
        and _has_positive_sequence(section.get("brakeTime"))
        and _nominal_number(section.get("brakeCxK")) > 0
    )
    if guided and (deployed_evidence or wing_evidence):
        return "glide"
    if glide_icon and (deployed_evidence or wing_evidence):
        return "glide"
    if (
        _has_positive_sequence(section.get("brakeTime"))
        and _nominal_number(section.get("brakeCxK")) > 0
    ):
        return "high_drag"
    return "normal"


def _load_localization(path: Path) -> dict[str, tuple[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.reader(handle, delimiter=";")
        header = next(rows)
        normalized = [_clean_text(value).strip("<>").casefold() for value in header]
        try:
            id_index = normalized.index("id|readonly|noverify")
            english_index = normalized.index("english")
            chinese_index = normalized.index("chinese")
        except ValueError as exc:
            raise RuntimeError(f"unexpected localization header: {path}") from exc
        result: dict[str, tuple[str, str]] = {}
        required_index = max(id_index, english_index, chinese_index)
        for row in rows:
            if len(row) <= required_index:
                continue
            key = _clean_text(row[id_index]).casefold()
            english = _clean_text(row[english_index])
            chinese = _clean_text(row[chinese_index])
            if key and english:
                result[key] = (english, chinese or english)
        return result


def _display_names(
    source_path: Path,
    section: dict[str, Any],
    localization: dict[str, tuple[str, str]],
) -> tuple[str, str]:
    candidates = []
    bullet_name = _clean_text(section.get("bulletName"))
    if bullet_name:
        candidates.append(bullet_name.casefold())
    candidates.append(source_path.stem.casefold())
    for candidate in candidates:
        value = localization.get(f"weapons/{candidate}")
        if value is not None:
            return value
    fallback = source_path.stem.replace("_", " ").strip()
    return fallback, fallback


def _build_weapon_record(
    datamine_root: Path,
    terminals: list[TerminalReference],
    localization: dict[str, tuple[str, str]],
) -> dict[str, Any] | None:
    first = terminals[0]
    source_data = first.source_data
    section_name = first.source_section
    section = source_data[section_name]
    trigger_groups = {terminal.trigger for terminal in terminals}
    role = _classify_role(trigger_groups, section_name, section)
    icon_types = {terminal.icon_type for terminal in terminals if terminal.icon_type}
    guided = _is_guided(section, trigger_groups, icon_types)
    if role in {"aam", "agm"} and not guided:
        return None

    stages = _extract_motor_stages(section_name, section)
    propulsion = "powered" if any(stage.thrust_n > 0 for stage in stages) else "unpowered"
    unsupported_reasons, unsupported_pointers = _model_support_audit(section_name, section)
    guidance_kind, _, _ = _classify_guidance(role, section, guided=guided)
    planform = _classify_planform(role, guided, source_data, section, icon_types)
    mass_start = _nominal_number(section.get("mass"))
    raw_caliber = _nominal_number(section.get("caliber"))
    caliber, caliber_normalization = normalize_datamine_caliber_m(
        raw_caliber,
        first.source_path.name,
        _clean_text(source_data.get("mesh")),
        _clean_text(section.get("bulletName")),
    )
    if mass_start <= 0 or caliber <= 0:
        return None
    raw_mass_end = _motor_values(section, "massEnd")
    mass_end = (
        stages[-1].mass_end_kg if stages else (raw_mass_end[-1][0] if raw_mass_end else mass_start)
    )
    if mass_end <= 0:
        mass_end = mass_start

    display_name, display_name_zh = _display_names(first.source_path, section, localization)
    source_file = _repo_relative(datamine_root, first.source_path)
    pointers: dict[str, str] = {
        "mass_start_kg": f"/{section_name}/mass",
        "caliber_m": f"/{section_name}/caliber",
    }
    raw_fields = {
        "cx_k": "CxK",
        "drag_cx": "dragCx",
        "wing_area_mult": "wingAreaMult",
        "fins_aoa_horiz": "finsAoaHor",
        "fins_aoa_vert": "finsAoaVer",
        "time_life_s": "timeLife",
        "start_speed_mps": "startSpeed",
        "min_distance_m": "minDistance",
        "hard_max_distance_m": "maxDistance",
        "stat_card_range_m": "rangeMax",
        "max_speed_mps": "endSpeed",
        "mach_max": "machMax",
    }
    values: dict[str, float] = {}
    for output_name, raw_name in raw_fields.items():
        raw_value = _nominal_number(section.get(raw_name))
        if output_name.startswith("fins_aoa_"):
            raw_value *= 90.0
        values[output_name] = max(0.0, raw_value)
        if raw_name in section:
            pointers[output_name] = f"/{section_name}/{raw_name}"

    motor_payload: list[dict[str, float]] = []
    for index, stage in enumerate(stages):
        motor_payload.append(
            {
                "duration_s": stage.duration_s,
                "thrust_n": stage.thrust_n,
                "mass_end_kg": stage.mass_end_kg,
            }
        )
        pointers[f"motor_stages.{index}.duration_s"] = stage.duration_pointer
        if stage.thrust_pointer is not None:
            pointers[f"motor_stages.{index}.thrust_n"] = stage.thrust_pointer
        pointers[f"motor_stages.{index}.mass_end_kg"] = stage.mass_pointer
        for label, pointer in stage.extra_pointers:
            pointers[f"motor_stages.{index}.{label}"] = pointer
    if stages:
        pointers["mass_end_kg"] = stages[-1].mass_pointer
    elif raw_mass_end:
        pointers["mass_end_kg"] = f"/{section_name}/{raw_mass_end[-1][1]}"
    else:
        pointers["mass_end_kg"] = f"/{section_name}/mass"

    guidance, guidance_pointers = _guidance_payload(
        section_name,
        section,
        guided=guided,
    )
    pointers.update(guidance_pointers)
    pointers.update(unsupported_pointers)
    guidance_min_ranges, guidance_min_range_pointers = _guidance_min_range_evidence(
        section_name,
        section,
        role=role,
    )
    pointers.update(guidance_min_range_pointers)
    for pointer in pointers.values():
        try:
            resolve_json_pointer(source_data, pointer)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError(f"unresolvable source pointer in {source_file}: {pointer}") from exc
    representative_chains: dict[str, tuple[str, ...]] = {}
    for terminal in terminals:
        existing = representative_chains.get(terminal.aircraft)
        if existing is None or (len(terminal.chain), terminal.chain) < (len(existing), existing):
            representative_chains[terminal.aircraft] = terminal.chain
    reference_chains = sorted(representative_chains.values())
    aircraft = sorted({terminal.aircraft for terminal in terminals})
    weapon_id = first.source_path.stem.casefold()
    record = {
        "id": weapon_id,
        "display_name": display_name,
        "display_name_zh": display_name_zh,
        "role": role,
        "propulsion": propulsion,
        "model_unsupported_reasons": unsupported_reasons,
        "control": "guided" if guided else "unguided",
        "guidance_kind": guidance_kind,
        "planform": planform,
        "source_file": source_file,
        "source_sha256": hashlib.sha256(first.source_path.read_bytes()).hexdigest(),
        "source_pointers": dict(sorted(pointers.items())),
        "reference_chains": [list(chain) for chain in reference_chains],
        "source_section": section_name,
        "trigger_groups": sorted(trigger_groups),
        "compatible_aircraft": aircraft,
        "mass_start_kg": mass_start,
        "mass_end_kg": mass_end,
        "caliber_m": caliber,
        **values,
        "motor_stages": motor_payload,
        "guidance": guidance,
    }
    if caliber_normalization is not None:
        record["normalizations"] = [caliber_normalization]
    if guidance_min_ranges is not None:
        record["guidance_min_ranges"] = guidance_min_ranges
    return record


def extract_catalog(
    datamine_root: Path,
    *,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    require_clean: bool = True,
) -> dict[str, Any]:
    """Extract and schema-validate one weapon catalog from a datamine tree."""
    datamine_root = datamine_root.resolve()
    if require_clean:
        require_clean_git_checkout(datamine_root)
    commit = read_git_commit(datamine_root)
    if require_clean and len(commit) != 40:
        raise RuntimeError("unable to read full datamine source commit")
    version = read_datamine_version(datamine_root)
    if not version:
        raise RuntimeError("missing datamine game version")

    schema = load_json_schema(schema_path)
    path_index = DataminePathIndex(datamine_root)
    mounts, unresolved = _collect_aircraft_mounts(datamine_root, path_index)
    grouped: dict[Path, list[TerminalReference]] = defaultdict(list)
    for mount in mounts:
        terminal = _resolve_mount(
            mount,
            datamine_root=datamine_root,
            path_index=path_index,
            unresolved=unresolved,
        )
        if terminal is not None:
            grouped[terminal.source_path].append(terminal)

    localization_path = datamine_root / WEAPON_LOCALIZATION_FILE
    if not localization_path.is_file():
        raise FileNotFoundError(f"missing localization file: {localization_path}")
    localization = _load_localization(localization_path)
    weapons: dict[str, dict[str, Any]] = {}
    for source_path in sorted(grouped):
        record = _build_weapon_record(datamine_root, grouped[source_path], localization)
        if record is None:
            continue
        weapon_id = record["id"]
        if weapon_id in weapons:
            raise RuntimeError(f"duplicate weapon id: {weapon_id}")
        weapons[weapon_id] = record

    aircraft_weapons: dict[str, list[str]] = defaultdict(list)
    for weapon_id, weapon in weapons.items():
        for aircraft in weapon["compatible_aircraft"]:
            aircraft_weapons[aircraft].append(weapon_id)
    aircraft_payload = {
        aircraft: sorted(set(weapon_ids))
        for aircraft, weapon_ids in sorted(aircraft_weapons.items())
        if weapon_ids
    }
    source_subdirs = [
        FLIGHTMODELS_SUBDIR.as_posix(),
        (WEAPONS_SUBDIR / "bombguns").as_posix(),
        ROCKETGUNS_SUBDIR.as_posix(),
        CONTAINERS_SUBDIR.as_posix(),
        WEAPON_LOCALIZATION_FILE.parent.as_posix(),
    ]
    schema_version = int(schema["properties"]["schema_version"]["const"])
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "meta": {
            "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source_repo": read_git_remote(datamine_root) or datamine_root.name,
            "source_version": version,
            "source_commit": commit or "0" * 40,
            "source_subdirs": source_subdirs,
            "weapon_count": len(weapons),
            "aircraft_count": len(aircraft_payload),
            "unresolved_references": sorted(unresolved),
        },
        "weapons": dict(sorted(weapons.items())),
        "aircraft_weapons": aircraft_payload,
    }
    validate_json_schema(payload, schema, path="weapon catalog")
    return payload


def write_catalog(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the Bomana weapon fire-control catalog from WT datamine data."
    )
    parser.add_argument("datamine_root", type=Path, help="clean War-Thunder-Datamine root")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH)
    args = parser.parse_args()

    try:
        payload = extract_catalog(
            args.datamine_root,
            schema_path=args.schema.resolve(),
            require_clean=True,
        )
        write_catalog(args.output.resolve(), payload)
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        print(f"[error] {exc}")
        return 1

    meta = payload["meta"]
    print("[summary] Bomana weapon catalog refreshed")
    print(f"  source: version={meta['source_version']} commit={meta['source_commit'][:12]}")
    print(
        f"  catalog: weapons={meta['weapon_count']} aircraft={meta['aircraft_count']} "
        f"unresolved={len(meta['unresolved_references'])}"
    )
    print(f"  wrote: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
