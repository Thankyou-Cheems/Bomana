"""Source-backed, offline strike encyclopedia models and airfield diagrams."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bomana.config.static_data import EC_AIRFIELD_CATALOG_JSON, STRIKE_ENCYCLOPEDIA_JSON
from bomana.utils.file_utils import resource_path

_SCHEMA = "bomana_strike_encyclopedia/v1"
_CATALOG_SCHEMA = "wt_ec_airfield_template/v1"
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
class WeaponReference:
    weapon_id: str
    display_name: str
    mass_kg: float
    explosive_type: str
    raw_explosive_mass_kg: float
    tnte_reference_kg: float | None


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


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StrikeEncyclopediaError(f"invalid_{label}")
    return value.strip()


def _number(value: object, label: str, *, positive: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StrikeEncyclopediaError(f"invalid_{label}")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0):
        raise StrikeEncyclopediaError(f"invalid_{label}")
    return result


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
    actual_catalog_hash = hashlib.sha256(catalog_source.read_bytes()).hexdigest().upper()
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
    weapon_references = tuple(
        WeaponReference(
            weapon_id=_text(raw.get("weapon_id"), "weapon_id"),
            display_name=_text(raw.get("display_name"), "display_name"),
            mass_kg=_number(raw.get("mass_kg"), "mass_kg"),
            explosive_type=_text(raw.get("explosive_type"), "explosive_type"),
            raw_explosive_mass_kg=_number(
                raw.get("raw_explosive_mass_kg"), "raw_explosive_mass_kg"
            ),
            tnte_reference_kg=(
                None
                if raw.get("tnte_reference_kg") is None
                else _number(raw.get("tnte_reference_kg"), "tnte_reference_kg")
            ),
        )
        for item in _list(payload.get("weapon_references"), "weapon_references")
        for raw in (_mapping(item, "weapon_reference"),)
    )
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
        x, z = point[0] - center_x, point[1] - center_z
        return x * cosine - z * sine, x * sine + z * cosine

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
    "BombingPointDurabilityTier",
    "ModuleGeometry",
    "PracticalReference",
    "SceneShape",
    "StrikeEncyclopedia",
    "StrikeEncyclopediaError",
    "WeaponReference",
    "load_strike_encyclopedia",
    "project_airfield_scene",
]
