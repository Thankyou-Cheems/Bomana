"""Source-backed, offline strike encyclopedia models and airfield diagrams."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bomana.config.static_data import (
    BOMBING_ZONE_SPLASH_JSON,
    EC_AIRFIELD_CATALOG_JSON,
    STRIKE_ENCYCLOPEDIA_JSON,
    STRIKE_WEAPON_DAMAGE_JSON,
)
from bomana.core.hangar_base_damage import (
    BombingZoneSplashModel,
    HangarBaseDamageError,
    HangarDamageInputs,
    load_splash_model,
)
from bomana.utils.file_utils import resource_path

_SCHEMA = "bomana_strike_encyclopedia/v1"
_WEAPON_CATALOG_SCHEMA = "bomana_strike_weapon_damage/v1"
_CATALOG_SCHEMA = "wt_ec_airfield_template/v1"
_WEAPON_KINDS = {"bomb", "rocket", "missile"}
_WEAPON_DAMAGE_MODELS = {
    "splash_tnte_curve",
    "napalm_splash_fire",
    "nuclear_yield",
    "native_unknown",
}
_KIND_LABELS = {
    "bomb": "炸弹",
    "rocket": "火箭弹",
    "missile": "导弹",
}
_MODULE_ORDER = ("airfield", "storage", "parking", "dwelling")
_MODULE_LABELS = {
    "airfield": "跑道",
    "storage": "油库 / 储存区",
    "parking": "停机 / 维修区",
    "dwelling": "生活区",
}
_MODULE_COLORS = {
    "airfield": "#2477A8",
    "storage": "#C85145",
    "parking": "#D7A62C",
    "dwelling": "#37936B",
}


class StrikeEncyclopediaError(ValueError):
    """Raised when a bundled encyclopedia source violates its static contract."""


@dataclass(frozen=True)
class BombingPointDurabilityTier:
    balance_level_range: tuple[int, int]
    planes_mission_hp: float
    heli_mission_hp: float


@dataclass(frozen=True)
class AirportDurabilityTier:
    balance_level_range: tuple[int, int]
    auxiliary_module_mission_hp: float
    runway_mission_hp: float
    repair_base_hp: float


@dataclass(frozen=True)
class BombingPointBehavior:
    hp_fire_mult: float
    fire_speed: float
    depletion_seconds_reference: float
    fire_tail_evidence_kind: str
    respawn_seconds: float
    respawn_evidence_kind: str


@dataclass(frozen=True)
class AirportBehavior:
    has_fire_tail: bool
    repair_timing_kind: str
    repair_evidence_kind: str


@dataclass(frozen=True)
class BombingZoneTntConversion:
    hp_to_tnt_equivalent_tons: float
    evidence_kind: str


@dataclass(frozen=True)
class WeaponReference:
    weapon_id: str
    kind: str
    display_name: str
    display_name_zh: str
    mass_kg: float
    explosive_type: str
    raw_explosive_mass_kg: float
    tnte_reference_kg: float | None
    strength_equivalent: float
    mission_damage_model: str
    splash_damage: float | None
    splash_penetration: float | None
    splash_damage_type: str
    fire_damage: float | None
    fire_life_time: float | None
    nuclear_yield_kt: float | None

    @property
    def calculator_label(self) -> str:
        name = self.display_name_zh or self.display_name
        return f"{name}  ·  {self.weapon_id}"

    def hangar_inputs(self) -> HangarDamageInputs:
        return HangarDamageInputs(
            explosive_mass_kg=self.raw_explosive_mass_kg,
            strength_equivalent=self.strength_equivalent,
            splash_damage=self.splash_damage,
            splash_penetration=self.splash_penetration,
            splash_damage_type=self.splash_damage_type,
            fire_damage=self.fire_damage,
            fire_life_time=self.fire_life_time,
            nuclear_yield_kt=self.nuclear_yield_kt,
            mission_damage_model=self.mission_damage_model,
        )


@dataclass(frozen=True)
class PracticalReference:
    reference_id: str
    scope: str
    weapon_id: str
    weapon_count: int
    total_tnte_reference_kg: float
    evidence_kind: str
    is_mission_damage_formula: bool
    source_url: str


@dataclass(frozen=True)
class ModuleGeometry:
    module_id: str
    label: str
    start_xz: tuple[float, float]
    end_xz: tuple[float, float]
    width_m: float


@dataclass(frozen=True)
class AirfieldLayout:
    layout_id: str
    label: str
    source_unit_class: str
    module_geometry_fingerprint: str
    runway_length_m: float
    modules: tuple[ModuleGeometry, ...]


@dataclass(frozen=True)
class SceneShape:
    module_id: str
    label: str
    color: str
    points: tuple[tuple[float, float], ...]
    label_position: tuple[float, float]


@dataclass(frozen=True)
class AirfieldScene:
    width: int
    height: int
    shapes: tuple[SceneShape, ...]
    disclaimer: str


@dataclass(frozen=True)
class StrikeEncyclopedia:
    schema: str
    provenance: Mapping[str, str]
    bombing_point_tiers: tuple[BombingPointDurabilityTier, ...]
    airport_tiers: tuple[AirportDurabilityTier, ...]
    bombing_point_behavior: BombingPointBehavior
    airport_behavior: AirportBehavior
    bombing_zone_tnt_conversion: BombingZoneTntConversion
    bombing_zone_splash: BombingZoneSplashModel
    weapon_references: tuple[WeaponReference, ...]
    practical_references: tuple[PracticalReference, ...]
    airfield_layouts: tuple[AirfieldLayout, ...]
    disclaimer: str


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StrikeEncyclopediaError(f"invalid_{label}")
    return value


def _list(value: object, label: str, *, exact: int | None = None) -> list[Any]:
    if not isinstance(value, list) or not value or len(value) > 64:
        raise StrikeEncyclopediaError(f"invalid_{label}")
    if exact is not None and len(value) != exact:
        raise StrikeEncyclopediaError(f"invalid_{label}_count")
    return value


def _weapon_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list) or not value or len(value) > 2000:
        raise StrikeEncyclopediaError(f"invalid_{label}")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StrikeEncyclopediaError(f"invalid_{label}")
    return value.strip()


def _optional_text(value: object, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise StrikeEncyclopediaError(f"invalid_{label}")
    return value.strip()


def _number(value: object, label: str, *, positive: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StrikeEncyclopediaError(f"invalid_{label}")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0):
        raise StrikeEncyclopediaError(f"invalid_{label}")
    return result


def _optional_number(value: object, label: str) -> float | None:
    if value is None:
        return None
    return _number(value, label, positive=False)


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise StrikeEncyclopediaError(f"invalid_{label}")
    return value


def _balance_range(value: object) -> tuple[int, int]:
    items = _list(value, "balance_level", exact=2)
    if any(isinstance(item, bool) or not isinstance(item, int) for item in items):
        raise StrikeEncyclopediaError("invalid_balance_level")
    start, end = items
    if start < 0 or end < start:
        raise StrikeEncyclopediaError("invalid_balance_level")
    return start, end


def _source_path(relative_path: str, override: str | Path | None) -> Path:
    return Path(override) if override is not None else Path(resource_path(relative_path))


def _sha256_text(path: Path) -> str:
    """Hash file bytes after normalizing Git-checked-out CRLF to LF."""

    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest().upper()


def _load_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StrikeEncyclopediaError(f"unreadable_{label}") from exc
    return _mapping(payload, label)


def _load_module_geometry(module_id: str, raw: Mapping[str, Any]) -> ModuleGeometry:
    def xz(value: object, label: str) -> tuple[float, float]:
        vector = _list(value, label, exact=3)
        coordinates = tuple(_number(item, label, positive=False) for item in vector)
        return coordinates[0], coordinates[2]

    return ModuleGeometry(
        module_id=module_id,
        label=_MODULE_LABELS[module_id],
        start_xz=xz(raw.get("start"), f"{module_id}_start"),
        end_xz=xz(raw.get("end"), f"{module_id}_end"),
        width_m=_number(raw.get("width"), f"{module_id}_width"),
    )


def _layout_identity(unit_class: str) -> tuple[str, str, int]:
    if "1line_3000" in unit_class:
        return "long_3200", "现代长跑道 · 3200 m", 0
    suffixes = {
        "dynaf_universal_1line_a": ("layout_a_1670", "机场布局 A · 1670 m", 1),
        "dynaf_universal_1line_b": ("layout_b_1635", "机场布局 B · 1635 m", 2),
        "dynaf_universal_1line_c": ("layout_c_1635", "机场布局 C · 1635 m", 3),
    }
    for suffix, identity in suffixes.items():
        if unit_class == suffix or unit_class.startswith(f"{suffix}_"):
            return identity
    raise StrikeEncyclopediaError("unknown_airfield_geometry")


def _load_airfield_layouts(catalog: Mapping[str, Any]) -> tuple[AirfieldLayout, ...]:
    if catalog.get("schema") != _CATALOG_SCHEMA:
        raise StrikeEncyclopediaError("unsupported_airfield_catalog_schema")
    unique_templates: dict[str, Mapping[str, Any]] = {}
    for item in _list(catalog.get("templates"), "airfield_templates"):
        template = _mapping(item, "airfield_template")
        fingerprint = _text(
            template.get("module_geometry_fingerprint"), "module_geometry_fingerprint"
        )
        unique_templates.setdefault(fingerprint, template)

    layouts: list[tuple[int, AirfieldLayout]] = []
    for fingerprint, template in unique_templates.items():
        unit_class = _text(template.get("unit_class"), "unit_class")
        layout_id, label, order = _layout_identity(unit_class)
        geometry = _mapping(template.get("module_geometry"), "module_geometry")
        raw_modules = _mapping(geometry.get("modules"), "modules")
        modules = tuple(
            _load_module_geometry(module_id, _mapping(raw_modules.get(module_id), module_id))
            for module_id in _MODULE_ORDER
        )
        runway = modules[0]
        runway_length = math.dist(runway.start_xz, runway.end_xz)
        layouts.append(
            (
                order,
                AirfieldLayout(
                    layout_id=layout_id,
                    label=label,
                    source_unit_class=unit_class,
                    module_geometry_fingerprint=fingerprint,
                    runway_length_m=runway_length,
                    modules=modules,
                ),
            )
        )
    layouts.sort(key=lambda item: item[0])
    if [layout.layout_id for _, layout in layouts] != [
        "long_3200",
        "layout_a_1670",
        "layout_b_1635",
        "layout_c_1635",
    ]:
        raise StrikeEncyclopediaError("unexpected_airfield_layout_set")
    return tuple(layout for _, layout in layouts)


def _load_weapon_reference(item: object) -> WeaponReference:
    raw = _mapping(item, "weapon_reference")
    return WeaponReference(
        weapon_id=_text(raw.get("weapon_id"), "weapon_id"),
        kind=_text(raw.get("kind"), "kind"),
        display_name=_text(raw.get("display_name"), "display_name"),
        display_name_zh=_text(raw.get("display_name_zh"), "display_name_zh"),
        mass_kg=_number(raw.get("mass_kg"), "mass_kg", positive=False),
        explosive_type=_optional_text(raw.get("explosive_type"), "explosive_type"),
        raw_explosive_mass_kg=_number(
            raw.get("raw_explosive_mass_kg"),
            "raw_explosive_mass_kg",
            positive=False,
        ),
        tnte_reference_kg=(
            None
            if raw.get("tnte_reference_kg") is None
            else _number(raw.get("tnte_reference_kg"), "tnte_reference_kg")
        ),
        strength_equivalent=_number(
            raw.get("strength_equivalent"),
            "strength_equivalent",
            positive=False,
        ),
        mission_damage_model=_text(raw.get("mission_damage_model"), "mission_damage_model"),
        splash_damage=_optional_number(raw.get("splash_damage"), "splash_damage"),
        splash_penetration=_optional_number(raw.get("splash_penetration"), "splash_penetration"),
        splash_damage_type=_optional_text(raw.get("splash_damage_type"), "splash_damage_type"),
        fire_damage=_optional_number(raw.get("fire_damage"), "fire_damage"),
        fire_life_time=_optional_number(raw.get("fire_life_time"), "fire_life_time"),
        nuclear_yield_kt=_optional_number(raw.get("nuclear_yield_kt"), "nuclear_yield_kt"),
    )


def search_weapon_references(
    weapons: tuple[WeaponReference, ...],
    query: str,
    *,
    kind: str | None = None,
) -> tuple[WeaponReference, ...]:
    """Filter calculator weapons by kind and a case-insensitive name/id query."""

    if kind is not None and kind not in _WEAPON_KINDS:
        raise StrikeEncyclopediaError("invalid_weapon_kind")
    needle = " ".join(str(query or "").casefold().split())
    selected = []
    for weapon in weapons:
        if kind is not None and weapon.kind != kind:
            continue
        haystack = " ".join(
            (
                weapon.weapon_id,
                weapon.display_name,
                weapon.display_name_zh,
                weapon.explosive_type,
                _KIND_LABELS[weapon.kind],
            )
        ).casefold()
        if needle and needle not in haystack:
            continue
        selected.append(weapon)
    return tuple(selected)


def wiki_weapon_samples(weapons: tuple[WeaponReference, ...]) -> tuple[WeaponReference, ...]:
    """Return the few weapons that still carry an official Wiki TNTe column."""

    return tuple(weapon for weapon in weapons if weapon.tnte_reference_kg is not None)


def load_strike_encyclopedia(
    encyclopedia_path: str | Path | None = None,
    airfield_catalog_path: str | Path | None = None,
) -> StrikeEncyclopedia:
    """Load the bundled reference data and derive the four real static layouts."""

    encyclopedia_source = _source_path(STRIKE_ENCYCLOPEDIA_JSON, encyclopedia_path)
    catalog_source = _source_path(EC_AIRFIELD_CATALOG_JSON, airfield_catalog_path)
    payload = _load_json(encyclopedia_source, "strike_encyclopedia")
    catalog = _load_json(catalog_source, "airfield_catalog")
    if payload.get("schema") != _SCHEMA:
        raise StrikeEncyclopediaError("unsupported_schema")

    provenance_raw = _mapping(payload.get("provenance"), "provenance")
    provenance = {str(key): _text(value, str(key)) for key, value in provenance_raw.items()}
    expected_catalog_hash = provenance.get("airfield_catalog_sha256", "").upper()
    actual_catalog_hash = _sha256_text(catalog_source)
    if actual_catalog_hash != expected_catalog_hash:
        raise StrikeEncyclopediaError("airfield_catalog_hash_mismatch")

    bombing_point_tiers = tuple(
        BombingPointDurabilityTier(
            balance_level_range=_balance_range(raw.get("balance_level")),
            planes_mission_hp=_number(raw.get("planes_mission_hp"), "planes_mission_hp"),
            heli_mission_hp=_number(raw.get("heli_mission_hp"), "heli_mission_hp"),
        )
        for item in _list(payload.get("bombing_point_tiers"), "bombing_point_tiers", exact=6)
        for raw in (_mapping(item, "bombing_point_tier"),)
    )
    airport_tiers = tuple(
        AirportDurabilityTier(
            balance_level_range=_balance_range(raw.get("balance_level")),
            auxiliary_module_mission_hp=_number(
                raw.get("auxiliary_module_mission_hp"), "auxiliary_module_mission_hp"
            ),
            runway_mission_hp=_number(raw.get("runway_mission_hp"), "runway_mission_hp"),
            repair_base_hp=_number(raw.get("repair_base_hp"), "repair_base_hp"),
        )
        for item in _list(payload.get("airport_tiers"), "airport_tiers", exact=6)
        for raw in (_mapping(item, "airport_tier"),)
    )
    bombing_behavior_raw = _mapping(payload.get("bombing_point_behavior"), "bombing_point_behavior")
    bombing_point_behavior = BombingPointBehavior(
        hp_fire_mult=_number(bombing_behavior_raw.get("hp_fire_mult"), "hp_fire_mult"),
        fire_speed=_number(bombing_behavior_raw.get("fire_speed"), "fire_speed"),
        depletion_seconds_reference=_number(
            bombing_behavior_raw.get("depletion_seconds_reference"),
            "depletion_seconds_reference",
        ),
        fire_tail_evidence_kind=_text(
            bombing_behavior_raw.get("fire_tail_evidence_kind"),
            "fire_tail_evidence_kind",
        ),
        respawn_seconds=_number(bombing_behavior_raw.get("respawn_seconds"), "respawn_seconds"),
        respawn_evidence_kind=_text(
            bombing_behavior_raw.get("respawn_evidence_kind"),
            "respawn_evidence_kind",
        ),
    )
    airport_behavior_raw = _mapping(payload.get("airport_behavior"), "airport_behavior")
    airport_behavior = AirportBehavior(
        has_fire_tail=_boolean(airport_behavior_raw.get("has_fire_tail"), "has_fire_tail"),
        repair_timing_kind=_text(
            airport_behavior_raw.get("repair_timing_kind"), "repair_timing_kind"
        ),
        repair_evidence_kind=_text(
            airport_behavior_raw.get("repair_evidence_kind"), "repair_evidence_kind"
        ),
    )
    conversion_raw = _mapping(
        payload.get("bombing_zone_tnt_conversion"), "bombing_zone_tnt_conversion"
    )
    bombing_zone_tnt_conversion = BombingZoneTntConversion(
        hp_to_tnt_equivalent_tons=_number(
            conversion_raw.get("hp_to_tnt_equivalent_tons"),
            "hp_to_tnt_equivalent_tons",
        ),
        evidence_kind=_text(conversion_raw.get("evidence_kind"), "conversion_evidence_kind"),
    )
    weapon_catalog_rel = _text(provenance.get("weapon_catalog", ""), "weapon_catalog")
    if weapon_catalog_rel != STRIKE_WEAPON_DAMAGE_JSON:
        raise StrikeEncyclopediaError("invalid_weapon_catalog")
    weapon_catalog_source = _source_path(STRIKE_WEAPON_DAMAGE_JSON, None)
    expected_weapon_hash = provenance.get("weapon_catalog_sha256", "").upper()
    actual_weapon_hash = _sha256_text(weapon_catalog_source)
    if actual_weapon_hash != expected_weapon_hash:
        raise StrikeEncyclopediaError("weapon_catalog_hash_mismatch")
    splash_rel = _text(provenance.get("splash_model", ""), "splash_model")
    if splash_rel != BOMBING_ZONE_SPLASH_JSON:
        raise StrikeEncyclopediaError("invalid_splash_model")
    splash_source = _source_path(BOMBING_ZONE_SPLASH_JSON, None)
    expected_splash_hash = provenance.get("splash_model_sha256", "").upper()
    actual_splash_hash = _sha256_text(splash_source)
    if actual_splash_hash != expected_splash_hash:
        raise StrikeEncyclopediaError("splash_model_hash_mismatch")
    try:
        bombing_zone_splash = load_splash_model(_load_json(splash_source, "splash_model"))
    except HangarBaseDamageError as exc:
        raise StrikeEncyclopediaError("invalid_splash_model") from exc
    weapon_catalog = _load_json(weapon_catalog_source, "weapon_catalog")
    if weapon_catalog.get("schema") != _WEAPON_CATALOG_SCHEMA:
        raise StrikeEncyclopediaError("unsupported_weapon_catalog_schema")
    weapon_references = tuple(
        _load_weapon_reference(item)
        for item in _weapon_list(
            weapon_catalog.get("weapons"),
            "weapons",
        )
    )
    if len({weapon.weapon_id for weapon in weapon_references}) != len(weapon_references):
        raise StrikeEncyclopediaError("duplicate_weapon_id")
    if any(
        weapon.kind not in _WEAPON_KINDS or weapon.mission_damage_model not in _WEAPON_DAMAGE_MODELS
        for weapon in weapon_references
    ):
        raise StrikeEncyclopediaError("invalid_weapon_reference")
    practical_references = tuple(
        PracticalReference(
            reference_id=_text(raw.get("reference_id"), "reference_id"),
            scope=_text(raw.get("scope"), "scope"),
            weapon_id=_text(raw.get("weapon_id"), "practical_weapon_id"),
            weapon_count=int(_number(raw.get("weapon_count"), "weapon_count")),
            total_tnte_reference_kg=_number(
                raw.get("total_tnte_reference_kg"), "total_tnte_reference_kg"
            ),
            evidence_kind=_text(raw.get("evidence_kind"), "evidence_kind"),
            is_mission_damage_formula=bool(raw.get("is_mission_damage_formula")),
            source_url=_text(raw.get("source_url"), "source_url"),
        )
        for item in _list(payload.get("practical_references"), "practical_references")
        for raw in (_mapping(item, "practical_reference"),)
    )
    if any(reference.is_mission_damage_formula for reference in practical_references):
        raise StrikeEncyclopediaError("unsupported_mission_damage_formula")

    return StrikeEncyclopedia(
        schema=_SCHEMA,
        provenance=provenance,
        bombing_point_tiers=bombing_point_tiers,
        airport_tiers=airport_tiers,
        bombing_point_behavior=bombing_point_behavior,
        airport_behavior=airport_behavior,
        bombing_zone_tnt_conversion=bombing_zone_tnt_conversion,
        bombing_zone_splash=bombing_zone_splash,
        weapon_references=weapon_references,
        practical_references=practical_references,
        airfield_layouts=_load_airfield_layouts(catalog),
        disclaimer=_text(payload.get("disclaimer"), "disclaimer"),
    )


def _rectangle_corners(module: ModuleGeometry) -> tuple[tuple[float, float], ...]:
    dx = module.end_xz[0] - module.start_xz[0]
    dz = module.end_xz[1] - module.start_xz[1]
    length = math.hypot(dx, dz)
    if length <= 0.0:
        raise StrikeEncyclopediaError("zero_length_module")
    half = module.width_m / 2.0
    nx, nz = -dz / length * half, dx / length * half
    return (
        (module.start_xz[0] + nx, module.start_xz[1] + nz),
        (module.end_xz[0] + nx, module.end_xz[1] + nz),
        (module.end_xz[0] - nx, module.end_xz[1] - nz),
        (module.start_xz[0] - nx, module.start_xz[1] - nz),
    )


def project_airfield_scene(layout: AirfieldLayout, *, width: int, height: int) -> AirfieldScene:
    """Fit exact module rectangles into an original, source-derived vector scene."""

    if width < 240 or height < 180:
        raise ValueError("airfield scene is too small")
    raw_shapes = [(module, _rectangle_corners(module)) for module in layout.modules]
    all_points = [point for _, points in raw_shapes for point in points]
    center_x = (min(point[0] for point in all_points) + max(point[0] for point in all_points)) / 2
    center_z = (min(point[1] for point in all_points) + max(point[1] for point in all_points)) / 2
    angle = math.radians(-11.0)
    cosine, sine = math.cos(angle), math.sin(angle)

    def rotate(point: tuple[float, float]) -> tuple[float, float]:
        x = point[0] - center_x
        screen_y = center_z - point[1]
        return x * cosine - screen_y * sine, x * sine + screen_y * cosine

    rotated = [(module, tuple(rotate(point) for point in points)) for module, points in raw_shapes]
    rotated_points = [point for _, points in rotated for point in points]
    min_x = min(point[0] for point in rotated_points)
    max_x = max(point[0] for point in rotated_points)
    min_y = min(point[1] for point in rotated_points)
    max_y = max(point[1] for point in rotated_points)
    padding = 26.0
    scale = min(
        (width - padding * 2) / max(1.0, max_x - min_x),
        (height - padding * 2) / max(1.0, max_y - min_y),
    )
    offset_x = (width - (max_x - min_x) * scale) / 2 - min_x * scale
    offset_y = (height - (max_y - min_y) * scale) / 2 - min_y * scale

    shapes = []
    for module, points in rotated:
        projected = tuple((x * scale + offset_x, y * scale + offset_y) for x, y in points)
        label_position = (
            sum(point[0] for point in projected) / len(projected),
            sum(point[1] for point in projected) / len(projected),
        )
        shapes.append(
            SceneShape(
                module_id=module.module_id,
                label=module.label,
                color=_MODULE_COLORS[module.module_id],
                points=projected,
                label_position=label_position,
            )
        )
    return AirfieldScene(
        width=width,
        height=height,
        shapes=tuple(shapes),
        disclaimer="离线静态模块几何 · 非服务器命中框",
    )


__all__ = [
    "AirfieldLayout",
    "AirfieldScene",
    "AirportDurabilityTier",
    "AirportBehavior",
    "BombingPointDurabilityTier",
    "BombingPointBehavior",
    "ModuleGeometry",
    "PracticalReference",
    "SceneShape",
    "StrikeEncyclopedia",
    "StrikeEncyclopediaError",
    "WeaponReference",
    "load_strike_encyclopedia",
    "project_airfield_scene",
    "search_weapon_references",
    "wiki_weapon_samples",
]
