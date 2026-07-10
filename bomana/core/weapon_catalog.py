"""Schema-backed runtime catalog for weapon fire-control data."""

from __future__ import annotations

import copy
import json
import math
import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bomana.config.static_data import (
    WEAPON_FIRE_CONTROL_JSON,
    WEAPON_FIRE_CONTROL_SCHEMA_JSON,
)
from bomana.utils.file_utils import resource_path

DEFAULT_WEAPON_ID = "su_fab100"
SELECTION_SOURCES = frozenset({"manual", "8111", "unknown"})


class WeaponCatalogError(ValueError):
    """Raised when the catalog or its shared schema is missing or invalid."""


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise WeaponCatalogError(f"unable to read {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WeaponCatalogError(f"invalid JSON in {label}: {path}") from exc
    if not isinstance(value, dict):
        raise WeaponCatalogError(f"{label} root must be an object")
    return value


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return Path(resource_path(path.as_posix()))


def _resolve_ref(root_schema: Mapping[str, Any], reference: str) -> Mapping[str, Any]:
    if not reference.startswith("#/"):
        raise WeaponCatalogError(f"unsupported schema reference: {reference}")
    current: Any = root_schema
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or part not in current:
            raise WeaponCatalogError(f"unresolved schema reference: {reference}")
        current = current[part]
    if not isinstance(current, Mapping):
        raise WeaponCatalogError(f"schema reference is not an object: {reference}")
    return current


def _matches_schema_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (
            isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
        )
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise WeaponCatalogError(f"unsupported schema type: {expected}")


def _validate_from_schema(
    value: Any,
    schema: Mapping[str, Any],
    root_schema: Mapping[str, Any],
    path: str = "$",
) -> None:
    """Validate the schema vocabulary used by the shared weapon schema.

    Required fields and version constants are deliberately read from the JSON
    schema itself. Runtime code therefore cannot drift by maintaining a second
    handwritten required-field list.
    """

    reference = schema.get("$ref")
    if isinstance(reference, str):
        _validate_from_schema(value, _resolve_ref(root_schema, reference), root_schema, path)
        return

    if "const" in schema and value != schema["const"]:
        raise WeaponCatalogError(f"{path} must equal schema const {schema['const']!r}")
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        raise WeaponCatalogError(f"{path} is not one of the schema enum values")

    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _matches_schema_type(value, expected_type):
        raise WeaponCatalogError(f"{path} must be of type {expected_type}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            missing = [name for name in required if name not in value]
            if missing:
                raise WeaponCatalogError(f"{path} missing schema-required fields: {missing}")

        min_properties = schema.get("minProperties")
        if isinstance(min_properties, int) and len(value) < min_properties:
            raise WeaponCatalogError(f"{path} has fewer than {min_properties} properties")

        properties = schema.get("properties", {})
        if isinstance(properties, Mapping):
            for key, child_schema in properties.items():
                if key in value and isinstance(child_schema, Mapping):
                    _validate_from_schema(value[key], child_schema, root_schema, f"{path}.{key}")

        additional = schema.get("additionalProperties")
        known = set(properties) if isinstance(properties, Mapping) else set()
        extras = [key for key in value if key not in known]
        if additional is False and extras:
            raise WeaponCatalogError(f"{path} contains fields forbidden by schema: {extras}")
        if isinstance(additional, Mapping):
            for key in extras:
                _validate_from_schema(value[key], additional, root_schema, f"{path}.{key}")

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            raise WeaponCatalogError(f"{path} has fewer than {min_items} items")
        if schema.get("uniqueItems") is True:
            encoded = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
            if len(encoded) != len(set(encoded)):
                raise WeaponCatalogError(f"{path} must contain unique items")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                _validate_from_schema(item, item_schema, root_schema, f"{path}[{index}]")

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            raise WeaponCatalogError(f"{path} is shorter than {min_length} characters")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            raise WeaponCatalogError(f"{path} does not match schema pattern")

    if isinstance(value, int | float) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, int | float) and value < minimum:
            raise WeaponCatalogError(f"{path} is below schema minimum")
        exclusive_minimum = schema.get("exclusiveMinimum")
        if isinstance(exclusive_minimum, int | float) and value <= exclusive_minimum:
            raise WeaponCatalogError(f"{path} is not above schema exclusive minimum")
        maximum = schema.get("maximum")
        if isinstance(maximum, int | float) and value > maximum:
            raise WeaponCatalogError(f"{path} is above schema maximum")


def _sort_key(weapon: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(weapon.get("display_name") or weapon.get("display_name_zh") or "").casefold(),
        str(weapon.get("id") or "").casefold(),
    )


class WeaponCatalog:
    """Load, query, and hold the current manual weapon selection."""

    def __init__(
        self,
        catalog_path: str | Path = WEAPON_FIRE_CONTROL_JSON,
        schema_path: str | Path = WEAPON_FIRE_CONTROL_SCHEMA_JSON,
    ) -> None:
        self.catalog_path = _resolve_path(catalog_path)
        self.schema_path = _resolve_path(schema_path)
        schema = _load_json(self.schema_path, label="weapon schema")
        payload = _load_json(self.catalog_path, label="weapon catalog")
        _validate_from_schema(payload, schema, schema)

        weapons = payload.get("weapons")
        aircraft_weapons = payload.get("aircraft_weapons")
        if not isinstance(weapons, dict) or not weapons:
            raise WeaponCatalogError("weapon catalog contains no weapons")
        if not isinstance(aircraft_weapons, dict):
            raise WeaponCatalogError("weapon catalog aircraft mapping must be an object")

        for weapon_id, weapon in weapons.items():
            if not isinstance(weapon, dict) or weapon.get("id") != weapon_id:
                raise WeaponCatalogError(f"weapon key/id mismatch: {weapon_id}")
        known_ids = set(weapons)
        for aircraft, ids in aircraft_weapons.items():
            if not isinstance(aircraft, str) or not isinstance(ids, list):
                raise WeaponCatalogError("invalid aircraft_weapons mapping")
            unknown_ids = [weapon_id for weapon_id in ids if weapon_id not in known_ids]
            if unknown_ids:
                raise WeaponCatalogError(
                    f"aircraft {aircraft!r} references unknown weapons: {unknown_ids}"
                )

        self.meta = copy.deepcopy(payload.get("meta", {}))
        self.schema_version = payload.get("schema_version")
        self._weapons: dict[str, dict[str, Any]] = copy.deepcopy(weapons)
        self._aircraft_weapons: dict[str, list[str]] = copy.deepcopy(aircraft_weapons)
        self._lock = threading.RLock()
        self._selection_source = "manual"
        self._selected_weapon_id = self._choose_default_weapon_id()

    def _choose_default_weapon_id(self) -> str:
        if DEFAULT_WEAPON_ID in self._weapons:
            return DEFAULT_WEAPON_ID
        for weapon_id, weapon in self._weapons.items():
            if (
                weapon.get("role") == "bomb"
                and weapon.get("propulsion") == "unpowered"
                and weapon.get("control") == "unguided"
                and weapon.get("planform") == "normal"
            ):
                return weapon_id
        return next(iter(self._weapons))

    @property
    def selected_weapon_id(self) -> str:
        with self._lock:
            return self._selected_weapon_id

    @property
    def selection_source(self) -> str:
        with self._lock:
            return self._selection_source

    @property
    def selected_weapon(self) -> dict[str, Any] | None:
        return self.get(self.selected_weapon_id)

    def selection_snapshot(self) -> tuple[str, str, dict[str, Any] | None]:
        """Atomically copy the selected ID, source, and immutable record view."""

        with self._lock:
            weapon_id = self._selected_weapon_id
            source = self._selection_source
            weapon = self._weapons.get(weapon_id)
            return weapon_id, source, copy.deepcopy(weapon) if weapon is not None else None

    def get(self, weapon_id: str) -> dict[str, Any] | None:
        weapon = self._weapons.get(str(weapon_id or ""))
        return copy.deepcopy(weapon) if weapon is not None else None

    def search(self, query: str = "", **filters: Any) -> list[dict[str, Any]]:
        """Return matching records in stable display-name/id order."""

        needle = str(query or "").strip().casefold()
        aircraft = str(filters.pop("aircraft", filters.pop("aircraft_type", "")) or "")
        limit_raw = filters.pop("limit", None)
        limit = int(limit_raw) if isinstance(limit_raw, int) and limit_raw >= 0 else None
        records: list[dict[str, Any]] = []
        compatible_ids = {item["id"] for item in self.for_aircraft(aircraft)} if aircraft else None

        for weapon in self._weapons.values():
            if compatible_ids is not None and weapon["id"] not in compatible_ids:
                continue
            if any(
                weapon.get(key) != expected
                for key, expected in filters.items()
                if expected is not None
            ):
                continue
            if needle:
                haystack = " ".join(
                    [
                        str(weapon.get("id") or ""),
                        str(weapon.get("display_name") or ""),
                        str(weapon.get("display_name_zh") or ""),
                        *[str(item) for item in weapon.get("trigger_groups", [])],
                    ]
                ).casefold()
                if needle not in haystack:
                    continue
            records.append(copy.deepcopy(weapon))

        records.sort(key=_sort_key)
        return records if limit is None else records[:limit]

    def for_aircraft(self, aircraft: str) -> list[dict[str, Any]]:
        aircraft_key = str(aircraft or "").strip().casefold()
        if not aircraft_key:
            return []
        ids: set[str] = set()
        for candidate, weapon_ids in self._aircraft_weapons.items():
            if candidate.casefold() == aircraft_key:
                ids.update(weapon_ids)
        for weapon_id, weapon in self._weapons.items():
            if any(str(item).casefold() == aircraft_key for item in weapon["compatible_aircraft"]):
                ids.add(weapon_id)
        records = [copy.deepcopy(self._weapons[weapon_id]) for weapon_id in ids]
        records.sort(key=_sort_key)
        return records

    def compatible(self, weapon_id: str, aircraft: str) -> bool:
        weapon = self._weapons.get(str(weapon_id or ""))
        aircraft_key = str(aircraft or "").strip().casefold()
        if weapon is None or not aircraft_key:
            return False
        if any(
            str(candidate).casefold() == aircraft_key
            for candidate in weapon.get("compatible_aircraft", [])
        ):
            return True
        return any(
            candidate.casefold() == aircraft_key and weapon_id in weapon_ids
            for candidate, weapon_ids in self._aircraft_weapons.items()
        )

    def set_selected(self, weapon_id: str, source: str = "manual") -> bool:
        weapon_id = str(weapon_id or "")
        source = str(source or "")
        if weapon_id not in self._weapons or source not in SELECTION_SOURCES:
            return False
        with self._lock:
            self._selected_weapon_id = weapon_id
            self._selection_source = source
        return True


_catalog_singleton: WeaponCatalog | None = None
_catalog_singleton_lock = threading.Lock()


def get_weapon_catalog() -> WeaponCatalog:
    """Return the process-wide shared weapon catalog, loading it on first use."""

    global _catalog_singleton
    if _catalog_singleton is None:
        with _catalog_singleton_lock:
            if _catalog_singleton is None:
                _catalog_singleton = WeaponCatalog()
    return _catalog_singleton


def _reset_weapon_catalog_for_tests() -> None:
    global _catalog_singleton
    with _catalog_singleton_lock:
        _catalog_singleton = None


__all__ = [
    "DEFAULT_WEAPON_ID",
    "SELECTION_SOURCES",
    "WeaponCatalog",
    "WeaponCatalogError",
    "get_weapon_catalog",
]
