"""Battle-scoped timer persistence helpers."""

import hashlib
import json

from bomana.core.state import MapInfo, MapObjData

_NUMERIC_PARSE_ERRORS = (TypeError, ValueError)


def rounded_float(value: float) -> float:
    """Round values that participate in stable battle fingerprints."""
    return round(float(value), 6)


def build_battle_signature(
    map_info: MapInfo | None,
    mp: MapObjData | None,
) -> str | None:
    """Build a battle fingerprint from the current visible 8111 map context."""
    if map_info is None or not map_info.valid or mp is None or not mp.ok:
        return None

    try:
        payload = {
            "map_min": [rounded_float(value) for value in map_info.map_min],
            "map_max": [rounded_float(value) for value in map_info.map_max],
            "grid_size": [rounded_float(value) for value in map_info.grid_size],
            "grid_steps": [rounded_float(value) for value in map_info.grid_steps],
            "grid_zero": [rounded_float(value) for value in map_info.grid_zero],
            "zones": sorted(
                (
                    rounded_float(zone.x),
                    rounded_float(zone.y),
                    str(zone.color or ""),
                )
                for zone in mp.zones
            ),
            "airfields": sorted(
                (
                    rounded_float(airfield.x),
                    rounded_float(airfield.y),
                    str(airfield.color or ""),
                    bool(airfield.is_friendly),
                )
                for airfield in mp.airfields
            ),
        }
    except _NUMERIC_PARSE_ERRORS:
        return None

    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()
